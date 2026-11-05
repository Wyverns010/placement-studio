"""Request bodies. A note is free text the user adds to a step; blank means none."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.models.ads import Creative
from app.models.brief import Brief
from app.models.result import CampaignResult

Note = Annotated[str, StringConstraints(strip_whitespace=True)] | None


class CampaignIn(BaseModel):
    text: str
    budget_usd: float | None = None
    answers: dict[str, str] | None = None  # clarify answers, appended to the text
    note: Note = None
    brief: Brief | None = None  # sent back with a note, so the text isn't read again


class StageIn(CampaignResult):
    """Step 1's result sent back for step 3, with an optional note."""
    note: Note = None


class ConfigIn(StageIn):
    creatives: list[Creative]
