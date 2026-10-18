"""The real `litellm.acompletion` against a local OpenAI-compatible fake server (A-AC-81).

This proves the wiring the scripted fakes skip: model name, api_base, api key, JSON mode, tool calls
and usage parsing through LiteLLM itself.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from actron import models
from actron.config import get_settings
from actron.models import llm
from tests.fakes.llm import FakeLLM, openai_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def server() -> Iterator[tuple[str, FakeLLM]]:
    import uvicorn

    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    fake = FakeLLM()
    port = _free_port()
    config = uvicorn.Config(openai_app(fake), host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/v1", fake
    finally:
        srv.should_exit = True
        thread.join(timeout=5)


async def test_judgment_through_real_litellm(server: tuple[str, FakeLLM], monkeypatch: Any) -> None:
    """A-AC-81: Jev missing -> real LiteLLM -> JSON answer validated."""
    base, fake = server
    monkeypatch.setenv("MODEL_DECISION", "openai/fake-decision")
    get_settings.cache_clear()
    llm.configure(api_base=base, api_key="sk-local-test")
    fake.replies = [json.dumps({"answers": {"supported": {"type": "noul", "noul": 0.72}}})]
    j = await models.check_link("quote", "claim")
    assert j.provider == "llm" and j.probability == pytest.approx(0.72)
    call = fake.calls[0]
    assert call["model"] == "fake-decision"
    assert call["_authorization"] == "Bearer sk-local-test"
    assert call["response_format"] == {"type": "json_object"}


async def test_tool_turn_through_real_litellm(
    server: tuple[str, FakeLLM], monkeypatch: Any
) -> None:
    """B5 interface: tool calls and token usage come back through LiteLLM's response objects."""
    base, fake = server
    monkeypatch.setenv("MODEL_AGENT", "openai/fake-agent")
    get_settings.cache_clear()
    llm.configure(api_base=base, api_key="sk-local-test")
    fake.replies = [
        {"tool_calls": [{"id": "c1", "name": "search", "arguments": {"query": "jack-in"}}]}
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the graph",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]
    turn = await models.agent_completion([{"role": "user", "content": "find jack-in"}], tools)
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("c1", "search", {"query": "jack-in"})
    ]
    assert turn.tokens == {"input": 50, "output": 20}
    assert fake.calls[0]["tools"][0]["function"]["name"] == "search"
