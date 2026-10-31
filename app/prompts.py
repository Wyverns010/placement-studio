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


def _wrap(tag: str, text: str) -> str:
    """Wrap untrusted text in <tag> tags, neutralising any opening or closing tag inside it."""
    inner = re.sub(r"<(/?)" + tag, lambda m: "\u2039" + m.group(1) + tag, text, flags=re.IGNORECASE)
    return f"<{tag}>{inner}</{tag}>"


def wrap_advertiser_text(text: str) -> str:
    """Wrap the advertiser's untrusted text in <advertiser_text> tags."""
    return _wrap("advertiser_text", text)


def wrap_current_ad(text: str) -> str:
    """Wrap the client-echoed current ad (regenerate) in <current_ad> tags."""
    return _wrap("current_ad", text)


def wrap_user_note(text: str) -> str:
    """Wrap a regenerate note (untrusted, treated as data) in <user_note> tags."""
    return _wrap("user_note", text)


def feedback(key: str, /, *, prompts_dir: Path = _DEFAULT_DIR, **slots) -> str:
    """A feedback template from prompts/creative_feedback.yaml, with {slots} filled."""
    data = yaml.safe_load((Path(prompts_dir) / "creative_feedback.yaml").read_text(encoding="utf-8"))
    return data[key].format_map(slots)
