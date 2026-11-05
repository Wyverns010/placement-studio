from __future__ import annotations

from pydantic import BaseModel


class Factor(BaseModel):
    name: str
    score: float
    note: str


class PublisherScore(BaseModel):
    publisher_id: str
    name: str
    fit: float
    factors: list[Factor]
    recommended: bool
    stretch: bool
    reason: str  # about 8 words max


class PersonaScore(BaseModel):
    persona_id: str
    name: str
    fit: float
    factors: list[Factor]
    stretch: bool
