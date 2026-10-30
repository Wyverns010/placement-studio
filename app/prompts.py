"""Prompt loader.

Prompt files live in the repo-level ``prompts/`` directory as ``{name}.md`` and
are rendered with ``str.format_map``: ``{slot}`` is substituted, a missing slot
raises ``KeyError``. Literal braces in prompt text (e.g. JSON examples) must be
doubled: ``{{`` and ``}}``.
"""
import re
from pathlib import Path

import yaml


_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def render(name: str, /, *, prompts_dir: Path = _DEFAULT_DIR, **slots) -> str:
    text = (Path(prompts_dir) / f"{name}.md").read_text(encoding="utf-8")
    return text.format_map(slots)


_TAG = re.compile(r"<(/?)advertiser_text", re.IGNORECASE)


def wrap_advertiser_text(text: str) -> str:
    """Wrap untrusted text in <advertiser_text> tags, neutralising any tag breakout inside it."""
    return "<advertiser_text>" + _TAG.sub(lambda m: "\u2039" + m.group(1) + "advertiser_text", text) + "</advertiser_text>"


def feedback(key: str, /, *, prompts_dir: Path = _DEFAULT_DIR, **slots) -> str:
    """A feedback template from prompts/creative_feedback.yaml, with {slots} filled."""
    data = yaml.safe_load((Path(prompts_dir) / "creative_feedback.yaml").read_text(encoding="utf-8"))
    return data[key].format_map(slots)
