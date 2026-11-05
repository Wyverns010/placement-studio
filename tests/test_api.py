from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.constants.paths import EXAMPLES
from app.llm import FakeProvider, LLMError
from app.loaders import load_samples
from app.models.plan import PlanChanges
from app.ratelimit import RateLimiter
from tests.conftest import T, make_deps
from tests.test_note import changes
from tests.test_pipeline import ACCEPT, CLARIFY, _creatives, brief_obj

N = T.ratelimit.per_client_runs
NO_ADS = "The AI service didn't return any ads — try again."


@pytest.fixture
def llm():
    return FakeProvider({"BriefSchema": brief_obj(), "Draft": _creatives, "Review": ACCEPT, "ClarifyBatch": CLARIFY})


def client_for(llm, limiter=None) -> TestClient:
    return TestClient(create_app(make_deps(llm, limiter)), raise_server_exceptions=False)


@pytest.fixture
def client(llm):
    return client_for(llm)


@pytest.fixture
def s1(client):
    return client.post("/api/campaign", json={"text": "We sell dog food"}).json()


def with_ads(client, s1, **extra) -> dict:
    """A /config body: step 1's result and its ads."""
    ads = client.post("/api/creatives", json={"result": s1}).json()
    return {"result": s1, "creatives": ads, **extra}


# ---- step 1 ----

def test_health_and_samples(client):
    assert client.get("/api/health").json() == {"ok": True}
    samples = client.get("/api/samples").json()
    assert len(samples) == 15 and samples[0]["label"] == "Senior dog food"
    assert EXAMPLES.is_absolute() and len(load_samples()) == 15


def test_campaign_appends_answers_and_keeps_long_text_whole(client, llm):
    r = client.post("/api/campaign", json={"text": "  dog food ", "answers": {"Price?": "High"}, "budget_usd": 3000})
    assert r.status_code == 200 and r.json()["outcome"] == "proceed" and r.json()["budget_usd"] == 3000
    assert r.json()["input_text"] == "dog food\n\nAdditional details:\n- Price?: High"
    assert "Draft" not in [call["schema"] for call in llm.calls]
    long = client.post("/api/campaign", json={"text": "a" * 5000})
    assert long.status_code == 200 and len(long.json()["input_text"]) == 5000  # no input length limits


@pytest.mark.parametrize("body,detail", [
    ({"text": "   \n "}, "Please describe your business."),
    ({"text": "dog food", "budget_usd": 499}, "Budget must be between $500 and $5,000,000."),
    ({"text": "dog food", "budget_usd": 5_000_001}, "Budget must be between $500 and $5,000,000."),
])
def test_campaign_rejects_bad_input(client, body, detail):
    r = client.post("/api/campaign", json=body)
    assert r.status_code == 422 and r.json()["detail"] == detail


def test_campaign_note_reuses_the_brief(client, llm, s1):
    llm.responses["BriefChanges"] = changes()
    before = [call["schema"] for call in llm.calls].count("BriefSchema")
    r = client.post("/api/campaign", json={"text": s1["input_text"], "note": "keep it", "brief": s1["brief"]})
    assert r.status_code == 200 and [call["schema"] for call in llm.calls].count("BriefSchema") == before


def test_llm_failure_is_a_safe_502(client, llm, s1):
    llm.responses["Draft"] = LLMError("sk-secret")
    r = client.post("/api/creatives", json={"result": s1})
    assert r.status_code == 502 and r.json()["detail"] == NO_ADS and "sk-secret" not in r.text
    llm.responses["BriefSchema"] = RuntimeError("sk-boom")
    r = client.post("/api/campaign", json={"text": "dog food"})
    assert r.status_code == 502 and "sk-boom" not in r.text


# ---- rate limits ----

def test_rate_limit_per_client_keyed_on_rightmost_hop(client):
    for i in range(N):
        assert client.post("/api/campaign", json={"text": "dog food"},
                           headers={"X-Forwarded-For": f"10.0.0.{i}, 5.5.5.5"}).status_code == 200
    r = client.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": "10.9.9.9, 5.5.5.5"})
    assert r.status_code == 429 and r.json() == {"detail": "Demo limit reached — try a sample or wait a few minutes."}
    other = client.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
    assert other.status_code == 200


def test_global_cap_returns_busy(llm):
    busy = client_for(llm, RateLimiter(N, 600, global_limit=2))
    for ip in ("1.0.0.1", "1.0.0.2"):
        assert busy.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": ip}).status_code == 200
    r = busy.post("/api/campaign", json={"text": "dog food"}, headers={"X-Forwarded-For": "1.0.0.3"})
    assert r.status_code == 429 and r.json() == {"detail": "The demo is busy — try a sample or come back in a bit."}


def test_ads_cost_two_config_is_free_and_errors_cost_nothing(client, s1):
    for _ in range(20):
        client.post("/api/campaign", json={"text": ""})
    body = with_ads(client, s1)  # 1 (step 1) + 2 (ads) used
    used = 3
    while used + T.ratelimit.cost_ads <= N:
        assert client.post("/api/creatives", json={"result": s1}).status_code == 200
        used += T.ratelimit.cost_ads
    assert client.post("/api/creatives", json={"result": s1}).status_code == 429
    for _ in range(20):
        assert client.post("/api/config", json=body).status_code == 200


# ---- steps 3 and 4 ----

def test_steps_end_to_end(client, s1):
    body = with_ads(client, s1)
    assert len(body["creatives"]) == len(s1["personas"])
    assert {ad["publisher_id"] for ad in body["creatives"]} <= {p["publisher_id"] for p in s1["publishers"] if p["recommended"]}
    config = client.post("/api/config", json=body).json()["config"]
    assert config["budget"]["source"] == "recommended" and config["budget"]["monthly_usd"] == config["budget"]["recommended_usd"]
    user = client.post("/api/config", json={**body, "budget_usd": 12000}).json()["config"]
    assert user["budget"]["monthly_usd"] == 12000 and user["budget"]["source"] == "user"
    for budget in (499, 5_000_001):
        assert client.post("/api/config", json={**body, "budget_usd": budget}).status_code == 422


def test_weak_fit_config_is_a_test(client, llm):
    llm.responses["BriefSchema"] = brief_obj(categories=[], adjacent_categories=["subscription"], product="widgets")
    s1 = client.post("/api/campaign", json={"text": "widgets"}).json()
    assert s1["outcome"] == "weak_fit"
    config = client.post("/api/config", json=with_ads(client, s1)).json()["config"]
    assert config["budget"]["test_budget"] is True and config["budget"]["pacing"] == "front_loaded"


def test_config_note_is_read_and_its_notes_returned(client, llm, s1):
    llm.responses["PlanChanges"] = PlanChanges(budget_usd=5000, drop_publishers=[], pacing="even", not_applied=[])
    r = client.post("/api/config", json=with_ads(client, s1, note="under $5k please"))
    assert r.status_code == 200 and r.json()["config"]["budget"]["monthly_usd"] == 5000
    assert any("5,000" in note for note in r.json()["notes"])
