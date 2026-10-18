"""Workspace settings (spec B, B.C7, B12a): approvers, prices, public replays, thresholds, budget."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from actron.api.deps import Ctx, current, once, owner, writer
from actron.config import get_settings
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import budget as budget_mod
from actron.flow import service

router = APIRouter(tags=["settings"])

# PRD 10.2a: which jobs are judgments (Jev) and which write text (LLM).
JEV_JOBS = [("classify_message", "choice"), ("is_approval", "noul"), ("judge_link", "noul"), ("check_link", "noul"),
            ("rank_candidates", "score"), ("judge_conflict", "choice"), ("classify_request", "choice"),
            ("needs_question", "noul"), ("is_scope_change", "noul"), ("feedback_kind", "choice")]
LLM_JOBS = [("extract_decision", "json"), ("write_questions", "json"), ("write_ticket", "json"),
            ("write_answer", "text"), ("summarize_findings", "text"), ("investigator", "tools")]
SCHEDULES = {"code": "every 15 minutes", "github": "every 5 minutes", "linear": "every 5 minutes",
             "slack": "every 10 minutes"}


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict: float | None = Field(default=None, ge=0, le=1)
    possibleConflict: float | None = Field(default=None, ge=0, le=1)
    linkKeep: float | None = Field(default=None, ge=0, le=1)


class Price(BaseModel):
    inputPerMTokUsd: float = Field(ge=0)
    outputPerMTokUsd: float = Field(ge=0)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approvers: list[str] | None = Field(default=None, max_length=200)
    modelPrices: dict[str, Price] | None = None
    allowPublicReplays: bool | None = None
    thresholds: Thresholds | None = None
    botIdentity: dict[str, str] | None = None


class BudgetIn(BaseModel):
    capUsd: float = Field(ge=0, le=100000)


def settings_view(ws: str) -> dict[str, Any]:
    s = get_settings()
    with session_scope() as session:
        row = session.get(m.Workspace, ws)
        stored = dict((row.settings if row else None) or {})
        status = budget_mod.status(session, ws)
        prices = budget_mod.prices(session, ws)
    thresholds = {"conflict": s.CONFLICT_THRESHOLD, "possibleConflict": s.POSSIBLE_CONFLICT_THRESHOLD,
                  "linkKeep": s.LINK_KEEP_THRESHOLD, **(stored.get("thresholds") or {})}
    integ = s.integrations()
    jobs = [{"job": j, "primitive": p, "provider": "jev" if integ["jev"] == "live" else
             ("llm" if integ["llm"] == "live" else "stub"),
             "status": "live" if integ["jev"] == "live" or integ["llm"] == "live" else "stub"} for j, p in JEV_JOBS]
    jobs += [{"job": j, "primitive": p, "provider": "llm" if integ["llm"] == "live" else "stub",
              "status": "live" if integ["llm"] == "live" else "stub"} for j, p in LLM_JOBS]
    bot = {"name": s.ACTRON_BOT_NAME or "", "email": s.ACTRON_BOT_EMAIL or "", **(stored.get("botIdentity") or {})}
    return {
        "approvers": list(stored.get("approvers") or []),
        "modelPrices": prices,
        "allowPublicReplays": bool(stored.get("allowPublicReplays", False)),
        "thresholds": thresholds,
        "models": {"decision": s.MODEL_DECISION or "", "writing": s.MODEL_WRITING or "", "agent": s.MODEL_AGENT or "",
                   "coding": s.MODEL_CODING or ""},
        "jobs": jobs,
        "botIdentity": {"name": bot.get("name", ""), "email": bot.get("email", "")},
        "budget": {"capUsd": status["capUsd"], "spentTodayUsd": status["spentTodayUsd"]},
        "schedules": SCHEDULES,
    }


@router.get("/api/settings")
async def get_workspace_settings(ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return {"settings": await asyncio.to_thread(settings_view, ctx.ws)}


@router.put("/api/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(owner)) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    if "thresholds" in patch:
        patch["thresholds"] = {k: v for k, v in patch["thresholds"].items() if v is not None}

    def apply() -> dict[str, Any]:
        with session_scope() as session:
            row = session.get(m.Workspace, ctx.ws)
            assert row is not None
            current_settings = dict(row.settings or {})
            if "thresholds" in patch:
                patch["thresholds"] = {**(current_settings.get("thresholds") or {}), **patch["thresholds"]}
            row.settings = {**current_settings, **patch}
        return {"settings": settings_view(ctx.ws)}

    async def run() -> dict[str, Any]:
        return await asyncio.to_thread(apply)

    return await once(ctx, "put_settings", run)


@router.post("/api/settings/budget")
async def raise_budget(body: BudgetIn, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    await service.raise_budget(ctx.ws, body.capUsd, ctx.actor(), ctx.idempotency_key)
    return {"settings": await asyncio.to_thread(settings_view, ctx.ws)}
