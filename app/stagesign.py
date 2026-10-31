"""Stage tokens: stage 1 signs what it returned so stages 2 and 3 can trust the echo.

The token is HMAC-SHA256, keyed by STAGE_SECRET, over canonical JSON (sorted keys, compact) of
{input_text, brief, gate, publishers, personas} after Pydantic parsing, so number formatting in
the client (1.0 vs 1) does not matter. Without STAGE_SECRET a random key is made per process:
tokens then stop working after a restart (the user re-runs stage 1). Never stored in the cache.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

from app.models import Brief, CampaignResult, GateResult, PersonaScore, PublisherScore

SECRET: bytes = os.environ.get("STAGE_SECRET", "").encode() or secrets.token_bytes(32)


def _canonical(input_text: str, brief: Brief, gate: GateResult, publishers: list[PublisherScore],
               personas: list[PersonaScore]) -> bytes:
    data = {"input_text": input_text, "brief": brief.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
            "publishers": [p.model_dump(mode="json") for p in publishers],
            "personas": [p.model_dump(mode="json") for p in personas]}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(input_text: str, brief: Brief, gate: GateResult, publishers: list[PublisherScore],
         personas: list[PersonaScore]) -> str:
    return hmac.new(SECRET, _canonical(input_text, brief, gate, publishers, personas),
                    hashlib.sha256).hexdigest()


def verify(token: str, input_text: str, brief: Brief, gate: GateResult,
           publishers: list[PublisherScore], personas: list[PersonaScore]) -> bool:
    """Constant-time comparison against the token stage 1 would have issued."""
    return hmac.compare_digest(sign(input_text, brief, gate, publishers, personas).encode(),
                               (token or "").encode())


def sign_result(r: CampaignResult) -> CampaignResult:
    """The stage-1 result with its stage_token (None when there is no brief or gate)."""
    if r.brief is None or r.gate is None:
        return r.model_copy(update={"stage_token": None})
    return r.model_copy(update={"stage_token": sign(r.input_text, r.brief, r.gate, r.publishers,
                                                    r.personas)})
