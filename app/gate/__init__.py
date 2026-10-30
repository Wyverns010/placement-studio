"""Confidence gate: decides whether an input is clear enough to build a campaign."""
from __future__ import annotations

import os
from typing import Protocol

from app.models import Brief, GateResult
from app.tuning import GateTuning, Tuning, load_tuning


class ConfidenceGate(Protocol):
    def assess(self, text: str, brief: Brief) -> GateResult: ...


def decide_outcome(
    *,
    has_content: float,
    business_prob: float,
    clarity: float,
    t: GateTuning,
    impl: str,
    signals: dict,
) -> GateResult:
    """Shared decision rules for every gate implementation."""
    clarity = min(1.0, max(0.0, clarity))
    if has_content < t.no_signal_threshold:
        outcome = "no_signal"
    elif business_prob >= t.business_threshold:
        outcome = "out_of_scope"
    elif clarity < t.proceed_threshold:
        outcome = "clarify"
    else:
        outcome = "proceed"
    return GateResult(
        outcome=outcome,
        confidence=clarity,
        threshold=t.proceed_threshold,
        impl=impl,
        signals={
            **signals,
            "has_content": has_content,
            "business_prob": business_prob,
            "clarity": clarity,
        },
    )


def get_gate(impl: str | None = None, *, tuning: Tuning | None = None) -> ConfidenceGate:
    impl = impl or os.environ.get("GATE_IMPL", "llm")
    if impl == "llm":
        from app.gate.llm_gate import LLMSelfReportGate

        return LLMSelfReportGate(tuning or load_tuning())
    if impl == "laya":
        from app.gate.laya_gate import LayaGate

        return LayaGate(tuning or load_tuning())
    raise ValueError(f"Unknown gate impl: {impl!r}")
