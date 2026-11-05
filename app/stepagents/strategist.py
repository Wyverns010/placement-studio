"""Step ① Strategist agent: reads the brief, takes the gate's decision, and applies the user's
steer only through tool parameters (exclude catalog publishers/personas, add/remove vocabulary
categories, an age range within bounds). Code then assembles the stage-1 result from those
choices (app.pipeline.Stage1Plan); the gate's outcome is never the agent's to change."""
import json
import re

from agents import Agent, RunContextWrapper, function_tool
from pydantic import BaseModel

from app.create import clarify_questions
from app.gate import ConfidenceGate
from app.llm import LLMProvider
from app.match import (
    is_weak_fit,
    mark_stretch,
    score_personas,
    score_publishers,
    select_personas,
)
from app.models.brief import Brief, ClarifyQuestion, GateResult
from app.models.catalog import Catalog
from app.models.scores import PublisherScore
from app.models.tuning import Tuning
from app.pipeline import Stage1Plan
from app.prompts import CATEGORY_WORDS, render, wrap
from app.stepagents.guards import floor, floor_note, named_in_steer, unnamed_note
from app.stepagents.runtime import (
    AgentRuntime,
    Session,
    ToolRefused,
    keep_agent_notes,
    run_agent,
)
from app.understand import clamp_brief, understand

ROLE = "strategist"
GATE_WORDS = {
    "proceed": "proceed: build the campaign",
    "clarify": "clarify: the advertiser must answer questions first; no campaign is built",
    "out_of_scope": "out_of_scope: this catalog is the wrong place; no campaign is built",
    "no_signal": "no_signal: nothing to go on; no campaign is built",
}


class StrategistOutput(BaseModel):
    notes: list[str]  # parts of the steer it could not apply, and why (plain sentences)


class Stage1Workspace:
    """What the strategist's tools read and change. The brief and gate are computed once, by code."""

    def __init__(self, text: str, steer: str | None, *, llm: LLMProvider, gate: ConfidenceGate,
                 catalog: Catalog, t: Tuning, session: Session):
        self.text, self.steer = text, steer
        self.llm, self.gate_impl, self.catalog, self.t, self.session = llm, gate, catalog, t, session
        self._brief: Brief | None = None
        self._gate: GateResult | None = None
        self.adjusted: Brief | None = None
        self.exclude_publishers: frozenset[str] = frozenset()
        self.exclude_personas: frozenset[str] = frozenset()
        self.clarify: tuple[ClarifyQuestion, ...] | None = None

    @property
    def understood(self) -> Brief | None:
        """The brief, if a tool already paid for it (fallback reuses it)."""
        return self._brief

    def brief(self) -> Brief:
        if self._brief is None:
            self._brief = clamp_brief(understand(self.text, self.catalog, self.llm), self.t)
        return self._brief

    def current(self) -> Brief:
        return self.adjusted or self.brief()

    def gate(self) -> GateResult:
        if self._gate is None:
            self._gate = self.gate_impl.assess(self.text, self.brief())
        return self._gate

    def require_steer(self) -> None:
        if not self.steer:
            raise ToolRefused("there is no steer from the user, so nothing may change")

    def recommended(self, brief: Brief, exclude: frozenset[str]) -> list[PublisherScore]:
        """The publishers stage 1 would recommend (weak fit: code's stretch picks)."""
        scored = score_publishers(brief, self.catalog, self.t, exclude)
        if is_weak_fit(scored, self.t):
            scored = mark_stretch(scored, self.t, exclude)
        return [s for s in scored if s.recommended]

    def guard(self, brief: Brief, exclude: frozenset[str]) -> None:
        """Validate the agent's choices against the steer (code, not the prompt): refuse a plan
        that shrinks the recommended set below the floor, excludes a publisher the steer doesn't
        name, or recommends a publisher below the cut-off that wasn't recommended before."""
        pubs = {p.id: p for p in self.catalog.publishers}
        original = self.recommended(self.brief(), frozenset())
        orig_ids = [s.publisher_id for s in original]
        after = self.recommended(brief, exclude)
        after_ids = {s.publisher_id for s in after}
        n = floor(self.t.agents.min_recommended_after_steer, len(original))
        if len(after) < n:
            kept = [pubs[i].name for i in orig_ids if i not in after_ids] or [pubs[i].name for i in orig_ids]
            self.session.note(floor_note(kept, n))
            raise ToolRefused(f"a steer may narrow the recommended publishers but not below {n}; "
                              "nothing changed")
        unnamed = [i for i in sorted(exclude)
                   if not named_in_steer(self.steer, pubs[i].name, pubs[i].category)]
        if unnamed:
            self.session.note(unnamed_note([pubs[i].name for i in unnamed]))
            raise ToolRefused("the steer does not name these as publishers to avoid: "
                              f"{', '.join(unnamed)}; nothing changed")
        cut = self.t.publisher.cutoff
        low = [s.publisher_id for s in after
               if not s.stretch and s.fit < cut and s.publisher_id not in orig_ids]
        if low:
            raise ToolRefused(f"below the {cut:.2f} cut-off, so it can't be recommended: "
                              f"{', '.join(low)}; nothing changed")

    def plan(self) -> Stage1Plan:
        return Stage1Plan(brief=self.brief(), adjusted=self.adjusted,
                          exclude_publishers=self.exclude_publishers,
                          exclude_personas=self.exclude_personas, clarify=self.clarify)

    def change_notes(self) -> list[str]:
        """One plain sentence per applied change, written by code from the final choices."""
        notes = []
        pubs = {p.id: p for p in self.catalog.publishers}
        for pid in sorted(self.exclude_publishers):
            p = pubs[pid]
            notes.append(f"Left out {p.name} ({CATEGORY_WORDS.get(p.category, p.category.replace("_", " "))}) because of your note.")
        names = {p.id: p.name for p in self.catalog.personas}
        for pid in sorted(self.exclude_personas):
            notes.append(f"Left out the persona {names[pid]} because of your note.")
        if self.adjusted is not None:
            b, a = self.brief(), self.adjusted
            added = [c for c in a.categories if c not in b.categories]
            removed = [c for c in b.categories if c not in a.categories]
            if added:
                notes.append(f"Added {', '.join(added)} to the brief's categories because of your note.")
            if removed:
                notes.append(f"Removed {', '.join(removed)} from the brief's categories because of your note.")
            if (a.age_min, a.age_max) != (b.age_min, b.age_max):
                notes.append(f"Set the audience ages to {a.age_min}–{a.age_max} because of your note.")
        if self.steer and self._gate is not None and self._gate.outcome != "proceed":
            notes.append(f"The gate decided {self._gate.outcome}; a note can't change that.")
        return notes


