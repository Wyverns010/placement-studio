import pytest
from pydantic import BaseModel

from app import llm
from app.llm import CachedProvider, FakeProvider, LLMError, OpenAIProvider


class Out(BaseModel):
    answer: str


def test_cached_provider_hits_disk_once(tmp_path):
    fake = FakeProvider({"Out": Out(answer="x")})
    cp = CachedProvider(fake, tmp_path)
    a = cp.parse(system="s", user="u", schema=Out, model="m")
    b = cp.parse(system="s", user="u", schema=Out, model="m")
    assert a == b == Out(answer="x")
    assert len(fake.calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_cached_provider_different_input_misses(tmp_path):
    fake = FakeProvider({"Out": Out(answer="x")})
    cp = CachedProvider(fake, tmp_path)
    cp.parse(system="s", user="u1", schema=Out, model="m")
    cp.parse(system="s", user="u2", schema=Out, model="m")
    assert len(fake.calls) == 2


def test_fake_callable_and_records_calls():
    fake = FakeProvider({"Out": lambda s, u: Out(answer=f"{s}|{u}")})
    r = fake.parse(system="S", user="U", schema=Out, model="m")
    assert r.answer == "S|U"
    assert fake.calls == [{"system": "S", "user": "U", "schema": "Out", "model": "m"}]


def test_fake_exception_raised():
    fake = FakeProvider({"Out": LLMError("boom")})
    with pytest.raises(LLMError):
        fake.parse(system="s", user="u", schema=Out, model="m")


def test_fake_unregistered_schema_clear_error():
    with pytest.raises(LookupError, match="Out"):
        FakeProvider({}).parse(system="s", user="u", schema=Out, model="m")


class _Resp:
    def __init__(self, parsed):
        self.output_parsed = parsed


class _Client:
    def __init__(self, parsed=None, exc=None):
        self.kw = None
        self._p, self._e = parsed, exc
        self.responses = self

    def parse(self, **kw):
        self.kw = kw
        if self._e:
            raise self._e
        return _Resp(self._p)


def test_openai_provider_calls_responses_parse():
    c = _Client(Out(answer="y"))
    r = OpenAIProvider(client=c).parse(system="s", user="u", schema=Out, model="m")
    assert r == Out(answer="y")
    assert c.kw["model"] == "m" and c.kw["text_format"] is Out
    assert c.kw["input"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


def test_openai_provider_wraps_errors():
    import openai

    with pytest.raises(LLMError):
        OpenAIProvider(client=_Client(exc=openai.OpenAIError("x"))).parse(
            system="s", user="u", schema=Out, model="m"
        )
    with pytest.raises(LLMError):
        OpenAIProvider(client=_Client(parsed=None)).parse(
            system="s", user="u", schema=Out, model="m"
        )


def test_get_provider_cache_toggle(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
    assert isinstance(llm.get_provider(), OpenAIProvider)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    assert isinstance(llm.get_provider(), CachedProvider)
    monkeypatch.setenv("LLM_CACHE_DIR", "")
    assert isinstance(llm.get_provider(), OpenAIProvider)


def test_model_defaults():
    assert llm.MODEL_FAST and llm.MODEL_CREATIVE
