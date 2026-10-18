"""Daily model budget (spec B, B12a; PRD 16).

Today's estimated spend = `model_calls` for the workspace (cost when recorded, else tokens x price table) plus
build token costs. At or above the cap, investigations use the pipeline with stubs and builds wait until the cap
is raised (`budget_raised` signal) or the next UTC day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from actron.config import get_settings
from actron.db import models as m

# USD per million tokens. Defaults are editable in Settings (`settings.modelPrices`).
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet-4-5": {"inputPerMTokUsd": 3.0, "outputPerMTokUsd": 15.0},
    "anthropic/claude-haiku-4-5": {"inputPerMTokUsd": 1.0, "outputPerMTokUsd": 5.0},
    "jev-1.13.0": {"inputPerMTokUsd": 0.0, "outputPerMTokUsd": 0.0},
}
FALLBACK_PRICE = {"inputPerMTokUsd": 3.0, "outputPerMTokUsd": 15.0}


def day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def next_day_start(now: datetime | None = None) -> datetime:
    return day_start(now) + timedelta(days=1)


def prices(session: Session, ws: str) -> dict[str, dict[str, float]]:
    wsrow = session.get(m.Workspace, ws)
    custom = ((wsrow.settings or {}).get("modelPrices") or {}) if wsrow else {}
    settings = get_settings()
    out = dict(DEFAULT_PRICES)
    for model in filter(None, [settings.MODEL_DECISION, settings.MODEL_WRITING, settings.MODEL_AGENT,
                               settings.MODEL_CODING]):
        out.setdefault(model, dict(FALLBACK_PRICE))
    out.update({k: {"inputPerMTokUsd": float(v.get("inputPerMTokUsd", 0)),
                    "outputPerMTokUsd": float(v.get("outputPerMTokUsd", 0))} for k, v in custom.items()})
    return out


def cost_of(price_table: dict[str, dict[str, float]], model: str | None, input_tokens: int, output_tokens: int) -> float:
    p = price_table.get(model or "", FALLBACK_PRICE)
    return (input_tokens * p["inputPerMTokUsd"] + output_tokens * p["outputPerMTokUsd"]) / 1_000_000


def cap_usd(session: Session, ws: str) -> float:
    wsrow = session.get(m.Workspace, ws)
    budget = ((wsrow.settings or {}).get("budget") or {}) if wsrow else {}
    if "capUsd" in budget:
        return float(budget["capUsd"])
    return float(get_settings().ACTRON_DAILY_MODEL_BUDGET_USD)


def set_cap(session: Session, ws: str, cap: float) -> None:
    wsrow = session.get(m.Workspace, ws)
    if wsrow is None:
        raise LookupError(ws)
    settings = dict(wsrow.settings or {})
    settings["budget"] = {**(settings.get("budget") or {}), "capUsd": float(cap)}
    wsrow.settings = settings
    session.flush()


def spent_today(session: Session, ws: str, now: datetime | None = None) -> float:
    start = day_start(now)
    table = prices(session, ws)
    total = 0.0
    rows = session.execute(
        select(m.ModelCall.model, m.ModelCall.cost_usd, m.ModelCall.input_tokens, m.ModelCall.output_tokens,
               m.ModelCall.stub)
        .where(m.ModelCall.workspace_id == ws, m.ModelCall.created_at >= start)
    ).all()
    for model, cost, tin, tout, stub in rows:
        if stub:
            continue
        total += float(cost) if cost else cost_of(table, model, int(tin or 0), int(tout or 0))
    coding = get_settings().MODEL_CODING
    builds = session.execute(
        select(m.BuildRun.cost_usd, m.BuildRun.input_tokens, m.BuildRun.output_tokens)
        .join(m.Request, m.Request.id == m.BuildRun.request_id)
        .where(m.Request.workspace_id == ws, m.BuildRun.started_at >= start)
    ).all()
    for cost, tin, tout in builds:
        total += float(cost) if cost else cost_of(table, coding, int(tin or 0), int(tout or 0))
    return round(total, 4)


def status(session: Session, ws: str, now: datetime | None = None) -> dict[str, Any]:
    cap = cap_usd(session, ws)
    spent = spent_today(session, ws, now)
    return {"capUsd": cap, "spentTodayUsd": spent, "reached": spent >= cap}


def request_costs(session: Session, request_id: str) -> dict[str, Any]:
    """Investigation tokens and estimated cost for one request (from `model_calls`)."""
    row = session.execute(
        select(func.coalesce(func.sum(m.ModelCall.input_tokens), 0), func.coalesce(func.sum(m.ModelCall.output_tokens), 0),
               func.coalesce(func.sum(m.ModelCall.cost_usd), 0.0))
        .where(m.ModelCall.request_id == request_id)
    ).one()
    return {"tokens": {"input": int(row[0]), "output": int(row[1])}, "costUsd": round(float(row[2]), 4)}
