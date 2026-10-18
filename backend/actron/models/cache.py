"""Redis cache for model judgments (spec A, A13).

Key: `model:<job>:<sha256(model + canonical(state) + canonical(questions))>`, TTL 7 days.
Stubs and errors are never cached. When Redis is down the cache is skipped, never fatal.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import redis.asyncio as aioredis

from actron.config import get_settings
from actron.logging import get_logger

log = get_logger(__name__)

TTL_SECONDS = 7 * 24 * 3600
_clients: dict[int, aioredis.Redis[str]] = {}
_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def key_for(job: str, model: str, state: Any, questions: Any) -> str:
    digest = hashlib.sha256(
        (model + canonical(state) + canonical(questions)).encode("utf-8")
    ).hexdigest()
    return f"model:{job}:{digest}"


def _client() -> aioredis.Redis[str]:
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None:
        client = aioredis.Redis.from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        _clients[loop_id] = client
    return client


def reset() -> None:
    """Forget clients (tests change REDIS_URL between runs)."""
    _clients.clear()


async def get(key: str) -> dict[str, Any] | None:
    if not _enabled:
        return None
    try:
        raw = await _client().get(key)
    except Exception as exc:  # Redis down or unreachable: skip the cache
        log.warning("model cache read failed", extra={"error": type(exc).__name__})
        return None
    if not raw:
        return None
    try:
        value: dict[str, Any] = json.loads(raw)
    except ValueError:
        return None
    return value


async def put(key: str, value: dict[str, Any]) -> None:
    if not _enabled or value.get("stub"):
        return
    try:
        await _client().set(key, canonical(value), ex=TTL_SECONDS)
    except Exception as exc:
        log.warning("model cache write failed", extra={"error": type(exc).__name__})
