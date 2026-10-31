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
from app.pipeline import run_full
from tests.test_pipeline import CLARIFY, _creatives, brief_obj


@pytest.fixture
def llm():
    return FakeProvider({"BriefSchema": brief_obj(), "CreativeBatch": _creatives,
                         "ClarifyBatch": CLARIFY})


@pytest.fixture
def client(llm, tmp_path, monkeypatch):
    monkeypatch.setattr(samples_mod, "CACHE", tmp_path / "none.json")
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
    assert r.json()["budget_usd"] is None
    assert r.json()["creatives"] == [] and r.json()["config"] is None
    assert "CreativeBatch" not in [c["schema"] for c in llm.calls]


def test_post_campaign_echoes_budget(client):
    assert client.post("/api/campaign", json={"text": "dog food", "budget_usd": 3000}).json()["budget_usd"] == 3000


STAGE1_EVENTS = ["understood", "gate", "publishers", "personas", "done"]


def test_stream_events(client):
    r = client.get("/api/campaign/stream", params={"text": "dog food", "answers": '{"Q": "A"}'})
    ev = sse(r)
    assert [e for e, _ in ev] == STAGE1_EVENTS
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


def _cache_sample(llm, tmp_path, monkeypatch, text="We sell dog food"):
    """Write a format-2 cache holding `text`'s three stages and point the app at it."""
    full = run_full(text, None, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T)
    path = tmp_path / "samples.json"
    samples_mod.write_cache([samples_mod.SampleEntry(
        stage1=full.model_copy(update={"creatives": [], "config": None}),
        creatives=full.creatives, config=full.config)], path)
    monkeypatch.setattr(samples_mod, "CACHE", path)
    monkeypatch.setattr(api, "REPLAY_DELAY_S", 0)
    return full


def test_cached_sample_skips_pipeline_and_limit(client, llm, tmp_path, monkeypatch):
    text = "We sell dog food"
    _cache_sample(llm, tmp_path, monkeypatch, text)
    calls = len(llm.calls)
    for _ in range(15):
        r = client.post("/api/campaign", json={"text": "We  sell\ndog food"})
        assert r.status_code == 200 and r.json()["creatives"] == []
    assert client.post("/api/campaign", json={"text": text, "budget_usd": 1000}).json()["budget_usd"] == 1000
    assert len(llm.calls) == calls
    ev = sse(client.get("/api/campaign/stream", params={"text": text}))
    assert [e for e, _ in ev] == STAGE1_EVENTS
    # answers bypass the cache
    client.post("/api/campaign", json={"text": text, "answers": {"Q": "A"}})
    assert len(llm.calls) > calls


def test_cached_creatives_skip_llm_and_limit_and_config_matches_cache(client, llm, tmp_path, monkeypatch):
    full = _cache_sample(llm, tmp_path, monkeypatch)
    s1 = client.post("/api/campaign", json={"text": "We sell dog food"}).json()
    calls = len(llm.calls)
    for _ in range(15):
        r = client.post("/api/creatives", json=_stage2(s1))
        assert r.status_code == 200
    assert len(llm.calls) == calls
    assert r.json()["creatives"] == [c.model_dump() for c in full.creatives]
    cfg = client.post("/api/config", json=_stage3(s1, r.json()["creatives"])).json()["config"]
    assert cfg == full.config.model_dump()
    # a different persona selection is not the cached one: it runs live
    client.post("/api/creatives", json={**_stage2(s1), "personas": s1["personas"][:1]})
    assert len(llm.calls) > calls


def test_cache_rules(tmp_path):
    res = CampaignResult(input_text="a  b", budget_usd=None, outcome="no_signal", message=None,
                         brief=None, gate=None, publishers=[], personas=[], creatives=[],
                         clarify=[], config=None)
    p = tmp_path / "s.json"
    assert samples_mod.cached_stage1("a b", path=p) is None
    samples_mod.write_cache([samples_mod.SampleEntry(stage1=res)], p)
    assert samples_mod.cached_stage1("a\tb", path=p) is not None
    assert samples_mod.cached_stage1("a b", 1000, path=p).budget_usd == 1000
    assert samples_mod.cached_creatives("a b", [], [], path=p) is None  # nothing built
    assert json.loads(p.read_text())["format"] == 2
    p.write_text(json.dumps({"a b": res.model_dump()}))  # the old format is ignored
    assert samples_mod.cached_stage1("a b", path=p) is None


def test_answers_capped(client):
    ans = {f"q{i}": "x" * 500 for i in range(9)}
    r = client.post("/api/campaign", json={"text": "dog food", "answers": ans}).json()
    lines = r["input_text"].split("Additional details:\n")[1].splitlines()
    assert len(lines) == 5 and all(len(l) <= len("- q0: ") + 200 for l in lines)


