"""GitHub webhook (spec A, A11): verify, deduplicate, trigger the schedules. Routing is W3's `handle_webhook`."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from actron.api.deps import error_response
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow.events import redis_client
from actron.flow.service import get_gateway
from actron.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["webhooks"])
DELIVERY_TTL_S = 7 * 24 * 3600


def _candidates(repo_hint: str) -> list[tuple[str, dict[str, Any]]]:
    """Workspaces with a GitHub connection, the matching repository first, with their effective values."""
    from actron.connectors.common import resolve_config

    with session_scope() as s:
        rows = s.execute(select(m.Connection.workspace_id, m.Connection.config).where(
            m.Connection.provider == "github", m.Connection.status == "connected")).all()
    ordered = sorted(rows, key=lambda r: str((r[1] or {}).get("repository", "")).lower() != repo_hint)
    out = []
    for ws, _ in ordered:
        try:
            out.append((str(ws), dict(resolve_config(str(ws), "github").values)))
        except Exception as exc:
            log.warning("webhook config unreadable", extra={"error": type(exc).__name__})
    return out


@router.post("/webhooks/github", status_code=204, responses={401: {"description": "bad signature"}})
async def github_webhook(request: Request) -> Response:
    from actron.connectors.github import handle_webhook, verify_signature

    body = await request.body()
    headers = dict(request.headers)
    try:
        repo_hint = str((json.loads(body or b"{}").get("repository") or {}).get("full_name") or "").lower()
    except ValueError:
        repo_hint = ""
    candidates = await asyncio.to_thread(_candidates, repo_hint)
    sig = headers.get("x-hub-signature-256")
    match = next(((ws, cfg) for ws, cfg in candidates if verify_signature(cfg.get("webhook_secret"), body, sig)), None)
    if match is None:
        return error_response(401, "bad_signature", "The webhook signature did not verify.")
    ws, cfg = match
    delivery = headers.get("x-github-delivery")
    duplicate = False
    if delivery:
        duplicate = not await redis_client().set(f"gh-delivery:{delivery}", "1", nx=True, ex=DELIVERY_TTL_S)
    decision = handle_webhook(headers, body, secret=cfg.get("webhook_secret"),
                              working_branch=cfg.get("working_branch"), repository=cfg.get("repository"),
                              seen=lambda _d: duplicate)
    if decision.status == 401:
        return error_response(401, "bad_signature", decision.reason)
    if decision.status == 400:
        return error_response(400, "bad_request", decision.reason)
    gateway = get_gateway()
    for source in decision.triggers:
        await _trigger(gateway, ws, source)
    for source in decision.debounced:
        # Debounce: at most one trigger per source every `debounce_seconds`.
        if await redis_client().set(f"gh-debounce:{ws}:{source}", "1", nx=True, ex=decision.debounce_seconds):
            await _trigger(gateway, ws, source)
    return Response(status_code=204)


async def _trigger(gateway: Any, ws: str, source: str) -> None:
    try:
        await gateway.trigger_schedule(ws, source)
    except Exception as exc:
        log.warning("webhook trigger failed", extra={"source": source, "error": type(exc).__name__})
