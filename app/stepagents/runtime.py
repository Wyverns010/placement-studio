"""Step-agent runtime (OpenAI Agents SDK): which model each agent runs on, the per-step cost
guard, the compact trace returned to the UI, and running an agent with a deadline.

The agent proposes, code disposes: agents only choose tool inputs and write words. Every number
comes from a tool that wraps the existing deterministic code, and each step's result is assembled
by code from what the tools recorded. Any failure (error, timeout, turn limit, cost cap) makes the
caller run the plain code step instead (mode "fallback").
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable

from agents import ModelSettings, RunConfig, RunHooks, Runner, set_tracing_disabled
from agents.models.interface import Model, ModelProvider
from openai.types.shared import Reasoning

from app.llm import model_creative, model_fast, reasoning_effort
from app.models import TraceStep
from app.tuning import Tuning

log = logging.getLogger(__name__)

# agent role -> which of the two configured models it runs on
ROLE_MODEL = {"strategist": "fast", "copywriter": "creative", "critic": "fast",
              "media_planner": "fast"}
STEPS = ("strategist", "creative", "media_planner")  # cost caps and run_without_steer keys


def tracing_enabled() -> bool:
    """SDK tracing (uploads runs to OpenAI) is off unless OPENAI_AGENTS_TRACING=1."""
    return os.getenv("OPENAI_AGENTS_TRACING") == "1"


class AgentStopped(Exception):
    """The agent run was stopped by a guard; `str(e)` is a user-safe reason."""


class CostCapExceeded(AgentStopped):
    pass


class ToolRefused(Exception):
    """A tool input failed validation; the message goes back to the agent, nothing changes."""


class AgentRuntime:
    """Models per agent role. Live: model names from env through the OpenAI provider (made per
    step run, so its async client lives on that run's event loop). Tests: `models` maps a role
    to an SDK Model (e.g. a scripted fake)."""

    def __init__(self, *, models: dict[str, Model] | None = None,
                 provider_factory: Callable[[], ModelProvider] | None = None):
        self._models = models or {}
        self._provider_factory = provider_factory
        set_tracing_disabled(not tracing_enabled())

    def model(self, role: str) -> str | Model:
        if role in self._models:
            return self._models[role]
        if self._provider_factory is None:  # a scripted runtime never falls through to a live model
            raise AgentStopped(f"no model configured for {role}")
        return self.model_name(role)

    @staticmethod
    def model_name(role: str) -> str:
        """The configured model name for a role (also the price key for the cost guard)."""
        return model_fast() if ROLE_MODEL[role] == "fast" else model_creative()

    @staticmethod
    def settings() -> ModelSettings:
        effort = reasoning_effort()
        return ModelSettings() if effort == "default" else ModelSettings(reasoning=Reasoning(effort=effort))

    def run_config(self, workflow: str) -> RunConfig:
        kw: dict[str, Any] = {"tracing_disabled": not tracing_enabled(), "workflow_name": workflow}
        if self._provider_factory:
            kw["model_provider"] = self._provider_factory()
        return RunConfig(**kw)


def openai_runtime(t: Tuning) -> AgentRuntime | None:
    """The live runtime, or None (agents off: plain code) when disabled or there is no key."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not t.agents.enabled or not key:
        return None

    def provider() -> ModelProvider:
        from agents import OpenAIProvider
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key, timeout=t.llm.timeout_s, max_retries=0)
        return OpenAIProvider(openai_client=client, use_responses=True)

    return AgentRuntime(provider_factory=provider)


def wants_agent(step: str, steer: str | None, t: Tuning) -> bool:
    """A steer always runs the agent; without one, tuning decides per step."""
    return bool(steer) or t.agents.run_without_steer.get(step, False)


_SPACE = re.compile(r"\s+")


