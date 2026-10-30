"""Structural invariants every CampaignResult must satisfy, whatever the outcome."""
from __future__ import annotations

from app.create import check_facts, normalise_headline
from app.models import CampaignConfig, CampaignResult
from app.tuning import Tuning

BUILT = ("proceed", "weak_fit")


def check(result: CampaignResult, t: Tuning) -> list[str]:
    out: list[str] = []
    o = result.outcome
    cfg = result.config

    for p in result.publishers:
        if len(p.factors) != 4:
            out.append(f"publisher {p.publisher_id}: {len(p.factors)} factors, expected 4")
        if not p.reason.strip():
            out.append(f"publisher {p.publisher_id}: empty reason")

    if cfg is not None:
        total = sum(i.share for i in cfg.line_items)
        if abs(total - 1.0) > 1e-6:
            out.append(f"line item shares sum to {total:.6f}, expected 1")
        try:
            CampaignConfig.model_validate(cfg.model_dump())
        except Exception as e:  # noqa: BLE001
            out.append(f"config does not validate: {str(e)[:120]}")

    if o in BUILT:
        if not 3 <= len(result.personas) <= 5:
            out.append(f"{o}: {len(result.personas)} personas, expected 3-5")
        if len(result.creatives) != len(result.personas):
            out.append(f"{o}: {len(result.creatives)} creatives for {len(result.personas)} personas")
        if cfg is None:
            out.append(f"{o}: config is None")
    else:
        if cfg is not None:
            out.append(f"{o}: config must be None")
        if result.creatives:
            out.append(f"{o}: must have no creatives")

    seen: set[str] = set()
    for c in result.creatives:
        h = normalise_headline(c.headline)
        if h in seen:
            out.append(f"creative {c.creative_id}: duplicate headline {c.headline!r}")
        seen.add(h)

    if o == "weak_fit" and not (cfg and cfg.budget.get("test_budget")):
        out.append("weak_fit: config.budget.test_budget not set")

    for c in result.creatives:
        v = check_facts(c, result.input_text, t)
        if v:
            out.append(f"creative {c.creative_id}: fact violations {v}")
    return out
