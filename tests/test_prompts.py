import pytest

from app import prompts


def test_render_substitutes_slots(tmp_path):
    (tmp_path / "hello.md").write_text("Hi {name}")
    assert prompts.render("hello", name="Ada", prompts_dir=tmp_path) == "Hi Ada"


def test_render_missing_slot_raises(tmp_path):
    (tmp_path / "hello.md").write_text("Hi {name}")
    with pytest.raises(KeyError):
        prompts.render("hello", prompts_dir=tmp_path)


def test_render_literal_braces_doubled(tmp_path):
    (tmp_path / "j.md").write_text('{{"a": {x}}}')
    assert prompts.render("j", x=1, prompts_dir=tmp_path) == '{"a": 1}'


def test_understand_examples_appear_in_no_eval_case():
    """Prompt examples must not copy eval wording (it contaminates held-out results)."""
    import json
    import re
    from pathlib import Path
    prompt = Path("prompts/understand.md").read_text(encoding="utf-8")
    texts = [json.loads(line)["text"].lower()
             for line in Path("evals/cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    quoted = [q for q in re.findall(r'"([^"{}]+)"', prompt) if len(q.split()) >= 2]
    for phrase in quoted + ["jerky", "trail mix", "doormat", "bath rug"]:
        assert phrase.lower() in prompt.lower()
        assert not any(phrase.lower() in t for t in texts), phrase
    for given in ("protein bar", "candles"):
        assert given not in prompt.lower()


def test_feedback_yaml_parsed_once(tmp_path):
    (tmp_path / "creative_feedback.yaml").write_text("hi: 'Hi {name}'\n")
    assert prompts.feedback("hi", name="Ada", prompts_dir=tmp_path) == "Hi Ada"
    (tmp_path / "creative_feedback.yaml").write_text("hi: 'Changed {name}'\n")
    assert prompts.feedback("hi", name="Bo", prompts_dir=tmp_path) == "Hi Bo"  # cached parse
