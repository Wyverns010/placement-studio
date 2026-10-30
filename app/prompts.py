"""Prompt loader.

Prompt files live in the repo-level ``prompts/`` directory as ``{name}.md`` and
are rendered with ``str.format_map``: ``{slot}`` is substituted, a missing slot
raises ``KeyError``. Literal braces in prompt text (e.g. JSON examples) must be
doubled: ``{{`` and ``}}``.
"""
from pathlib import Path


def render(name: str, /, *, prompts_dir: Path = Path("prompts"), **slots) -> str:
    text = (Path(prompts_dir) / f"{name}.md").read_text(encoding="utf-8")
    return text.format_map(slots)
