"""Step 1's request body. A note is free text the user adds to a step; blank means none."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.models.brief import Brief

Note = Annotated[str, StringConstraints(strip_whitespace=True)] | None


class CampaignIn(BaseModel):
    text: str
    budget_usd: float | None = None
    answers: dict[str, str] | None = None  # clarify answers, appended to the text
    note: Note = None
    brief: Brief | None = None  # sent back with a note, so the text isn't read again

