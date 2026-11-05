from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.constants.ads import CTA_OPTIONS

Cta = Literal[CTA_OPTIONS]  # type: ignore[valid-type]


class Creative(BaseModel):
    persona_id: str  # one ad per persona, so the persona id is the ad's id
    publisher_id: str
    headline: str
    body: str
    cta: str
    why: str
    fact_violations: list[str] = []  # what code still rejects in the final ad


class Draft(BaseModel):
    """One Copywriter call's ad."""
    headline: str
    body: str
    cta: Cta
    why: str


class Review(BaseModel):
    """The Critic's answer on a draft code found clean."""
    accept: bool
    notes: list[str]  # what to change, if not accepted
