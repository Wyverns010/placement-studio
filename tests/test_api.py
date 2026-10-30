from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.samples as samples_mod
from app import api
from app.gate import get_gate
from app.llm import FakeProvider, LLMError
from app.models import CampaignResult
from app.ratelimit import RateLimiter
from app.understand import brief_schema
from tests.conftest import CAT, T
from tests.test_pipeline import CLARIFY, _creatives, brief_obj


@pytest.fixture
def llm():
    return FakeProvider({"BriefSchema": brief_obj(), "CreativeBatch": _creatives,
                         "ClarifyBatch": CLARIFY})


@pytest.fixture
def client(llm, tmp_path, monkeypatch):
    monkeypatch.setattr(samples_mod, "CACHE", tmp_path / "none.json")
    monkeypatch.setattr(samples_mod.cached_result, "__kwdefaults__",
                        {**samples_mod.cached_result.__kwdefaults__, "path": tmp_path / "none.json"})
    limiter = RateLimiter(limit=12, window_s=600)
    api.app.dependency_overrides[api.get_llm] = lambda: llm
    api.app.dependency_overrides[api.get_gate_dep] = lambda: get_gate("llm", tuning=T)
    api.app.dependency_overrides[api.get_catalog] = lambda: CAT
    api.app.dependency_overrides[api.get_tuning] = lambda: T
    api.app.dependency_overrides[api.get_limiter] = lambda: limiter
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def sse(resp) -> list[tuple[str, dict]]:
    out, ev = [], None
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and ev:
            out.append((ev, json.loads(line.split(":", 1)[1].strip())))
            ev = None
    return out


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_samples_endpoint_returns_15(client):
    r = client.get("/api/samples").json()
    assert len(r) == 15 and [s["id"] for s in r] == list(range(1, 16))
    assert r[0]["label"] == "Senior dog food" and r[0]["text"].startswith("We sell premium dog food")


def test_post_campaign_and_answers_appended(client, llm):
    r = client.post("/api/campaign", json={"text": "  dog food ", "answers": {"Price?": "High"}})
    assert r.status_code == 200 and r.json()["outcome"] == "proceed"
    assert r.json()["input_text"] == "dog food\n\nAdditional details:\n- Price?: High"
    assert r.json()["budget_usd"] == 25000


def test_stream_events(client):
    r = client.get("/api/campaign/stream", params={"text": "dog food", "answers": '{"Q": "A"}'})
    ev = sse(r)
    assert [e for e, _ in ev] == ["understood", "gate", "publishers", "personas", "creatives",
                                  "config", "done"]
    assert "- Q: A" in ev[-1][1]["input_text"]


def test_stream_llm_failure_last_event_error(client, llm):
    llm.responses["BriefSchema"] = LLMError("x")
    ev = sse(client.get("/api/campaign/stream", params={"text": "dog food"}))
    assert ev[-1][0] == "error" and "message" in ev[-1][1]


def test_stream_bad_answers(client):
    assert client.get("/api/campaign/stream", params={"text": "x", "answers": "nope"}).status_code == 422


@pytest.mark.parametrize("text", ["", "   \n "])
def test_rejects_empty_text(client, text):
    r = client.post("/api/campaign", json={"text": text})
    assert r.status_code == 422 and r.json()["detail"] == "Please describe your business."
    assert client.get("/api/campaign/stream", params={"text": text}).status_code == 422


def test_truncates_long_text(client):
    r = client.post("/api/campaign", json={"text": "a" * 5000})
    assert r.status_code == 200
    assert len(r.json()["input_text"]) == T.input.max_chars


@pytest.mark.parametrize("budget", [499, 5_000_001])
def test_budget_bounds(client, budget):
    r = client.post("/api/campaign", json={"text": "dog food", "budget_usd": budget})
    assert r.status_code == 422
    assert r.json()["detail"] == "Budget must be between $500 and $5,000,000."
    assert client.get("/api/campaign/stream",
                      params={"text": "x", "budget_usd": budget}).status_code == 422


def test_budget_edges_ok(client):
    for b in (500, 5_000_000):
        assert client.post("/api/campaign", json={"text": "dog food", "budget_usd": b}).status_code == 200


def test_rate_limit_429_after_12(client):
    for _ in range(12):
        assert client.post("/api/campaign", json={"text": "dog food"}).status_code == 200
    r = client.post("/api/campaign", json={"text": "dog food"})
    assert r.status_code == 429
    assert r.json() == {"detail": "Demo limit reached — try a sample or wait a few minutes."}
    # a different client IP is unaffected
    ok = client.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
    assert ok.status_code == 200


def test_rate_limit_keys_on_rightmost_forwarded_hop(client):
    # the proxy appends the real client IP; a client-chosen leading value must not open a new bucket
    for i in range(12):
        r = client.post("/api/campaign", json={"text": "dog food"},
                        headers={"X-Forwarded-For": f"10.0.0.{i}, 5.5.5.5"})
        assert r.status_code == 200
    r = client.post("/api/campaign", json={"text": "dog food"},
                    headers={"X-Forwarded-For": "10.9.9.9, 5.5.5.5"})
    assert r.status_code == 429


