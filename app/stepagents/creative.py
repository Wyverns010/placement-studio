"""Step ② Creative team: a Copywriter agent per persona (gpt-5.5) and a Critic agent (gpt-5.4-mini)
the copywriter calls as a tool (SDK agents-as-tools). The critic runs code's copy checks through
its own tool and returns accept or revision notes. Code bounds the loop (agents.critic_max_rounds
reviews per ad; later requests are refused) and re-checks every final ad: whatever code still
rejects ships flagged in fact_violations, never waved through."""
import asyncio
import json
import time

from agents import Agent, FunctionTool, RunContextWrapper, function_tool
from pydantic import BaseModel

from app.catalog import Catalog, Persona
from app.copycheck import ad_problems, headlines_similar, normalise_headline
from app.create import (_persona_block, _playbook, _publisher_block, creative_targets,
                        rewrite_problems, set_problems)
from app.models import Brief, Creative, PersonaScore, PublisherScore
from app.pipeline import recommended_of
from app.prompts import (feedback, render, wrap_advertiser_text, wrap_current_ad, wrap_steer,
                         wrap_user_note)
from app.stepagents.runtime import AgentRuntime, Session, run_agent
from app.tuning import Tuning

_TIMES = {1: "once", 2: "twice"}


class AdDraft(BaseModel):
    headline: str
    body: str
    cta: str
    why: str


class Review(BaseModel):
    accept: bool
    notes: list[str]  # what to change, if not accepted


class AdDesk:
    """One persona's ad: what both agents' tools read. `heads` is shared by the whole team (each
    persona's latest headline), so the critic can catch duplicates across ads."""

    def __init__(self, text: str, brief: Brief, persona: Persona, pub: PublisherScore,
                 heads: dict[str, str], names: dict[str, str], *, catalog: Catalog, t: Tuning,
                 session: Session, steer: str | None = None, note: str | None = None,
                 current: Creative | None = None):
        self.text, self.brief, self.persona, self.pub = text, brief, persona, pub
        self.heads, self.names = heads, names
        self.catalog, self.t, self.session = catalog, t, session
        self.steer, self.note, self.current = steer, note, current
        self.rounds = 0

    def creative(self, d: AdDraft) -> Creative:
        base = self.current or Creative(creative_id=f"cr_{self.persona.id}", persona_id=self.persona.id,
                                        publisher_id=self.pub.publisher_id, headline="", body="",
                                        cta="", why="")
        return base.model_copy(update={"headline": d.headline, "body": d.body, "cta": d.cta,
                                       "why": d.why, "fact_violations": []})

    def problems(self, c: Creative) -> list[str]:
        """Code's verdict on one draft (the same checks the final ad gets)."""
        others = [(h, pid) for pid, h in self.heads.items() if pid != self.persona.id]
        if self.current is not None:
            ps = rewrite_problems(c, self.current, self.text, self.persona.name, self.brief.product,
                                  others, self.names, self.t)
            return [p.message for p in ps]
        out = [p.message for p in ad_problems(c, self.text, self.persona.name, self.t)]
        if normalise_headline(c.headline) == normalise_headline(self.brief.product or ""):
            out.append(feedback("headline_product"))
        sim = self.t.creative.headline_similarity
        dup = next((pid for h, pid in others if headlines_similar(h, c.headline, sim)), None)
        if dup:
            out.append(feedback("headline_duplicate", name=self.names.get(dup, dup)))
        return out


@function_tool(failure_error_function=None)
def check_copy(ctx: RunContextWrapper[AdDesk], headline: str, body: str, cta: str) -> str:
    """Run code's copy checks on a draft: invented facts, length, generic copy, parroting and
    duplicate headlines. Returns the problems, or that there are none."""
    desk = ctx.context

    def run() -> str:
        probs = desk.problems(desk.creative(AdDraft(headline=headline, body=body, cta=cta, why="")))
        return json.dumps(probs) if probs else "No problems found by code."

    return desk.session.tool("critic", "check_copy", {"headline": headline}, run)


