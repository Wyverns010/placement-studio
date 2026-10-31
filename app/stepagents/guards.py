"""Steer guards shared by the step agents: a steer is the advertiser's preference, so it may
narrow a plan but never funnel it. Code checks every exclusion the agent proposes:

- it must be named in the steer (the publisher's name or its kind of store), and
- the recommended set may not shrink below `agents.min_recommended_after_steer` (or the original
  count, if that is smaller).

Refusals become a "Refused: …" tool answer (nothing changes) plus one plain note for the user."""
from __future__ import annotations

import re

from app.prompts import category_word

# words too generic to count as naming a kind of store ("skip delivery stores" names delivery)
_GENERIC = {"store", "stores", "shop", "shops", "goods", "services", "products", "product", "kits"}
_NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def _stems(category: str) -> set[str]:
    words = set(re.split(r"[^a-z]+", category.lower()))
    words |= set(re.split(r"[^a-z]+", category_word(category).lower()))
    return {w[:5] if len(w) > 5 else w for w in words if w and w not in _GENERIC}


def named_in_steer(steer: str | None, name: str | None, category: str) -> bool:
    """Does the steer name this publisher, or its kind of store ("pet stores", "grocery")?"""
    text = (steer or "").lower()
    if not text:
        return False
    if name and re.search(rf"\b{re.escape(name.lower())}\b", text):
        return True
    return any(re.search(rf"\b{re.escape(s)}", text) for s in _stems(category))


def floor(min_after_steer: int, original: int) -> int:
    """The fewest recommended publishers a steer may leave."""
    return min(min_after_steer, original)


def num_word(n: int) -> str:
    return _NUM.get(n, str(n))


def names_phrase(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def floor_note(kept: list[str], n: int) -> str:
    return (f"Kept {names_phrase(kept)}: a note can narrow the list but not below "
            f"{num_word(n)} publisher{'s' if n != 1 else ''}.")


def unnamed_note(kept: list[str]) -> str:
    it = "it" if len(kept) == 1 else "them"
    return f"Kept {names_phrase(kept)}: your note doesn't ask to leave {it} out."
