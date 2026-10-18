"""LiteLLM calls: per-job models, JSON mode, fallback chain, tool-calling turns (A13; PRD 10.3).

Model per kind of work comes from settings: `MODEL_DECISION` (judgment fallback, extraction),
`MODEL_WRITING` (questions, tickets, answers, summaries), `MODEL_AGENT` (investigator tool use).
`LITELLM_FALLBACKS` lists more models tried in order when a provider call fails.
Keys are passed explicitly (settings come from `.env`, which LiteLLM does not read).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from actron.config import get_settings
from actron.logging import get_logger
from actron.models import usage
from actron.models.types import (
    AgentTurn,
    InvalidModelOutput,
    ModelError,
    ModelUnavailable,
    ToolCall,
)

log = get_logger(__name__)

Kind = Literal["decision", "writing", "agent"]
CompletionFn = Callable[..., Awaitable[Any]]

TIMEOUT_SECONDS = 60
PROVIDER_KEYS = {
    "anthropic/": "ANTHROPIC_API_KEY",
    "openrouter/": "OPENROUTER_API_KEY",
    "gemini/": "GEMINI_API_KEY",
    "groq/": "GROQ_API_KEY",
    "deepseek/": "DEEPSEEK_API_KEY",
}
JSON_OBJECT_ONLY = ("deepseek/",)
JSON_REMINDER = (
    "Your last reply was not valid JSON in the required shape. "
    "Reply again with only one JSON object in exactly the required shape, and nothing else."
)

# Test seams: a fake completion function and an api_base (local OpenAI-compatible fake server).
_completion_fn: CompletionFn | None = None
_api_base: str | None = None
_api_key_override: str | None = None


def configure(
    *,
    completion_fn: CompletionFn | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> None:
    global _completion_fn, _api_base, _api_key_override
    _completion_fn = completion_fn
    _api_base = api_base
    _api_key_override = api_key


class LLMCallError(ModelError):
    """A provider call failed (after LiteLLM's own retries)."""


def _key_for(model: str) -> str | None:
    if _api_key_override:
        return _api_key_override
    settings = get_settings()
    for prefix, name in PROVIDER_KEYS.items():
        if model.startswith(prefix):
            value: str | None = getattr(settings, name)
            return value
    return None


def chain(kind: Kind) -> list[str]:
    """Models to try for this kind of work, in order, keeping only those with a key."""
    settings = get_settings()
    primary = settings.model_for(kind)
    names = [m for m in [primary, *settings.litellm_fallbacks] if m]
    out: list[str] = []
    for name in names:
        if name not in out and _key_for(name):
            out.append(name)
    return out


def available(kind: Kind) -> bool:
    return bool(chain(kind))


async def _call(model: str, **kwargs: Any) -> Any:
    fn = _completion_fn
    if fn is None:
        import litellm

        fn = litellm.acompletion
    extra: dict[str, Any] = {}
    if _api_base:
        extra["api_base"] = _api_base
    return await fn(
        model=model,
        api_key=_key_for(model),
        timeout=TIMEOUT_SECONDS,
        num_retries=2,
        drop_params=True,
        **extra,
        **kwargs,
    )


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _message(resp: Any) -> Any:
    choices = _get(resp, "choices") or []
    if not choices:
        raise InvalidModelOutput("completion has no choices")
    return _get(choices[0], "message")


def tokens_of(resp: Any) -> tuple[int, int]:
    u = _get(resp, "usage") or {}
    return int(_get(u, "prompt_tokens", 0) or 0), int(_get(u, "completion_tokens", 0) or 0)


def parse_json_text(text: str | None) -> dict[str, Any]:
    if not text:
        raise InvalidModelOutput("empty reply")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{") :] if "{" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise InvalidModelOutput("reply has no JSON object")
    try:
        value = json.loads(raw[start : end + 1])
    except ValueError as exc:
        raise InvalidModelOutput(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InvalidModelOutput("reply JSON is not an object")
    return value


async def _record(
    job: str,
    model: str,
    started: float,
    tin: int,
    tout: int,
    *,
    ok: bool,
    error: str | None,
    ws: str | None,
    request_id: str | None,
) -> None:
    await usage.record(
        usage.UsageRow(
            job=job,
            provider="llm",
            model=model,
            workspace_id=ws,
            request_id=request_id,
            input_tokens=tin,
            output_tokens=tout,
            latency_ms=int((time.monotonic() - started) * 1000),
            ok=ok,
            error=error,
        )
    )


async def complete_json[T](
    kind: Kind,
    messages: Sequence[dict[str, Any]],
    validate: Callable[[dict[str, Any]], T],
    *,
    job: str,
    ws: str | None = None,
    request_id: str | None = None,
    json_schema: dict[str, Any] | None = None,
) -> tuple[T, str]:
    """Ask for one JSON object and validate it. Returns (value, model).

    A provider error moves to the next model in the chain. An invalid reply is retried once on the
    same model with a reminder; a second invalid reply raises `InvalidModelOutput` (caller stubs).
    Raises `ModelUnavailable` when no model with a key is configured.
    """
    models = chain(kind)
    if not models:
        raise ModelUnavailable(f"no {kind} model with a key is configured")
    schema_format: dict[str, Any] = (
        {"type": "json_schema", "json_schema": {"name": job, "schema": json_schema}}
        if json_schema
        else {"type": "json_object"}
    )
    last_error: Exception | None = None
    for model in models:
        convo = list(messages)
        response_format = schema_format
        if json_schema and model.startswith(JSON_OBJECT_ONLY):
            # DeepSeek accepts only `json_object` (a `json_schema` request is a 400): put the schema in the prompt.
            response_format = {"type": "json_object"}
            convo.append({"role": "user", "content": f"Reply with one JSON object that matches this JSON schema:\n{json.dumps(json_schema)}"})
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                resp = await _call(
                    model, messages=convo, response_format=response_format, temperature=0
                )
            except Exception as exc:
                await _record(
                    job,
                    model,
                    started,
                    0,
                    0,
                    ok=False,
                    error=type(exc).__name__,
                    ws=ws,
                    request_id=request_id,
                )
                log.warning(
                    "llm call failed",
                    extra={"job": job, "model": model, "error": type(exc).__name__},
                )
                last_error = exc
                break  # next model
            tin, tout = tokens_of(resp)
            text = _get(_message(resp), "content")
            try:
                value = validate(parse_json_text(text))
            except (InvalidModelOutput, ValueError, TypeError, KeyError) as exc:
                await _record(
                    job,
                    model,
                    started,
                    tin,
                    tout,
                    ok=False,
                    error=f"invalid: {exc}"[:300],
                    ws=ws,
                    request_id=request_id,
                )
                if attempt == 2:
                    raise InvalidModelOutput(f"{job}: invalid reply twice from {model}") from exc
                convo = [
                    *convo,
                    {"role": "assistant", "content": text or ""},
                    {"role": "user", "content": f"{JSON_REMINDER} Problem: {exc}"},
                ]
                continue
            await _record(
                job, model, started, tin, tout, ok=True, error=None, ws=ws, request_id=request_id
            )
            return value, model
    raise LLMCallError(f"{job}: every model failed") from last_error


async def complete_text(
    kind: Kind,
    messages: Sequence[dict[str, Any]],
    *,
    job: str,
    ws: str | None = None,
    request_id: str | None = None,
) -> tuple[str, str]:
    models = chain(kind)
    if not models:
        raise ModelUnavailable(f"no {kind} model with a key is configured")
    last_error: Exception | None = None
    for model in models:
        started = time.monotonic()
        try:
            resp = await _call(model, messages=list(messages), temperature=0.2)
        except Exception as exc:
            await _record(
                job,
                model,
                started,
                0,
                0,
                ok=False,
                error=type(exc).__name__,
                ws=ws,
                request_id=request_id,
            )
            last_error = exc
            continue
        tin, tout = tokens_of(resp)
        text = _get(_message(resp), "content") or ""
        await _record(
            job,
            model,
            started,
            tin,
            tout,
            ok=bool(text.strip()),
            error=None if text.strip() else "empty",
            ws=ws,
            request_id=request_id,
        )
        if text.strip():
            return text.strip(), model
    raise LLMCallError(f"{job}: every model failed") from last_error


def _tool_calls(message: Any) -> list[ToolCall]:
    out: list[ToolCall] = []
    for i, call in enumerate(_get(message, "tool_calls") or []):
        fn = _get(call, "function") or {}
        raw = _get(fn, "arguments") or "{}"
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                parsed = json.loads(raw)
                args = parsed if isinstance(parsed, dict) else {"value": parsed}
            except ValueError:
                args = {"_raw": str(raw)}
        out.append(
            ToolCall(
                id=str(_get(call, "id") or f"call_{i}"),
                name=str(_get(fn, "name") or ""),
                arguments=args,
            )
        )
    return out


async def agent_completion(
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> AgentTurn:
    """One tool-calling turn with `MODEL_AGENT`. Raises `ModelUnavailable` without an agent key."""
    models = chain("agent")
    if not models:
        raise ModelUnavailable("no agent model with a key is configured (MODEL_AGENT)")
    last_error: Exception | None = None
    for model in models:
        started = time.monotonic()
        try:
            resp = await _call(
                model,
                messages=list(messages),
                tools=list(tools) or None,
                tool_choice="auto" if tools else None,
                temperature=0,
            )
        except Exception as exc:
            await _record(
                "agent_completion",
                model,
                started,
                0,
                0,
                ok=False,
                error=type(exc).__name__,
                ws=ws,
                request_id=request_id,
            )
            last_error = exc
            continue
        tin, tout = tokens_of(resp)
        message = _message(resp)
        await _record(
            "agent_completion",
            model,
            started,
            tin,
            tout,
            ok=True,
            error=None,
            ws=ws,
            request_id=request_id,
        )
        return AgentTurn(
            tool_calls=_tool_calls(message),
            content=_get(message, "content"),
            tokens={"input": tin, "output": tout},
            stub=False,
            model=model,
        )
    raise LLMCallError("agent_completion: every model failed") from last_error