def _critic(runtime: AgentRuntime, desk: AdDesk) -> Agent:
    t = desk.t
    return Agent(name="critic", model=runtime.model("critic"), model_settings=runtime.settings(),
                 instructions=render("agents/critic", playbook=_playbook(t),
                                     persona=_persona_block(desk.persona),
                                     publisher=_publisher_block(desk.pub, desk.catalog)),
                 tools=[check_copy], output_type=Review)


async def _review_json(result) -> str:
    out = result.final_output
    return out.model_dump_json() if isinstance(out, BaseModel) else str(out)


def _review_tool(runtime: AgentRuntime, desk: AdDesk) -> FunctionTool:
    """The critic as the copywriter's `review_draft` tool, bounded by code to critic_max_rounds."""
    t, session = desk.t, desk.session
    inner = _critic(runtime, desk).as_tool(
        "review_draft", "Have the critic review a full draft.", parameters=AdDraft,
        custom_output_extractor=_review_json, failure_error_function=None,
        max_turns=t.agents.max_turns["critic"], hooks=session.hooks, run_config=session.run_config)

    async def invoke(ctx, args_json: str):
        d = ctx.context
        draft = AdDraft.model_validate_json(args_json)
        d.heads[d.persona.id] = draft.headline
        args = {"persona": d.persona.id, "headline": draft.headline}
        if d.rounds >= t.agents.critic_max_rounds:
            msg = ("Refused: the review limit is reached. Return your best draft now; code will "
                   "flag anything still wrong.")
            session.record("copywriter", "review_draft", args, msg, 0)
            return msg
        if session.cost_usd > session.cap * t.agents.critic_stop_fraction:
            msg = ("Refused: this step's budget for reviews is used up. Return your best draft "
                   "now; code will flag anything still wrong.")
            session.record("copywriter", "review_draft", args, msg, 0)
            return msg
        d.rounds += 1
        t0 = time.perf_counter()
        out = await inner.on_invoke_tool(ctx, args_json)
        session.record("copywriter", "review_draft", args, str(out),
                       int((time.perf_counter() - t0) * 1000))
        return out

    return FunctionTool(name=inner.name, description=inner.description,
                        params_json_schema=inner.params_json_schema, on_invoke_tool=invoke,
                        strict_json_schema=inner.strict_json_schema)


def _copywriter(runtime: AgentRuntime, desk: AdDesk, others: list[Persona]) -> Agent:
    t = desk.t
    c = t.creative
    system = render(
        "agents/copywriter",
        product=desk.brief.product or feedback("product_default"),
        facts="\n".join(f"- {f}" for f in desk.brief.facts) or feedback("facts_default"),
        persona=_persona_block(desk.persona), publisher=_publisher_block(desk.pub, desk.catalog),
        others="\n".join(feedback("other_persona_line", name=o.name,
                                  preference=o.messaging_preferences[0] if o.messaging_preferences
                                  else feedback("none")) for o in others) or feedback("no_others"),
        playbook=_playbook(t), headline_max=c.headline_max_chars, body_max=c.body_max_chars,
        cta_max=c.cta_max_chars, rounds=t.agents.critic_max_rounds)
    return Agent(name="copywriter", model=runtime.model("copywriter"),
                 model_settings=runtime.settings(), instructions=system,
                 tools=[_review_tool(runtime, desk)], output_type=AdDraft)


def _input(desk: AdDesk) -> str:
    user = wrap_advertiser_text(desk.text) + "\n" + wrap_steer(desk.steer)
    if desk.current is not None:
        cur, c = desk.current, desk.t.creative
        flat = lambda s, n: " ".join(s.replace('"', "").split())[:n]  # noqa: E731
        ad = feedback("current_ad_fields", headline=flat(cur.headline, c.headline_max_chars),
                      body=flat(cur.body, c.body_max_chars), cta=flat(cur.cta, c.cta_max_chars))
        user += feedback("rewrite_current", ad=wrap_current_ad(ad))
        if desk.note:
            user += feedback("rewrite_note", note=wrap_user_note(desk.note))
    return user


