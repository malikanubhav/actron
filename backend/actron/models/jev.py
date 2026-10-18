"""Jev (TypeSafe System One) transport and response parsing (spec A, A13; PRD 10.2).

Transport: plain `httpx` POST to `JEV_API_URL` (decision in BUILD-LOG and docs/models-and-jev.md:
`typesafe-sdk` 0.7.5 ships its own `httpx2` fork and a tenacity retry policy whose defaults do not
retry 529; plain httpx gives the exact retry rules of the spec and a transport tests can replace).
Retries: 429 and 529 only, waits 0.5, 1, 2 s between at most 4 attempts (Retry-After honoured up
to 4 s). 400/401/413/415/422 raise typed errors and are never retried.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from actron.config import get_settings
from actron.models.questions import JevAsk
from actron.models.types import InvalidModelOutput, ModelError, ModelUnavailable

TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)
RETRY_STATUSES = frozenset({429, 529})


class JevError(ModelError):
    """A Jev call failed."""

    status: int | None = None

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class JevUnavailable(ModelUnavailable):
    """No TYPESAFE_API_KEY is set."""


class JevBadRequest(JevError):
    """400: the body breaks a request rule (or `max_tokens_exceeded`)."""


class JevAuthError(JevError):
    """401: missing or invalid API key."""


class JevPayloadTooLarge(JevError):
    """413: body over 32 MiB."""


class JevUnsupportedMediaType(JevError):
    """415: unsupported Content-Encoding."""


class JevValidationError(JevError):
    """422: a question or field failed validation."""


class JevRateLimited(JevError):
    """429 or 529 after the last retry."""


class JevTimeout(JevError):
    """No answer within the timeout."""


class JevResponseError(InvalidModelOutput):
    """Jev answered with a body that does not match the documented answer shape."""


_TYPED: dict[int, type[JevError]] = {
    400: JevBadRequest,
    401: JevAuthError,
    413: JevPayloadTooLarge,
    415: JevUnsupportedMediaType,
    422: JevValidationError,
}


@dataclass(frozen=True)
class JevAnswer:
    """One parsed answer. `value` is the noul probability, the chosen option, or the score."""

    type: str
    value: Any
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    legend: dict[str, str] | None = None


@dataclass
class JevResponse:
    model: str
    answers: dict[str, JevAnswer]
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1
    raw: dict[str, Any] = field(default_factory=dict)


# Test seams: tests install an httpx.MockTransport and a sleep that records delays.
_transport: httpx.AsyncBaseTransport | None = None
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def set_sleep(fn: Callable[[float], Awaitable[None]] | None) -> None:
    global _sleep
    _sleep = fn or asyncio.sleep


def available() -> bool:
    return bool(get_settings().TYPESAFE_API_KEY)


def model_name() -> str:
    return get_settings().JEV_MODEL


def _float(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JevResponseError(f"{where}: expected a number, got {value!r}")
    return float(value)


def _probs(value: Any, where: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise JevResponseError(f"{where}: probabilities must be an object")
    return {str(k): _float(v, f"{where}.{k}") for k, v in value.items()}


def parse_answer(qid: str, primitive: str, raw: Any) -> JevAnswer:
    """Parse one answer per A.C4 (`noul`, `choice`, `score`)."""
    if not isinstance(raw, dict):
        raise JevResponseError(f"answer {qid}: not an object")
    kind = raw.get("type", primitive)
    if kind != primitive:
        raise JevResponseError(f"answer {qid}: type {kind!r}, expected {primitive!r}")
    conf = raw.get("confidence")
    confidence = _float(conf, f"{qid}.confidence") if conf is not None else None
    if primitive == "noul":
        return JevAnswer("noul", _float(raw.get("noul"), f"{qid}.noul"), None, confidence)
    if primitive == "choice":
        choice = raw.get("choice")
        if not isinstance(choice, str):
            raise JevResponseError(f"answer {qid}: missing choice")
        return JevAnswer("choice", choice, _probs(raw.get("probabilities"), qid), confidence)
    if primitive == "score":
        legend = raw.get("legend")
        return JevAnswer(
            "score",
            _float(raw.get("score"), f"{qid}.score"),
            _probs(raw.get("probabilities"), qid),
            confidence,
            {str(k): str(v) for k, v in legend.items()} if isinstance(legend, dict) else None,
        )
    raise JevResponseError(f"answer {qid}: unknown primitive {primitive!r}")


def parse_response(ask: JevAsk, body: Any) -> tuple[str, dict[str, JevAnswer], int, int]:
    if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
        raise JevResponseError("response has no answers object")
    answers: dict[str, JevAnswer] = {}
    for qid in ask.questions:
        if qid not in body["answers"]:
            raise JevResponseError(f"answer {qid} missing")
        answers[qid] = parse_answer(qid, ask.primitive(qid), body["answers"][qid])
    usage = body.get("usage") or {}
    return (
        str(body.get("model") or ""),
        answers,
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
    )


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


async def ask(
    question: JevAsk, *, model: str | None = None, timeout: float = TIMEOUT_SECONDS
) -> JevResponse:
    """Send one request (all its questions together). Raises a typed `JevError` on failure."""
    settings = get_settings()
    key = settings.TYPESAFE_API_KEY
    if not key:
        raise JevUnavailable("TYPESAFE_API_KEY is not set")
    model = model or settings.JEV_MODEL
    payload = question.body(model)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    started = time.monotonic()
    async with httpx.AsyncClient(transport=_transport, timeout=timeout) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(settings.JEV_API_URL, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise JevTimeout(f"Jev did not answer in {timeout:.0f} seconds") from exc
            except httpx.HTTPError as exc:
                raise JevError(f"Jev request failed: {type(exc).__name__}") from exc
            if resp.status_code in RETRY_STATUSES:
                if attempt == MAX_ATTEMPTS:
                    raise JevRateLimited(
                        f"Jev returned {resp.status_code} after {attempt} attempts",
                        status=resp.status_code,
                    )
                delay = BACKOFF_SECONDS[attempt - 1]
                hinted = _retry_after(resp)
                if hinted is not None:
                    delay = min(max(delay, hinted), BACKOFF_SECONDS[-1])
                await _sleep(delay)
                continue
            if resp.status_code != 200:
                err = _TYPED.get(resp.status_code, JevError)
                try:
                    body: Any = resp.json()
                except ValueError:
                    body = resp.text[:500]
                raise err(f"Jev returned {resp.status_code}", status=resp.status_code, body=body)
            try:
                data = resp.json()
            except ValueError as exc:
                raise JevResponseError("Jev returned a body that is not JSON") from exc
            used_model, answers, tin, tout = parse_response(question, data)
            return JevResponse(
                model=used_model or model,
                answers=answers,
                input_tokens=tin,
                output_tokens=tout,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                raw=data,
            )
    raise JevError("unreachable")  # pragma: no cover
