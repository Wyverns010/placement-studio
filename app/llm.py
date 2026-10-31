"""LLM provider abstraction: OpenAI structured outputs, a test fake, a disk cache.

Fake and cache key on ``schema.__name__`` (a str), not the class, because some
schemas are built dynamically per catalog.
"""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

def model_fast() -> str:
    return os.getenv("OPENAI_MODEL_FAST") or "gpt-5.4-mini"


def model_creative() -> str:
    return os.getenv("OPENAI_MODEL_CREATIVE") or "gpt-5.5"


def reasoning_effort() -> str:
    return os.getenv("OPENAI_REASONING_EFFORT") or "low"


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T: ...


class OpenAIProvider:
    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            # strip: a secret pasted with a trailing newline is an illegal Authorization header
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:  # api_key=None would let the SDK re-read the raw (unstripped) env value
                raise LLMError("OPENAI_API_KEY is not set")
            from app.tuning import load_tuning

            self._client = OpenAI(api_key=key, timeout=load_tuning().llm.timeout_s, max_retries=0)
        return self._client

    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T:
        import openai

        extra = {}
        effort = reasoning_effort()
        if effort != "default":
            extra["reasoning"] = {"effort": effort}
        try:
            resp = self._get_client().responses.parse(
                model=model,
                **extra,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text_format=schema,
            )
        except openai.OpenAIError as e:
            raise LLMError(f"OpenAI call failed: {e}") from e
        if resp.output_parsed is None:
            raise LLMError("OpenAI returned no parsed output")
        return resp.output_parsed


class FakeProvider:
    """Test double. responses: schema name -> instance | callable(system, user) | Exception."""

    def __init__(self, responses: dict[str, "BaseModel | Callable[[str, str], BaseModel] | Exception"]):
        self.responses = responses
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T:
        name = schema.__name__
        with self._lock:
            self.calls.append({"system": system, "user": user, "schema": name, "model": model})
        if name not in self.responses:
            raise LookupError(f"FakeProvider: no response registered for schema {name!r}")
        r = self.responses[name]
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(system, user)
        return r


class CachedProvider:
    def __init__(self, inner: LLMProvider, cache_dir: Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir)

    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T:
        schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
        key = hashlib.sha256(json.dumps([model, system, user, schema.__name__, schema_json]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError, ValueError):
            pass  # missing or corrupt entry: fall through to the live call
        result = self.inner.parse(system=system, user=user, schema=schema, model=model)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(result.model_dump_json())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return result


def get_provider() -> LLMProvider:
    provider: LLMProvider = OpenAIProvider()
    cache_dir = os.getenv("LLM_CACHE_DIR", "")
    if cache_dir:
        provider = CachedProvider(provider, Path(cache_dir))
    return provider