@pytest.mark.parametrize("over", [dict(self_confidence=0.3), dict()])
def test_replay_mirrors_live(over):
    from app.pipeline import result_events, run_stage1, collect
    from tests.test_pipeline import fake
    llm = fake(**over)
    live = list(run_stage1("dog food", None, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T))
    replay = result_events(collect(iter(live)))
    assert [(e.stage, e.data) for e in replay] == [(e.stage, e.data) for e in live]


def test_cache_memoised(tmp_path, monkeypatch):
    res = CampaignResult(input_text="a", budget_usd=None, outcome="no_signal", message=None,
                         brief=None, gate=None, publishers=[], personas=[], creatives=[],
                         clarify=[], config=None)
    p = tmp_path / "s.json"
    samples_mod.write_cache([samples_mod.SampleEntry(stage1=res)], p)
    assert samples_mod.cached_stage1("a", path=p)
    calls = []
    orig = samples_mod.SampleEntry.model_validate
    monkeypatch.setattr(samples_mod.SampleEntry, "model_validate",
                        classmethod(lambda c, *a, **k: calls.append(1) or orig(*a, **k)))
    assert samples_mod.cached_stage1("a", path=p)
    assert calls == []


class _Boom:
    calls: list = []

    def parse(self, **kw):
        raise AssertionError("LLM must not be called for a cached sample")


def test_cached_sample_skips_llm(monkeypatch):
    """The committed cache serves sample #1's stage 1 and creatives even when the LLM provider
    always raises; stage 3 is code."""
    monkeypatch.setattr(api, "REPLAY_DELAY_S", 0)
    api.app.dependency_overrides[api.get_llm] = lambda: _Boom()
    try:
        c = TestClient(api.app)
        s1 = samples_mod.load_samples()[0]
        r = c.post("/api/campaign", json={"text": s1["text"]})
        assert r.status_code == 200 and r.json()["outcome"] == "proceed"
        ev = sse(c.get("/api/campaign/stream", params={"text": s1["text"]}))
        assert [e for e, _ in ev] == STAGE1_EVENTS
        cr = c.post("/api/creatives", json=_stage2(r.json()))
        assert cr.status_code == 200 and cr.json()["creatives"]
        cfg = c.post("/api/config", json=_stage3(r.json(), cr.json()["creatives"]))
        assert cfg.status_code == 200
        assert cfg.json()["config"] == samples_mod.cached_entry(s1["text"]).config.model_dump()
    finally:
        api.app.dependency_overrides.clear()


def test_every_sample_is_cached_with_its_stages():
    for s in samples_mod.load_samples():
        e = samples_mod.cached_entry(s["text"])
        assert e is not None, s["id"]
        assert e.stage1.creatives == [] and e.stage1.config is None, s["id"]
        built = e.stage1.outcome in ("proceed", "weak_fit")
        assert bool(e.creatives) == built and (e.config is not None) == built, s["id"]
        if built:
            assert e.config.budget["source"] == "recommended", s["id"]


def test_examples_path_anchored_to_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert samples_mod.EXAMPLES.is_absolute()
    assert len(samples_mod.load_samples()) == 15


# ---- stages 2 and 3 ----

def _stage2(s1: dict) -> dict:
    return {k: s1[k] for k in ("input_text", "brief", "publishers", "personas")}


def _stage3(s1: dict, creatives: list, **extra) -> dict:
    return {**_stage2(s1), "gate": s1["gate"], "creatives": creatives, **extra}


def _regen(s1: dict, creatives: list, **extra) -> dict:
    return {**_stage2(s1), "creatives": creatives, "persona_id": creatives[0]["persona_id"], **extra}


@pytest.fixture
def s1(client):
    return client.post("/api/campaign", json={"text": "We sell dog food"}).json()


def test_staged_flow_end_to_end(client, llm, s1):
    assert s1["outcome"] == "proceed"
    r = client.post("/api/creatives", json=_stage2(s1))
    assert r.status_code == 200
    cr = r.json()["creatives"]
    assert len(cr) == len(s1["personas"])
    rec = {p["publisher_id"] for p in s1["publishers"] if p["recommended"]}
    assert {c["publisher_id"] for c in cr} <= rec
    cfg = client.post("/api/config", json=_stage3(s1, cr)).json()["config"]
    assert cfg["budget"]["source"] == "recommended"
    assert cfg["budget"]["monthly_usd"] == cfg["budget"]["recommended_usd"]
    user = client.post("/api/config", json=_stage3(s1, cr, budget_usd=12000)).json()["config"]
    assert user["budget"]["monthly_usd"] == 12000 and user["budget"]["source"] == "user"
    assert user["budget"]["recommended_usd"] == cfg["budget"]["recommended_usd"]