async def _write(runtime: AgentRuntime, desk: AdDesk, others: list[Persona]) -> AdDraft:
    result = await run_agent(desk.session, _copywriter(runtime, desk, others), _input(desk), desk,
                             "copywriter")
    draft: AdDraft = result.final_output
    desk.heads[desk.persona.id] = draft.headline
    return draft


def _desk_note(desk: AdDesk, c: Creative) -> str:
    who = desk.persona.name.removeprefix("The ")
    s = (f"The {who} ad: the critic reviewed it {_TIMES.get(desk.rounds, 'more than twice')}"
         if desk.rounds else f"The {who} ad: not sent to the critic")
    if c.fact_violations:
        s += "; code still flags it (see the chips)"
    return s + "."


def projected_usd(n_ads: int, t: Tuning) -> float:
    """What the creative team is expected to cost for n ads (measured per-ad mean)."""
    return n_ads * t.agents.creative_est_usd_per_ad


def n_ads(personas: list[PersonaScore], publishers: list[PublisherScore], catalog: Catalog) -> int:
    return len(creative_targets(personas, recommended_of(publishers), catalog))


async def write_all(text: str, brief: Brief, publishers: list[PublisherScore],
                    personas: list[PersonaScore], steer: str | None, *, catalog: Catalog,
                    t: Tuning, runtime: AgentRuntime, session: Session) -> list[Creative]:
    """One ad per persona, written concurrently; code places them and checks the final set."""
    targets = creative_targets(personas, recommended_of(publishers), catalog)
    if not targets:
        return []
    heads: dict[str, str] = {}
    names = {p.id: p.name for p, _ in targets}
    desks = [AdDesk(text, brief, p, pub, heads, names, catalog=catalog, t=t, session=session,
                    steer=steer) for p, pub in targets]
    drafts = await asyncio.gather(*(
        _write(runtime, d, [o for o, _ in targets if o.id != d.persona.id]) for d in desks))
    out = [d.creative(dr) for d, dr in zip(desks, drafts)]
    set_problems(out, text, brief.product, names, t)
    if steer:
        session.note("Your note went to the copywriter and the critic as guidance (never as facts).")
    for d, c in zip(desks, out):
        session.note(_desk_note(d, c))
    return out


async def rewrite_one(text: str, brief: Brief, publishers: list[PublisherScore],
                      personas: list[PersonaScore], creatives: list[Creative], persona_id: str,
                      note: str | None, steer: str | None, *, catalog: Catalog, t: Tuning,
                      runtime: AgentRuntime, session: Session) -> Creative:
    """Rewrite one persona's ad on the same publisher; the same final checks as Regenerate."""
    by_id = {p.id: p for p in catalog.personas}
    current = next(c for c in creatives if c.persona_id == persona_id)
    persona = by_id[persona_id]
    pub = next((p for p in publishers if p.publisher_id == current.publisher_id), None)
    if pub is None:
        p = catalog.publisher(current.publisher_id)
        pub = PublisherScore(publisher_id=p.id, name=p.name, fit=0.0, factors=[], recommended=True,
                             stretch=False, reason="")
    heads = {c.persona_id: c.headline for c in creatives if c.persona_id != persona_id}
    names = {c.persona_id: by_id[c.persona_id].name for c in creatives if c.persona_id in by_id}
    desk = AdDesk(text, brief, persona, pub, heads, names, catalog=catalog, t=t, session=session,
                  steer=steer, note=note, current=current)
    others = [by_id[c.persona_id] for c in creatives if c.persona_id != persona_id and c.persona_id in by_id]
    draft = await _write(runtime, desk, others)
    out = desk.creative(draft)
    other_heads = [(c.headline, c.persona_id) for c in creatives if c.persona_id != persona_id]
    out.fact_violations = [p.message for p in rewrite_problems(
        out, current, text, persona.name, brief.product, other_heads, names, t)]
    if note or steer:
        session.note("Your note went to the copywriter and the critic as guidance (never as facts).")
    session.note(_desk_note(desk, out))
    return out
