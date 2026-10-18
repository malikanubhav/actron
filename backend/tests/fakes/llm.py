"""Fake LLM for the model layer, plus a helper that sets model settings for a test.

Two ways in, both recorded in docs/models-and-jev.md:
- `FakeLLM` is installed with `llm.configure(completion_fn=fake, api_key="test")`. It replaces
  `litellm.acompletion` (same keyword arguments, OpenAI-shaped response). Fast and fully scripted;
  used by most tests.
- `openai_app(fake)` is a small OpenAI-compatible `/v1/chat/completions` ASGI app. The contract test
  runs it with uvicorn and calls the real `litellm.acompletion` with `openai/<model>` and `api_base`,
  which proves the LiteLLM wiring (arguments, JSON mode, tool calls, usage) end to end.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

Reply = str | dict[str, Any] | Exception
ReplyFn = Callable[[dict[str, Any]], Reply]

MODEL_ENV_KEYS = (
    "TYPESAFE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MODEL_DECISION",
    "MODEL_WRITING",
    "MODEL_AGENT",
    "MODEL_CODING",
    "LITELLM_FALLBACKS",
)


def response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 50,
    completion_tokens: int = 20,
    model: str = "fake",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": c.get("id", f"call_{i}"),
                "type": "function",
                "function": {
                    "name": c["name"],
                    "arguments": c["arguments"]
                    if isinstance(c["arguments"], str)
                    else json.dumps(c["arguments"]),
                },
            }
            for i, c in enumerate(tool_calls)
        ]
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class FakeLLM:
    """Scripted replies: a list consumed in order (the last one repeats) or a function of the call."""

    def __init__(self, replies: list[Reply] | ReplyFn | None = None) -> None:
        self.replies = replies if replies is not None else ["{}"]
        self.calls: list[dict[str, Any]] = []

    def _next(self, call: dict[str, Any]) -> Reply:
        if callable(self.replies):
            return self.replies(call)
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]

    def reply_for(self, call: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(call)
        reply = self._next(call)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict):
            if "choices" in reply:
                return reply
            if "tool_calls" in reply:
                return response(
                    reply.get("content"), reply["tool_calls"], model=str(call.get("model"))
                )
            return response(json.dumps(reply), model=str(call.get("model")))
        return response(reply, model=str(call.get("model")))

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        return self.reply_for(kwargs)


def json_reply(**fields: Any) -> str:
    return json.dumps(fields)


def openai_app(fake: FakeLLM) -> Any:
    """An OpenAI-compatible chat completions endpoint backed by `fake`."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def completions(request: Request) -> JSONResponse:
        body = await request.json()
        body["_authorization"] = request.headers.get("authorization")
        try:
            return JSONResponse(fake.reply_for(body))
        except Exception as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "server_error"}}, status_code=500
            )

    return Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"])])


def install_fake_llm(
    replies: list[Reply] | ReplyFn | None = None, *, fallbacks: str = ""
) -> FakeLLM:
    """Point every kind of work at a fake model (call inside `model_env`)."""
    from actron.config import get_settings
    from actron.models import llm

    os.environ["MODEL_DECISION"] = "groq/fake-decision"
    os.environ["MODEL_WRITING"] = "groq/fake-writing"
    os.environ["MODEL_AGENT"] = "groq/fake-agent"
    os.environ["LITELLM_FALLBACKS"] = fallbacks
    get_settings.cache_clear()
    fake = FakeLLM(replies)
    llm.configure(completion_fn=fake, api_key="test-llm-key")
    return fake


# Pytest fixtures shared by the model and linking tests (re-exported by their conftest files).
# Every test starts with no model keys, no cache, a list usage sink and an instant Jev backoff.


@pytest.fixture
def usage_rows() -> Iterator[list[Any]]:
    from actron.models import usage

    rows: list[Any] = []
    usage.set_sink(usage.list_sink(rows))
    try:
        yield rows
    finally:
        usage.set_sink(None)


@pytest.fixture
def jev_sleeps() -> Any:
    from tests.fakes.jev import SleepRecorder

    return SleepRecorder()


@pytest.fixture
def isolated_models(usage_rows: list[Any], jev_sleeps: Any) -> Iterator[None]:
    from actron.models import cache, jev, llm

    jev.set_sleep(jev_sleeps)
    jev.set_transport(None)
    llm.configure()
    cache.set_enabled(False)
    cache.reset()
    with model_env():
        yield
    jev.set_sleep(None)
    jev.set_transport(None)
    llm.configure()
    cache.set_enabled(True)
    cache.reset()


@pytest.fixture
def jev_on(isolated_models: None) -> Callable[..., Any]:
    from actron.config import get_settings
    from actron.models import jev
    from tests.fakes.jev import FakeJev

    def start(**kwargs: Any) -> FakeJev:
        os.environ["TYPESAFE_API_KEY"] = "test-jev-key"
        get_settings.cache_clear()
        fake = FakeJev(**kwargs)
        jev.set_transport(fake.transport())
        return fake

    return start


@pytest.fixture
def llm_on(isolated_models: None) -> Callable[..., FakeLLM]:
    return install_fake_llm


@contextmanager
def model_env(**values: str) -> Iterator[None]:
    """Set model settings for a block (every other model key is cleared), then restore them."""
    from actron.config import get_settings

    saved = {k: os.environ.get(k) for k in MODEL_ENV_KEYS + tuple(values)}
    try:
        for k in MODEL_ENV_KEYS:
            os.environ[k] = ""
        for k, v in values.items():
            os.environ[k] = v
        get_settings.cache_clear()
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
