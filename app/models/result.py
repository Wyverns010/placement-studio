from __future__ import annotations

from pydantic import BaseModel

from app.models.brief import Brief, ClarifyQuestion, GateResult, Outcome
from app.models.scores import PersonaScore, PublisherScore


class CampaignResult(BaseModel):
    """Step 1's result. The browser sends it back with steps 3 and 4."""
    input_text: str  # the advertiser's text, with any clarify answers appended
    budget_usd: float | None = None  # the user's budget, if any, kept for step 4
    outcome: Outcome
    message: str | None
    brief: Brief | None
    gate: GateResult | None
    publishers: list[PublisherScore]
    personas: list[PersonaScore]
    clarify: list[ClarifyQuestion]
    notes: list[str] = []  # what a note changed, and what it couldn't apply