def _ws(ctx: RunContextWrapper[Stage1Workspace]) -> Stage1Workspace:
    return ctx.context


def _ids(given: list[str], items: dict[str, str], kind: str) -> list[str]:
    """Ids for what the agent passed: an id, or a name in any case, "The" optional ("busy parent")."""
    def key(name: str) -> str:
        return re.sub(r"^the\s+", "", name.strip().lower())
    by_name = {key(name): i for i, name in items.items()}
    out, bad = [], []
    for g in given:
        i = g if g in items else by_name.get(key(g))
        (out if i else bad).append(i or g)
    if bad:
        valid = ", ".join(f"{i} ({n})" for i, n in items.items())
        raise ToolRefused(f"unknown {kind}: {', '.join(bad)}. Valid ids: {valid}")
    return out


def _brief_view(b: Brief) -> str:
    return json.dumps({"product": b.product, "audience_type": b.audience_type,
                       "categories": b.categories, "adjacent_categories": b.adjacent_categories,
                       "price_tier": b.price_tier, "age_min": b.age_min, "age_max": b.age_max,
                       "gender_skew": b.gender_skew})


@function_tool(failure_error_function=None)
def read_brief(ctx: RunContextWrapper[Stage1Workspace]) -> str:
    """Read the advertiser's brief (understood once by code, in the catalog's vocabulary)."""
    ws = _ws(ctx)
    return ws.session.tool(ROLE, "read_brief", {}, lambda: _brief_view(ws.current()))


@function_tool(failure_error_function=None)
def decide(ctx: RunContextWrapper[Stage1Workspace]) -> str:
    """The gate's decision on the advertiser's text. Final: you cannot change it."""
    ws = _ws(ctx)
    return ws.session.tool(ROLE, "decide", {}, lambda: GATE_WORDS[ws.gate().outcome])


@function_tool(failure_error_function=None)
def adjust_brief(ctx: RunContextWrapper[Stage1Workspace], add_categories: list[str],
                 remove_categories: list[str], age_min: int | None, age_max: int | None) -> str:
    """Apply the user's steer to the brief: categories from the catalog vocabulary to add or remove,
    and an audience age range (null to keep). Only when the steer asks for it."""
    ws = _ws(ctx)

    def run() -> str:
        ws.require_steer()
        vocab = set(ws.catalog.vocab)
        bad = [c for c in add_categories + remove_categories if c not in vocab]
        if bad:
            raise ToolRefused(f"not in the catalog vocabulary: {', '.join(bad)}")
        unnamed = [c for c in remove_categories if not named_in_steer(ws.steer, None, c)]
        if unnamed:
            ws.session.note(f"Kept {', '.join(CATEGORY_WORDS.get(c, c.replace("_", " ")) for c in unnamed)} in the brief: "
                            "your note doesn't ask to drop it.")
            raise ToolRefused(f"the steer does not ask to drop: {', '.join(unnamed)}")
        b = ws.current()
        cats = [c for c in b.categories if c not in remove_categories]
        cats += [c for c in add_categories if c not in cats]
        if len(cats) > ws.t.input.brief_categories_max:
            raise ToolRefused("too many categories")
        lo, hi = b.age_min, b.age_max
        if age_min is not None or age_max is not None:
            a = ws.t.audience
            lo = age_min if age_min is not None else a.age_floor
            hi = age_max if age_max is not None else a.age_ceiling
            if not a.age_floor <= lo <= hi <= a.age_ceiling:
                raise ToolRefused(f"ages must satisfy {a.age_floor} <= min <= max <= {a.age_ceiling}")
        adjusted = b.model_copy(update={
            "categories": cats,
            "adjacent_categories": [c for c in b.adjacent_categories if c not in cats
                                    and c not in remove_categories],
            "age_min": lo, "age_max": hi})
        ws.guard(adjusted, ws.exclude_publishers)
        ws.adjusted = adjusted
        return _brief_view(ws.adjusted)

    args = {"add": add_categories, "remove": remove_categories, "age_min": age_min, "age_max": age_max}
    return ws.session.tool(ROLE, "adjust_brief", args, run)