def test_global_cap_returns_busy(client):
    busy = RateLimiter(limit=12, window_s=600, global_limit=2)
    api.app.dependency_overrides[api.get_limiter] = lambda: busy
    for ip in ("1.0.0.1", "1.0.0.2"):
        assert client.post("/api/campaign", json={"text": "dog food"},
                           headers={"X-Forwarded-For": ip}).status_code == 200
    r = client.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": "1.0.0.3"})
    assert r.status_code == 429
    assert r.json() == {"detail": "The demo is busy — try a sample or come back in a bit."}


def test_validation_errors_do_not_consume_limit(client):
    for _ in range(20):
        client.post("/api/campaign", json={"text": ""})
    assert client.post("/api/campaign", json={"text": "dog food"}).status_code == 200


def test_cached_sample_skips_pipeline_and_limit(client, llm, tmp_path, monkeypatch):
    from app.pipeline import collect, run_pipeline
    text = "We sell dog food"
    res = collect(run_pipeline(text, 25000, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T))
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"k": res.model_dump()}))
    monkeypatch.setattr(samples_mod.cached_result, "__kwdefaults__",
                        {**samples_mod.cached_result.__kwdefaults__, "path": path})
    monkeypatch.setattr(api, "REPLAY_DELAY_S", 0)
    calls = len(llm.calls)
    for _ in range(15):
        r = client.post("/api/campaign", json={"text": "We  sell\ndog food"})
        assert r.status_code == 200
    assert len(llm.calls) == calls
    ev = sse(client.get("/api/campaign/stream", params={"text": text}))
    assert [e for e, _ in ev][-1] == "done" and len(ev) == 7
    # a non-default budget or answers bypass the cache
    client.post("/api/campaign", json={"text": text, "budget_usd": 1000})
    assert len(llm.calls) > calls


def test_cached_result_rules(tmp_path):
    res = CampaignResult(input_text="a  b", budget_usd=25000, outcome="no_signal", message=None,
                         brief=None, gate=None, publishers=[], personas=[], creatives=[],
                         clarify=[], config=None)
    p = tmp_path / "s.json"
    assert samples_mod.cached_result("a b", 25000, path=p) is None
    p.write_text(json.dumps([res.model_dump()]))
    assert samples_mod.cached_result("a\tb", 25000, path=p) is not None
    assert samples_mod.cached_result("a b", 1000, path=p) is None


def test_answers_capped(client):
    ans = {f"q{i}": "x" * 500 for i in range(9)}
    r = client.post("/api/campaign", json={"text": "dog food", "answers": ans}).json()
    lines = r["input_text"].split("Additional details:\n")[1].splitlines()
    assert len(lines) == 5 and all(len(l) <= len("- q0: ") + 200 for l in lines)


def test_clarify_replay_mirrors_live():
    from app.pipeline import result_events, run_pipeline, collect
    from tests.test_pipeline import fake
    llm = fake(self_confidence=0.3)
    live = list(run_pipeline("dog food", 25000, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T))
    replay = result_events(collect(iter(live)))
    assert [(e.stage, e.data) for e in replay[:4]] == [(e.stage, e.data) for e in live[:4]]


def test_cache_memoised(tmp_path, monkeypatch):
    res = CampaignResult(input_text="a", budget_usd=25000, outcome="no_signal", message=None,
                         brief=None, gate=None, publishers=[], personas=[], creatives=[],
                         clarify=[], config=None)
    p = tmp_path / "s.json"
    p.write_text(json.dumps([res.model_dump()]))
    assert samples_mod.cached_result("a", 25000, path=p)
    calls = []
    orig = CampaignResult.model_validate
    monkeypatch.setattr(CampaignResult, "model_validate", classmethod(lambda c, *a, **k: calls.append(1) or orig(*a, **k)))
    assert samples_mod.cached_result("a", 25000, path=p)
    assert calls == []


class _Boom:
    calls: list = []

    def parse(self, **kw):
        raise AssertionError("LLM must not be called for a cached sample")


def test_cached_sample_skips_llm(monkeypatch):
    """The committed cache serves sample #1 even when the LLM provider always raises."""
    monkeypatch.setattr(api, "REPLAY_DELAY_S", 0)
    api.app.dependency_overrides[api.get_llm] = lambda: _Boom()
    try:
        c = TestClient(api.app)
        s1 = samples_mod.load_samples()[0]
        r = c.post("/api/campaign", json={"text": s1["text"]})
        assert r.status_code == 200 and r.json()["outcome"] == "proceed"
        ev = sse(c.get("/api/campaign/stream", params={"text": s1["text"]}))
        assert [e for e, _ in ev][-1] == "done"
    finally:
        api.app.dependency_overrides.clear()


def test_every_sample_is_cached():
    for s in samples_mod.load_samples():
        assert samples_mod.cached_result(s["text"], 25000) is not None, s["id"]


def test_examples_path_anchored_to_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert samples_mod.EXAMPLES.is_absolute()
    assert len(samples_mod.load_samples()) == 15
