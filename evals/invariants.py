"""Structural invariants every CampaignResult must satisfy, whatever the outcome."""
from __future__ import annotations

from app.copycheck import check_facts, headlines_similar
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
        b = cfg.budget
        if b.get("source") not in ("recommended", "user"):
            out.append(f"budget source {b.get('source')!r}, expected recommended|user")
        rec = b.get("recommended_usd")
        if not (isinstance(rec, (int, float)) and t.budget.min_usd <= rec <= t.budget.max_usd):
            out.append(f"budget recommended_usd {rec!r} outside the budget bounds")
        elif b.get("source") == "recommended" and b.get("monthly_usd") != rec:
            out.append("budget source is recommended but monthly_usd != recommended_usd")
        if b.get("pacing") not in ("front_loaded", "even", "accelerated"):
            out.append(f"budget pacing {b.get('pacing')!r} unknown")
        if cfg.frequency_cap.get("impressions", 0) < t.frequency.min_impressions:
            out.append(f"frequency cap {cfg.frequency_cap} below the minimum")

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

    seen: list[str] = []
    for c in result.creatives:
        if any(headlines_similar(h, c.headline, t.creative.headline_similarity) for h in seen):
            out.append(f"creative {c.creative_id}: duplicate headline {c.headline!r}")
        seen.append(c.headline)

    if (o == "weak_fit" and cfg and cfg.budget.get("source") == "recommended"
            and not cfg.budget.get("test_budget")):
        out.append("weak_fit: config.budget.test_budget not set")
    if cfg is not None:
        placed = {c for li in cfg.line_items for c in [li.creative_id, *li.extra_creative_ids]}
        for c in result.creatives:
            if c.creative_id not in placed:
                out.append(f"creative {c.creative_id} is not in any line item")

    for c in result.creatives:
        v = check_facts(c, result.input_text, t)
        if v:
            out.append(f"creative {c.creative_id}: fact violations {v}")
    return out
