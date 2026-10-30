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
