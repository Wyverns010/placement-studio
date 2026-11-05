from __future__ import annotations

from app.gate import decide_outcome
from app.models.brief import Brief, GateResult
from app.models.tuning import Tuning

# unclear sits below business_threshold so a vague buyer falls through to the clarity check (clarify), not out_of_scope
_BUSINESS_PROB = {"business": 1.0, "not_shoppable": 1.0, "unclear": 0.25, "consumer": 0.0}


class LLMSelfReportGate:
    """Maps the brief's own self-report to gate inputs; no extra LLM call."""

    def __init__(self, tuning: Tuning):
        self.t = tuning.gate

    def assess(self, text: str, brief: Brief) -> GateResult:
        return decide_outcome(
            has_content=1.0 if brief.describes_business else 0.0,
            business_prob=_BUSINESS_PROB[brief.audience_type],
            clarity=brief.self_confidence,
            t=self.t,
            impl="llm",
            signals={},
        )
