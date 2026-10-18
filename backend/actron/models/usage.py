"""Usage rows for every model call (`model_calls`, spec A, A2/A13) and the daily spend (B12a).

Rows go to a sink. The default sink writes to PostgreSQL; a failing database never fails a call.
Tests install a list sink with `set_sink`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from actron.config import get_settings
from actron.logging import get_logger

log = get_logger(__name__)

# USD per million tokens (input, output), matched by substring of the lowercased model name, first
# match wins. Estimates from public price pages (Oct 2026); `settings.MODEL_PRICES` (JSON object
# {needle: [input, output]}) overrides them when W1 adds that setting.
DEFAULT_PRICES: list[tuple[str, float, float]] = [
    ("jev-", 0.042, 0.0),
    (":free", 0.0, 0.0),
    ("claude-opus", 15.0, 75.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 1.0, 5.0),
    ("deepseek-v4-pro", 0.66, 1.98),
    ("deepseek-flash", 0.15, 0.60),
    ("gemini-2.5-pro", 1.25, 10.0),
    ("gemini-2.5-flash-lite", 0.10, 0.40),
    ("gemini-2.5-flash", 0.30, 2.50),
    ("llama-3.3-70b", 0.59, 0.79),
    ("llama-3.1-8b", 0.05, 0.08),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.0),
]


@dataclass
class UsageRow:
    job: str
    provider: str
    model: str
    workspace_id: str | None = None
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    stub: bool = False
    ok: bool = True
    error: str | None = None


Sink = Callable[[UsageRow], Awaitable[None]]


def price_table() -> list[tuple[str, float, float]]:
    raw = getattr(get_settings(), "MODEL_PRICES", None)
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return [(str(k).lower(), float(v[0]), float(v[1])) for k, v in dict(data).items()]
        except (ValueError, TypeError, IndexError):
            log.warning("MODEL_PRICES is not valid JSON; using defaults")
    return DEFAULT_PRICES


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    name = model.lower()
    for needle, pin, pout in price_table():
        if needle in name:
            return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 8)
    return 0.0


def _write_db(row: UsageRow) -> None:
    from actron.db.models import ModelCall
    from actron.db.session import session_scope

    with session_scope() as session:
        session.add(ModelCall(**asdict(row)))


async def db_sink(row: UsageRow) -> None:
    try:
        await asyncio.to_thread(_write_db, row)
    except Exception as exc:
        log.warning("model_calls write failed", extra={"error": type(exc).__name__, "job": row.job})


_sink: Sink = db_sink


def set_sink(sink: Sink | None) -> None:
    global _sink
    _sink = sink or db_sink


async def record(row: UsageRow) -> None:
    if not row.cost_usd and not row.cached and not row.stub:
        row.cost_usd = cost_for(row.model, row.input_tokens, row.output_tokens)
    await _sink(row)


def spent_today(ws: str, *, url: str | None = None, now: datetime | None = None) -> float:
    """USD spent on model calls by workspace `ws` since 00:00 UTC (daily budget, B12a)."""
    from sqlalchemy import func, select

    from actron.db.models import ModelCall
    from actron.db.session import session_scope

    current = now or datetime.now(UTC)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope(url) as session:
        total = session.execute(
            select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0)).where(
                ModelCall.workspace_id == ws, ModelCall.created_at >= start
            )
        ).scalar_one()
    return float(total)


def over_budget(ws: str, *, url: str | None = None) -> bool:
    return spent_today(ws, url=url) >= get_settings().ACTRON_DAILY_MODEL_BUDGET_USD


def list_sink(rows: list[UsageRow]) -> Sink:
    async def sink(row: UsageRow) -> None:
        rows.append(row)

    return sink


def as_dict(row: UsageRow) -> dict[str, Any]:
    return asdict(row)