@function_tool(failure_error_function=None)
def rank_publishers(ctx: RunContextWrapper[Stage1Workspace], exclude_ids: list[str]) -> str:
    """Score every catalog publisher (code) and show which are recommended. Pass publisher ids the
    user's steer rules out in exclude_ids (replaces earlier exclusions); [] for none."""
    ws = _ws(ctx)

    def run() -> str:
        if exclude_ids:
            ws.require_steer()
        ids = _ids(exclude_ids, {p.id: p.name for p in ws.catalog.publishers}, "publisher ids")
        ws.guard(ws.current(), frozenset(ids))
        ws.exclude_publishers = frozenset(ids)
        cat = {p.id: p.category for p in ws.catalog.publishers}
        scored = score_publishers(ws.current(), ws.catalog, ws.t, ws.exclude_publishers)
        return json.dumps([{"id": s.publisher_id, "name": s.name, "category": cat[s.publisher_id],
                            "fit": s.fit, "recommended": s.recommended,
                            "excluded": s.publisher_id in ws.exclude_publishers} for s in scored])

    return ws.session.tool(ROLE, "rank_publishers", {"exclude_ids": exclude_ids}, run)


@function_tool(failure_error_function=None)
def pick_personas(ctx: RunContextWrapper[Stage1Workspace], exclude_ids: list[str]) -> str:
    """Score the shopper personas (code) and show the ones selected. Pass persona ids the user's
    steer rules out in exclude_ids (replaces earlier exclusions); [] for none."""
    ws = _ws(ctx)

    def run() -> str:
        if exclude_ids:
            ws.require_steer()
        ids = _ids(exclude_ids, {p.id: p.name for p in ws.catalog.personas}, "persona ids")
        ws.exclude_personas = frozenset(ids)
        recs = ws.recommended(ws.current(), ws.exclude_publishers)
        scores = [p for p in score_personas(ws.current(), ws.catalog, ws.t, recs)
                  if p.persona_id not in ws.exclude_personas]
        chosen = {p.persona_id for p in select_personas(scores, ws.t)}
        return json.dumps([{"id": p.persona_id, "name": p.name, "fit": p.fit,
                            "selected": p.persona_id in chosen} for p in scores])

    return ws.session.tool(ROLE, "pick_personas", {"exclude_ids": exclude_ids}, run)


@function_tool(failure_error_function=None)
def ask_questions(ctx: RunContextWrapper[Stage1Workspace]) -> str:
    """The clarifying questions for the advertiser. Only when the gate decided clarify."""
    ws = _ws(ctx)

    def run() -> str:
        if ws.gate().outcome != "clarify":
            raise ToolRefused("questions are only asked when the gate decided clarify")
        if ws.clarify is None:
            ws.clarify = tuple(clarify_questions(ws.text, ws.current(), ws.llm, ws.catalog, ws.t))
        return json.dumps([q.question for q in ws.clarify])

    return ws.session.tool(ROLE, "ask_questions", {}, run)


def build_agent(runtime: AgentRuntime) -> Agent:
    return Agent(name=ROLE, instructions=render("agents/strategist"), model=runtime.model(ROLE),
                 model_settings=runtime.settings(), output_type=StrategistOutput,
                 tools=[read_brief, decide, adjust_brief, rank_publishers, pick_personas, ask_questions])


def agent_input(text: str, steer: str | None) -> str:
    return wrap("advertiser_text", text) + "\n" + wrap("user_steer", steer or "")


async def run(ws: Stage1Workspace, runtime: AgentRuntime) -> None:
    """Run the strategist; its choices stay in `ws`, its own notes (what it could not apply, no
    numbers: those come from code) go to the session after code's change notes."""
    result = await run_agent(ws.session, build_agent(runtime), agent_input(ws.text, ws.steer), ws, ROLE)
    ws.gate()  # code's decision, whether or not the agent asked
    for n in ws.change_notes():
        ws.session.note(n)
    out: StrategistOutput = result.final_output
    keep_agent_notes(ws.session, out.notes,
                     [p.name for p in ws.catalog.publishers] + [p.name for p in ws.catalog.personas])
