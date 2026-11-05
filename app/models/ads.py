from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.constants.ads import CTA_OPTIONS

Cta = Literal[CTA_OPTIONS]  # type: ignore[valid-type]


class Creative(BaseModel):
    creative_id: str
    persona_id: str
    publisher_id: str
    headline: str
    body: str
    cta: str
    why: str
    fact_violations: list[str] = []
