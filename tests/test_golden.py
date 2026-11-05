from pathlib import Path

import pytest

from scripts import golden

needs_cache = pytest.mark.skipif(not golden.CACHE.is_dir(), reason="no .cache/llm")


@needs_cache
def test_matches_golden():
    assert golden.main(["--check"]) == 0


@needs_cache
def test_check_fails_when_a_number_changes(tmp_path: Path, monkeypatch):
    lines = golden.GOLDEN.read_text().splitlines()
    first = lines[0].replace('"fit": 0.', '"fit": 9.', 1)
    assert first != lines[0]
    changed = tmp_path / "golden.jsonl"
    changed.write_text("\n".join([first, *lines[1:]]) + "\n")
    monkeypatch.setattr(golden, "GOLDEN", changed)
    assert golden.main(["--check"]) == 1