def test_weak_fit_config_is_a_test(client, llm):
    llm.responses["BriefSchema"] = brief_obj(categories=[], adjacent_categories=[], product="widgets")
    s1 = client.post("/api/campaign", json={"text": "widgets"}).json()
    assert s1["outcome"] == "weak_fit"
    cr = client.post("/api/creatives", json=_stage2(s1)).json()["creatives"]
    cfg = client.post("/api/config", json=_stage3(s1, cr)).json()["config"]
    assert cfg["budget"]["test_budget"] is True and cfg["budget"]["pacing"] == "front_loaded"


def test_regenerate_rewrites_one_ad(client, llm, s1):
    cr = client.post("/api/creatives", json=_stage2(s1)).json()["creatives"]

    def rewrite(system, user):
        out = _creatives(system, user)
        if "Rewrite this persona" in user:
            for it in out.items:
                it.headline = "A brand new angle"
        return out

    llm.responses["CreativeBatch"] = rewrite
    r = client.post("/api/creatives/regenerate", json=_regen(s1, cr, note="  more playful  "))
    assert r.status_code == 200
    c = r.json()["creative"]
    assert c["creative_id"] == cr[0]["creative_id"] and c["publisher_id"] == cr[0]["publisher_id"]
    assert c["headline"] == "A brand new angle" != cr[0]["headline"]
    assert "<user_note>more playful</user_note>" in llm.calls[-1]["user"]


@pytest.mark.parametrize("extra,detail", [
    ({"note": "x" * 201}, "Keep the note to 200 characters."),
    ({"persona_id": "persona_999"}, "persona_id has no creative to regenerate."),
])
def test_regenerate_validation(client, s1, extra, detail):
    cr = client.post("/api/creatives", json=_stage2(s1)).json()["creatives"]
    r = client.post("/api/creatives/regenerate", json={**_regen(s1, cr), **extra})
    assert r.status_code == 422 and r.json()["detail"] == detail


def test_stage2_validation(client, s1):
    no_rec = [{**p, "recommended": False} for p in s1["publishers"]]
    cases = [
        ({"publishers": no_rec}, "No recommended publishers to place ads on."),
        ({"personas": []}, "Send between 1 and 5 personas."),
        ({"personas": [{**s1["personas"][0], "persona_id": "persona_999"}]}, "Unknown persona in the request."),
        ({"publishers": [{**s1["publishers"][0], "publisher_id": "pub_999"}]}, "Unknown publisher in the request."),
        ({"input_text": "  "}, "Please describe your business."),
        ({"input_text": "a" * 10_000}, "input_text is longer than stage 1 produces."),
    ]
    for over, detail in cases:
        r = client.post("/api/creatives", json={**_stage2(s1), **over})
        assert r.status_code == 422 and r.json()["detail"] == detail, over
    assert client.post("/api/creatives", json={"input_text": "x"}).status_code == 422  # pydantic


def test_config_validation(client, s1):
    cr = client.post("/api/creatives", json=_stage2(s1)).json()["creatives"]
    for b in (499, 5_000_001):
        r = client.post("/api/config", json=_stage3(s1, cr, budget_usd=b))
        assert r.status_code == 422 and r.json()["detail"] == "Budget must be between $500 and $5,000,000."
    r = client.post("/api/config", json=_stage3(s1, cr) | {"gate": {**s1["gate"], "outcome": "clarify"}})
    assert r.status_code == 422


def test_stage2_counts_as_a_run_and_stage3_is_free(client, s1):
    # stage 1 used one run; creatives and regenerate each count
    cr = client.post("/api/creatives", json=_stage2(s1)).json()["creatives"]
    for _ in range(10):
        assert client.post("/api/creatives/regenerate", json=_regen(s1, cr)).status_code == 200
    assert client.post("/api/creatives", json=_stage2(s1)).status_code == 429
    assert client.post("/api/creatives/regenerate", json=_regen(s1, cr)).status_code == 429
    for _ in range(20):
        assert client.post("/api/config", json=_stage3(s1, cr)).status_code == 200


def test_stage2_llm_failure_is_502(client, llm, s1):
    llm.responses["CreativeBatch"] = LLMError("sk-secret")
    r = client.post("/api/creatives", json=_stage2(s1))
    assert r.status_code == 502 and "sk-secret" not in r.text
    assert r.json()["detail"] == "The AI service didn't respond — try again or pick a sample."
