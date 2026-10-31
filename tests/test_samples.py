"""The precomputed sample cache: its fingerprint, and that it still matches the code (offline)."""
import json
import logging

import pytest

import app.samples as samples_mod
from app.models import CampaignResult
from tests.conftest import CAT, T


def _res(text="a"):
    return CampaignResult(input_text=text, budget_usd=None, outcome="no_signal", message=None,
                          brief=None, gate=None, publishers=[], personas=[], creatives=[],
                          clarify=[], config=None)


def _tree(root):
    (root / "config").mkdir()
    (root / "config/tuning.yaml").write_text("a: 1\n")
    (root / "prompts/sub").mkdir(parents=True)
    (root / "prompts/understand.md").write_text("hi")
    (root / "prompts/sub/x.yaml").write_text("k: v")
    (root / "data").mkdir()
    (root / "data/publishers.json").write_text("[]")
    (root / "data/notes.txt").write_text("not hashed")
    return root


def test_fingerprint_covers_tuning_prompts_and_data_json(tmp_path):
    root = _tree(tmp_path)
    fp = samples_mod.fingerprint(root)
    assert len(fp) == 64 and fp == samples_mod.fingerprint(root)
    for rel in ("config/tuning.yaml", "prompts/understand.md", "prompts/sub/x.yaml",
                "data/publishers.json"):
        before = samples_mod.fingerprint(root)
        (root / rel).write_text((root / rel).read_text() + " ")
        assert samples_mod.fingerprint(root) != before, rel
    before = samples_mod.fingerprint(root)
    (root / "data/notes.txt").write_text("changed")
    (root / "prompts/README.md").write_text("docs only, never sent to a model")
    assert samples_mod.fingerprint(root) == before


def test_write_cache_stores_the_fingerprint(tmp_path):
    p = tmp_path / "s.json"
    samples_mod.write_cache([samples_mod.SampleEntry(stage1=_res())], p)
    assert json.loads(p.read_text())["fingerprint"] == samples_mod.fingerprint()


def test_stale_cache_is_ignored_with_one_log_line(tmp_path, caplog):
    p = tmp_path / "s.json"
    samples_mod.write_cache([samples_mod.SampleEntry(stage1=_res())], p)
    raw = json.loads(p.read_text())
    raw["fingerprint"] = "0" * 64
    p.write_text(json.dumps(raw))
    with caplog.at_level(logging.INFO, logger="app.samples"):
        assert samples_mod.cached_stage1("a", path=p) is None
        assert samples_mod.cached_stage1("a", path=p) is None
    stale = [r for r in caplog.records if "stale" in r.getMessage()]
    assert len(stale) == 1
    del raw["fingerprint"]  # a cache written before fingerprints is stale too
    p.write_text(json.dumps(raw))
    assert samples_mod.cached_stage1("a", path=p) is None


# ---- the committed cache still matches the code (no LLM calls) ----

ENTRIES = sorted(samples_mod.read_entries().items())


def test_committed_cache_is_current_and_complete():
    assert json.loads(samples_mod.CACHE.read_text())["fingerprint"] == samples_mod.fingerprint()
    assert len(ENTRIES) == 15


@pytest.mark.parametrize("text,entry", ENTRIES, ids=[e.stage1.input_text[:30] for _, e in ENTRIES])
def test_cached_stage1_reproduces_from_its_brief(text, entry):
    """Re-scoring the cached brief (gate, match, personas) gives the cached stage-1 result."""
    replay = samples_mod.replay_stage1(entry, catalog=CAT, t=T)
    skip = {"stage_token", "budget_usd"}
    assert replay.model_dump(exclude=skip) == entry.stage1.model_dump(exclude=skip)


@pytest.mark.parametrize("text,entry", ENTRIES, ids=[e.stage1.input_text[:30] for _, e in ENTRIES])
def test_cached_config_matches_current_code(text, entry):
    rebuilt = samples_mod.rebuild_config(entry, catalog=CAT, t=T)
    assert (rebuilt and rebuilt.model_dump()) == (entry.config and entry.config.model_dump())


def test_fingerprint_ignores_step_agent_tunables_and_prompts(tmp_path):
    """Cached samples are no-steer code results: the tuning `agents:` block and prompts/agents/
    never shape them, so editing those keeps the cache current."""
    root = _tree(tmp_path)
    (root / "config/tuning.yaml").write_text("a: 1\nagents:\n  x: 1\n  # note\nb: 2\n")
    (root / "prompts/agents").mkdir()
    (root / "prompts/agents/strategist.md").write_text("v1")
    before = samples_mod.fingerprint(root)
    (root / "config/tuning.yaml").write_text("a: 1\nagents:\n  x: 2\n  y: 3\nb: 2\n")
    (root / "prompts/agents/strategist.md").write_text("v2")
    assert samples_mod.fingerprint(root) == before
    (root / "config/tuning.yaml").write_text("a: 1\nagents:\n  x: 2\nb: 3\n")
    assert samples_mod.fingerprint(root) != before
