"""Prompt files from prompts/: `{slot}` is filled, a missing slot raises KeyError, and literal
braces in a prompt are doubled (`{{`, `}}`)."""
import re
from pathlib import Path

import yaml

from app.constants.paths import PROMPTS_DIR

FEEDBACK: dict[str, str] = yaml.safe_load((PROMPTS_DIR / "creative_feedback.yaml").read_text(encoding="utf-8"))
CATEGORY_WORDS: dict[str, str] = yaml.safe_load((PROMPTS_DIR / "category_words.yaml").read_text(encoding="utf-8")) or {}


def render(name: str, /, *, prompts_dir: Path = PROMPTS_DIR, **slots) -> str:
    text = (prompts_dir / f"{name}.md").read_text(encoding="utf-8")
    return text.format_map(slots)


def wrap(tag: str, text: str) -> str:
    """Untrusted text inside <tag> tags, with any opening or closing tag inside it neutralised.
    Pattern: data/instruction separation (prompt-injection defence)."""
    inner = re.sub(r"<(/?)" + tag, lambda m: "‹" + m.group(1) + tag, text, flags=re.IGNORECASE)
    return f"<{tag}>{inner}</{tag}>"
