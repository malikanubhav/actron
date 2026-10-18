"""Live check of every configured LLM through LiteLLM (opt-in): JSON mode, plain text and a tool call.

Run: `./scripts/live_smoke.sh models` (or `uv run pytest tests/live/test_models_live.py -m live -s`) with the
provider keys and MODEL_* names in .env. Prints latency, tokens and estimated cost per model; never prints keys.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from actron.config import get_settings
from actron.models import llm, usage

pytestmark = [pytest.mark.live, pytest.mark.timeout(300)]

TOOL = {
    "type": "function",
    "function": {
        "name": "find_function",
        "description": "Look up a function in the code graph by name.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}


def _models() -> list[str]:
    get_settings.cache_clear()
    s = get_settings()
    names = [s.MODEL_DECISION, s.MODEL_WRITING, s.MODEL_AGENT, *s.litellm_fallbacks]
    out: list[str] = []
    for n in names:
        if n and n not in out and llm._key_for(n):
            out.append(n)
    return out


def _report(label: str, model: str, started: float, resp: Any) -> None:
    tin, tout = llm.tokens_of(resp)
    cost = usage.cost_for(model, tin, tout)
    print(f"[live] {label:5} {model}: {time.monotonic() - started:5.1f}s in={tin} out={tout} cost=${cost:.5f}")


def _limit_of(exc: Exception) -> str:
    """The quota id and value from a provider 429 body (no keys appear in it)."""
    text = str(exc)
    found = [part for part in ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "PerMinute", "PerDay") if part in text]
    value = text.split('"quotaValue": "', 1)[1].split('"', 1)[0] if '"quotaValue"' in text else "?"
    return f"{', '.join(found) or 'quota'} = {value}"


@pytest.fixture(autouse=True)
def _real_llm() -> None:
    llm.configure()


@pytest.mark.parametrize("model", _models() or ["none"])
async def test_json_text_and_tool_call(model: str) -> None:
    if model == "none":
        pytest.skip("no configured model has a key")
    started = time.monotonic()
    try:
        resp = await llm._call(
            model,
            messages=[{"role": "user", "content": 'Reply with only this JSON object: {"ok": true, "n": 3}'}],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as exc:
        if type(exc).__name__ == "RateLimitError":
            pytest.skip(f"{model} is rate limited: {_limit_of(exc)}")
        raise
    _report("json", model, started, resp)
    value = llm.parse_json_text(llm._get(llm._message(resp), "content"))
    assert value.get("ok") is True

    started = time.monotonic()
    resp = await llm._call(
        model, messages=[{"role": "user", "content": "Say hello in five words."}], temperature=0.2
    )
    _report("text", model, started, resp)
    assert (llm._get(llm._message(resp), "content") or "").strip()

    started = time.monotonic()
    resp = await llm._call(
        model,
        messages=[{"role": "user", "content": "Use the tool to look up the function named `activate`."}],
        tools=[TOOL],
        tool_choice="auto",
        temperature=0,
    )
    _report("tool", model, started, resp)
    calls = llm._tool_calls(llm._message(resp))
    assert calls and calls[0].name == "find_function"
    assert "activate" in json.dumps(calls[0].arguments)
