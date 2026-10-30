"""Stage 1: advertiser text -> Brief, with category fields constrained to the data pack."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, create_model

from app.catalog import Catalog
from app.llm import LLMProvider, model_fast
from app.models import Brief
from app.prompts import render


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


def understand(text: str, catalog: Catalog, llm: LLMProvider) -> Brief:
    system = render(
        "understand",
        vocab=", ".join(catalog.vocab),
        conflict_vocab=", ".join(catalog.conflict_vocab),
    )
    user = f"<advertiser_text>{text}</advertiser_text>"
    out = llm.parse(system=system, user=user, schema=brief_schema(catalog), model=model_fast())
    return Brief.model_validate(out.model_dump())
