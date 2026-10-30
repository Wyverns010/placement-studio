"""LLM provider abstraction: OpenAI structured outputs, a test fake, a disk cache.

Fake and cache key on ``schema.__name__`` (a str), not the class, because some
schemas are built dynamically per catalog.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", "gpt-5-mini")
MODEL_CREATIVE = os.getenv("OPENAI_MODEL_CREATIVE", "gpt-5")


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

            self._client = OpenAI(timeout=25, max_retries=1)
        return self._client

    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T:
        import openai

        try:
            resp = self._get_client().responses.parse(
                model=model,
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

    def parse(self, *, system: str, user: str, schema: type[T], model: str) -> T:
        name = schema.__name__
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
        key = hashlib.sha256(
            json.dumps([model, system, user, schema.__name__]).encode()
        ).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        result = self.inner.parse(system=system, user=user, schema=schema, model=model)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(), encoding="utf-8")
        return result


def get_provider() -> LLMProvider:
    provider: LLMProvider = OpenAIProvider()
    cache_dir = os.getenv("LLM_CACHE_DIR", "")
    if cache_dir:
        provider = CachedProvider(provider, Path(cache_dir))
    return provider
