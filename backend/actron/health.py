"""Health of the stores and the integration summary for `GET /api/health` (spec A, A1)."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any, Literal

import redis
from sqlalchemy import create_engine, text
from temporalio.client import Client

from actron.config import REPO_ROOT, Settings
from actron.logging import get_logger

log = get_logger(__name__)

Status = Literal["ok", "error"]
CHECK_TIMEOUT_S = 3.0


@lru_cache(maxsize=1)
def app_version() -> str:
    """Git short sha, `ACTRON_VERSION` when set (images have no .git), else `dev`."""
    env = os.environ.get("ACTRON_VERSION")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return out.stdout.strip() or "dev"
    except (OSError, subprocess.SubprocessError):
        return "dev"


def _ping_redis(url: str) -> None:
    client = redis.Redis.from_url(
        url, socket_connect_timeout=CHECK_TIMEOUT_S, socket_timeout=CHECK_TIMEOUT_S
    )
    try:
        client.ping()
    finally:
        client.close()


def _ping_postgres(url: str) -> None:
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    engine = create_engine(url, connect_args={"connect_timeout": int(CHECK_TIMEOUT_S)})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


async def _ping_temporal(address: str, namespace: str) -> None:
    client = await Client.connect(address, namespace=namespace)
    if not await client.service_client.check_health(timeout=_seconds(CHECK_TIMEOUT_S)):
        raise RuntimeError("temporal reports not serving")


def _seconds(value: float) -> Any:
    from datetime import timedelta

    return timedelta(seconds=value)


async def _status(name: str, check: Callable[[], Awaitable[Any]]) -> Status:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_S + 1)
    except Exception as exc:
        log.warning("health check failed", extra={"store": name, "error": type(exc).__name__})
        return "error"
    return "ok"


async def check_health(settings: Settings) -> dict[str, Any]:
    """Probe each store concurrently. Each probe has its own timeout, so one dead store never hangs the call."""
    falkor, postgres, redis_status, temporal = await asyncio.gather(
        _status("falkordb", lambda: asyncio.to_thread(_ping_redis, settings.FALKORDB_URL)),
        _status("postgres", lambda: asyncio.to_thread(_ping_postgres, settings.DATABASE_URL)),
        _status("redis", lambda: asyncio.to_thread(_ping_redis, settings.REDIS_URL)),
        _status(
            "temporal",
            lambda: _ping_temporal(settings.TEMPORAL_ADDRESS, settings.TEMPORAL_NAMESPACE),
        ),
    )
    return {
        "falkordb": falkor,
        "postgres": postgres,
        "redis": redis_status,
        "temporal": temporal,
        "integrations": settings.integrations(),
        "version": app_version(),
        "falkordb_binding": settings.FALKORDB_BINDING,
    }


def all_stores_ok(health: dict[str, Any]) -> bool:
    return all(health[k] == "ok" for k in ("falkordb", "postgres", "redis", "temporal"))
