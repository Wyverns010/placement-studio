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


def test_model_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL_FAST", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_CREATIVE", raising=False)
    assert llm.model_fast() == "gpt-5.4-mini"
    assert llm.model_creative() == "gpt-5.5"
    monkeypatch.setenv("OPENAI_MODEL_FAST", "x")
    assert llm.model_fast() == "x"


def test_cached_provider_corrupt_entry_falls_through(tmp_path):
    fake = FakeProvider({"Out": Out(answer="x")})
    cp = CachedProvider(fake, tmp_path)
    cp.parse(system="s", user="u", schema=Out, model="m")
    (f,) = tmp_path.glob("*.json")
    f.write_text("{garbage")
    assert cp.parse(system="s", user="u", schema=Out, model="m") == Out(answer="x")
    assert len(fake.calls) == 2
    assert Out.model_validate_json(f.read_text()) == Out(answer="x")


def test_cache_key_includes_schema_shape(tmp_path):
    from pydantic import create_model

    A = create_model("Same", a=(str, ...))
    B = create_model("Same", b=(int, ...))
    fake = FakeProvider({"Same": lambda s, u: A(a="1")})
    cp = CachedProvider(fake, tmp_path)
    cp.parse(system="s", user="u", schema=A, model="m")
    fake.responses["Same"] = lambda s, u: B(b=2)
    cp.parse(system="s", user="u", schema=B, model="m")
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert len(fake.calls) == 2


def test_client_built_with_no_retries_and_25s_timeout(monkeypatch):
    import openai
    seen = {}

    class Stub:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(openai, "OpenAI", Stub)
    llm.OpenAIProvider()._get_client()
    assert seen["timeout"] == 25 and seen["max_retries"] == 0


def test_reasoning_effort_sent_and_omitted(monkeypatch):
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    c = _Client(Out(answer="y"))
    OpenAIProvider(client=c).parse(system="s", user="u", schema=Out, model="m")
    assert c.kw["reasoning"] == {"effort": "low"}
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")
    OpenAIProvider(client=c).parse(system="s", user="u", schema=Out, model="m")
    assert c.kw["reasoning"] == {"effort": "medium"}
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "default")
    OpenAIProvider(client=c).parse(system="s", user="u", schema=Out, model="m")
    assert "reasoning" not in c.kw


def test_openai_client_gets_stripped_api_key(monkeypatch):
    # an HF Space secret pasted with a trailing newline made every request an illegal header
    import openai

    seen = {}

    class _Spy:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setenv("OPENAI_API_KEY", "  sk-test\n")
    monkeypatch.setattr(openai, "OpenAI", _Spy)
    OpenAIProvider()._get_client()
    assert seen == {"api_key": "sk-test", "timeout": 25, "max_retries": 0}


def test_openai_client_blank_key_falls_back_to_none(monkeypatch):
    import openai

    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", " \n")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: seen.update(kw))
    OpenAIProvider()._get_client()
    assert seen["api_key"] is None
