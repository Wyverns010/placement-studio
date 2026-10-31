"""Step ③ Media planner agent: turns the user's steer ("under $5k", "drop Ruffco", "front-load
launch week") into validated tool calls. A budget is accepted only if code finds that amount in
the steer and it is within the budget bounds; the config itself is always built by code
(app.pipeline.make_config) from the recorded choices."""
import json
import re
from typing import Literal

from agents import Agent, RunContextWrapper, function_tool
from pydantic import BaseModel

from app.budget import recommended_budget
from app.catalog import Catalog
from app.models import Brief, CampaignConfig, Creative, GateResult, PersonaScore, PublisherScore
from app.pipeline import is_weak, make_config, recommended_of
from app.prompts import render, wrap_steer
from app.stepagents.runtime import AgentRuntime, Session, ToolRefused, run_agent
from app.tuning import Tuning

ROLE = "media_planner"
PACE_WORD = {"front_loaded": "front-loaded", "even": "even", "accelerated": "accelerated"}
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(k|m|thousand|million|mil)?\b", re.IGNORECASE)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mil": 1e6, "million": 1e6}


def steer_amounts(steer: str | None) -> set[float]:
    """Every amount written in the steer, in dollars ("$5k" -> 5000, "12,500" -> 12500)."""
    out = set()
    for num, unit in _AMOUNT.findall(steer or ""):
        digits = num.replace(",", "")
        try:
            v = float(digits)
        except ValueError:
            continue
        out.add(round(v * _MULT.get(unit.lower(), 1), 2))
    return out


class PlannerOutput(BaseModel):
    notes: list[str]  # parts of the steer it could not apply, and why


class PlanDesk:
    """The stage-3 inputs (already validated by the API) and the planner's recorded choices."""

    def __init__(self, brief: Brief, gate: GateResult, publishers: list[PublisherScore],
                 personas: list[PersonaScore], creatives: list[Creative], budget_usd: float | None,
                 steer: str | None, *, catalog: Catalog, t: Tuning, session: Session):
        self.brief, self.gate, self.publishers = brief, gate, publishers
        self.personas, self.creatives, self.request_budget = personas, creatives, budget_usd
        self.steer, self.catalog, self.t, self.session = steer, catalog, t, session
        self.budget: float | None = None  # from the steer, via set_budget
        self.exclude: frozenset[str] = frozenset()
        self.pacing: str | None = None

    def require_steer(self) -> None:
        if not self.steer:
            raise ToolRefused("there is no steer from the user, so nothing may change")

    def recommended_usd(self) -> float:
        pubs = [p for p in recommended_of(self.publishers) if p.publisher_id not in self.exclude]
        return recommended_budget(self.brief, pubs, self.catalog, is_weak(self.publishers), self.t).usd

    def build(self) -> CampaignConfig:
        budget = self.request_budget if self.request_budget is not None else self.budget
        return make_config(self.brief, self.gate, self.publishers, self.personas, self.creatives,
                           budget, catalog=self.catalog, t=self.t, exclude=self.exclude,
                           pacing_override=self.pacing)

    def change_notes(self) -> list[str]:
        notes = []
        if self.budget is not None and self.request_budget is None:
            notes.append(f"Budget set to ${self.budget:,.0f}/mo from your note "
                         f"(recommended ${self.recommended_usd():,.0f}).")
        names = {p.publisher_id: p.name for p in self.publishers}
        for pid in sorted(self.exclude):
            notes.append(f"Dropped {names.get(pid, pid)} from the line items because of your note.")
        if self.pacing:
            notes.append(f"Pacing set to {PACE_WORD[self.pacing]} because of your note.")
        return notes


def _desk(ctx: RunContextWrapper[PlanDesk]) -> PlanDesk:
    return ctx.context


@function_tool(failure_error_function=None)
def recommend_budget(ctx: RunContextWrapper[PlanDesk]) -> str:
    """The recommended monthly budget (code) for the current line items, and the budget bounds."""
    d = _desk(ctx)
    b = d.t.budget
    return d.session.tool(ROLE, "recommend_budget", {}, lambda: json.dumps({
        "recommended_usd": d.recommended_usd(), "min_usd": b.min_usd, "max_usd": b.max_usd,
        "budget_field_usd": d.request_budget}))


