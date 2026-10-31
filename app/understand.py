"""Stage 1: advertiser text -> Brief, with category fields constrained to the data pack."""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, create_model

from app.catalog import Catalog
from app.llm import LLMProvider, model_fast
from app.models import Brief
from app.prompts import render, wrap_advertiser_text
from app.tuning import Tuning


@lru_cache(maxsize=None)
def _build_schema(vocab: tuple[str, ...], conflict_vocab: tuple[str, ...]) -> type[BaseModel]:
    cat_t = list[Literal[vocab]]  # type: ignore[valid-type]
    conflict_t = list[Literal[conflict_vocab]]  # type: ignore[valid-type]
    fields: dict = {}
    for name, f in Brief.model_fields.items():
        if name in ("categories", "adjacent_categories"):
            ann = cat_t
        elif name == "conflicts":
            ann = conflict_t
        else:
            ann = f.annotation
        fields[name] = (ann, ...)  # all required: OpenAI strict structured outputs
    return create_model("BriefSchema", **fields)


def brief_schema(catalog: Catalog) -> type[BaseModel]:
    """Strict per-catalog schema: out-of-vocab terms fail validation."""
    return _build_schema(tuple(catalog.vocab), tuple(catalog.conflict_vocab))


def category_vocab_text(catalog: Catalog) -> str:
    """One line per publisher category with its subcategories: '- pet: pet_food, treats, ...'."""
    return "\n".join(f"- {c}: {', '.join(subs)}" for c, subs in catalog.vocab_groups().items())


def understand(text: str, catalog: Catalog, llm: LLMProvider) -> Brief:
    system = render(
        "understand",
        category_vocab=category_vocab_text(catalog),
        interest_vocab=", ".join(catalog.interest_terms()),
        conflict_vocab=", ".join(catalog.conflict_vocab),
    )
    user = wrap_advertiser_text(text)
    out = llm.parse(system=system, user=user, schema=brief_schema(catalog), model=model_fast())
    return Brief.model_validate(out.model_dump())


def clamp_brief(b: Brief, t: Tuning) -> Brief:
    """Hold an LLM brief to the tuning.input caps that stages 2 and 3 enforce on the echo:
    truncated product/facts/unknowns, deduplicated and capped category lists, a finite
    non-negative price (else unknown) and ages within 0..brief_age_max."""
    i = t.input

    def items(xs: list[str]) -> list[str]:
        return [x[: i.brief_item_max_chars] for x in xs[: i.brief_list_max_items]]

    def terms(xs: list[str]) -> list[str]:
        return list(dict.fromkeys(xs))[: i.brief_categories_max]

    def age(a: int | None) -> int | None:
        return None if a is None else min(max(a, 0), i.brief_age_max)

    price = b.price_usd
    if price is not None and not (math.isfinite(price) and price >= 0):
        price = None
    return b.model_copy(update={
        "product": b.product[: i.brief_product_max_chars] if b.product else b.product,
        "facts": items(b.facts), "unknowns": items(b.unknowns),
        "categories": terms(b.categories), "adjacent_categories": terms(b.adjacent_categories),
        "conflicts": terms(b.conflicts), "price_usd": price,
        "age_min": age(b.age_min), "age_max": age(b.age_max),
    })