def _cut(s: str, n: int) -> str:
    s = _SPACE.sub(" ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


class Session:
    """One step run: the cost guard, the trace and the notes. Shared by every agent in the step
    (thread- and task-safe). `on_step` sees each trace step as it happens (SSE `agent` events)."""

    def __init__(self, step: str, runtime: AgentRuntime, t: Tuning,
                 on_step: Callable[[TraceStep], None] | None = None):
        self.step, self.runtime, self.t = step, runtime, t
        self.cap = t.agents.max_cost_usd[step]
        self.cost_usd = 0.0
        self.trace: list[TraceStep] = []
        self._notes: list[str] = []
        self._on_step = on_step
        self._lock = threading.Lock()
        self.hooks = _Guard(self)
        self.run_config = runtime.run_config(f"placement-studio {step}")

    # ---- cost guard ----
    def charge(self, role: str, usage) -> None:
        """Add one model response's tokens at tuning prices; over the step cap -> stop."""
        p = self.t.agents.price(self.runtime.model_name(role))
        details = getattr(usage, "input_tokens_details", None)
        cached = min(getattr(details, "cached_tokens", 0) or 0, usage.input_tokens)
        cost = ((usage.input_tokens - cached) * p.input + cached * p.cached_input
                + usage.output_tokens * p.output) / 1_000_000
        with self._lock:
            self.cost_usd += cost
            over = self.cost_usd > self.cap
        if over:
            raise CostCapExceeded(f"cost cap reached (${self.cap:.2f} for this step)")

    def check(self) -> None:
        if self.cost_usd > self.cap:
            raise CostCapExceeded(f"cost cap reached (${self.cap:.2f} for this step)")

    # ---- trace and notes ----
    def record(self, agent: str, tool: str, args: Any, result: str, ms: int) -> TraceStep:
        a = self.t.agents
        args_s = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False,
                                                              separators=(",", ":"))
        step = TraceStep(agent=agent, tool=tool, args_summary=_cut(args_s, a.trace_args_chars),
                         result_summary=_cut(result, a.trace_result_chars), ms=ms)
        with self._lock:
            self.trace.append(step)
        if self._on_step:
            self._on_step(step)
        return step

    def tool(self, agent: str, tool: str, args: dict, fn: Callable[[], str]) -> str:
        """Run one tool body: a ToolRefused becomes a 'Refused: …' answer to the agent (nothing
        changes); anything else propagates and stops the run (fallback). Always traced."""
        t0 = time.perf_counter()
        try:
            out = fn()
        except ToolRefused as e:
            out = f"Refused: {e}"
        self.record(agent, tool, args, out, int((time.perf_counter() - t0) * 1000))
        return out

    def note(self, text: str) -> None:
        a = self.t.agents
        text = _cut(text, a.note_max_chars)
        with self._lock:
            if text and text not in self._notes and len(self._notes) < a.max_notes:
                self._notes.append(text)

    @property
    def notes(self) -> list[str]:
        return list(self._notes)

    def meta(self, mode: str) -> dict:
        return {"mode": mode, "agent_trace": list(self.trace), "agent_notes": self.notes}

    def fallback_meta(self, error: BaseException) -> dict:
        """Trace the stop and say, in one note, that the plain code result is shown."""
        reason = str(error) if isinstance(error, AgentStopped) else type(error).__name__
        self.record(self.step, "fallback", {}, f"agent stopped ({reason}); code result used", 0)
        self._notes = [f"The agent stopped ({reason}), so this is the standard result."]
        return self.meta("fallback")


class _Guard(RunHooks):
    """Cost guard on every model call: refuse to start one once over the cap, and stop as soon as
    a response takes the step over it."""

    def __init__(self, session: Session):
        self.session = session

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.session.check()

    async def on_llm_end(self, context, agent, response) -> None:
        self.session.charge(agent.name, response.usage)


async def run_agent(session: Session, agent, input: str, context, role: str):
    """One agent run with this step's guard, turn limit and run config."""
    return await Runner.run(agent, input, context=context,
                            max_turns=session.t.agents.max_turns[role],
                            hooks=session.hooks, run_config=session.run_config)


def run_step(coro_fn: Callable[[], Any], t: Tuning):
    """Run a step's agent coroutine to completion on a fresh event loop, within agents.timeout_s.
    Call from a worker thread (FastAPI's threadpool), never from a running loop."""
    async def main():
        return await asyncio.wait_for(coro_fn(), t.agents.timeout_s)
    try:
        return asyncio.run(main())
    except TimeoutError as e:
        raise AgentStopped(f"took longer than {t.agents.timeout_s:g}s") from e