@function_tool(failure_error_function=None)
def set_budget(ctx: RunContextWrapper[PlanDesk], monthly_usd: float) -> str:
    """Set the monthly budget to an amount the user wrote in the steer (validated by code)."""
    d = _desk(ctx)

    def run() -> str:
        d.require_steer()
        b = d.t.budget
        if d.request_budget is not None:
            raise ToolRefused("the user's budget field is set and wins over the steer")
        if round(monthly_usd, 2) not in steer_amounts(d.steer):
            raise ToolRefused("that amount is not written in the user's steer")
        if not b.min_usd <= monthly_usd <= b.max_usd:
            raise ToolRefused(f"the budget must be between ${b.min_usd:,.0f} and ${b.max_usd:,.0f}")
        d.budget = float(monthly_usd)
        return f"Budget set to ${d.budget:,.0f}/mo."

    return d.session.tool(ROLE, "set_budget", {"monthly_usd": monthly_usd}, run)


@function_tool(failure_error_function=None)
def exclude_publishers(ctx: RunContextWrapper[PlanDesk], publisher_ids: list[str]) -> str:
    """Drop recommended publishers the steer rules out from the line items (replaces earlier
    exclusions); at least one must remain."""
    d = _desk(ctx)

    def run() -> str:
        d.require_steer()
        rec = {p.publisher_id for p in recommended_of(d.publishers)}
        bad = [i for i in publisher_ids if i not in rec]
        if bad:
            raise ToolRefused(f"not a recommended publisher: {', '.join(bad)}")
        if rec <= set(publisher_ids):
            raise ToolRefused("at least one publisher must remain")
        d.exclude = frozenset(publisher_ids)
        return f"Line items now: {', '.join(sorted(rec - d.exclude))}."

    return d.session.tool(ROLE, "exclude_publishers", {"publisher_ids": publisher_ids}, run)


@function_tool(failure_error_function=None)
def set_pacing(ctx: RunContextWrapper[PlanDesk],
               pacing: Literal["front_loaded", "even", "accelerated"]) -> str:
    """Override pacing when the steer asks for it (code picks pacing otherwise)."""
    d = _desk(ctx)

    def run() -> str:
        d.require_steer()
        d.pacing = pacing
        return f"Pacing set to {pacing}."

    return d.session.tool(ROLE, "set_pacing", {"pacing": pacing}, run)


@function_tool(failure_error_function=None)
def preview_config(ctx: RunContextWrapper[PlanDesk]) -> str:
    """Build the config with the current choices (code) and show its budget, pacing, frequency
    cap and line items."""
    d = _desk(ctx)

    def run() -> str:
        c = d.build()
        return json.dumps({"budget": dict(c.budget), "frequency_cap": c.frequency_cap,
                           "line_items": [{"publisher_id": li.publisher_id, "budget_usd": li.budget_usd}
                                          for li in c.line_items]})

    return d.session.tool(ROLE, "preview_config", {}, run)


def build_agent(runtime: AgentRuntime, desk: PlanDesk) -> Agent:
    pubs = "\n".join(f"- {p.publisher_id}: {p.name}" for p in recommended_of(desk.publishers))
    return Agent(name=ROLE, instructions=render("agents/media_planner", publishers=pubs),
                 model=runtime.model(ROLE), model_settings=runtime.settings(),
                 output_type=PlannerOutput,
                 tools=[recommend_budget, set_budget, exclude_publishers, set_pacing, preview_config])


async def run(desk: PlanDesk, runtime: AgentRuntime) -> None:
    result = await run_agent(desk.session, build_agent(runtime, desk), wrap_steer(desk.steer), desk, ROLE)
    for n in desk.change_notes():
        desk.session.note(n)
    if desk.request_budget is not None and steer_amounts(desk.steer):
        desk.session.note("Your budget field wins over an amount in the note.")
    out: PlannerOutput = result.final_output
    for n in out.notes:
        if not any(ch.isdigit() for ch in n):  # numbers come from code only
            desk.session.note(n)
