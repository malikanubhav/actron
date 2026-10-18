"""Replays (spec B, B.C7): every event of a finished request; a redacted public version when allowed."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from actron.api.deps import ApiError, Ctx, current
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow.events import load_request_events
from actron.flow.service import build_request_view
from actron.flow.states import FINAL_STATES

router = APIRouter(tags=["replay"])

_PERSONAL_KEYS = re.compile(r"(?i)^(name|author|email|userId|slackUserId|toUserId|personId|avatarUrl|requester|"
                            r"by|channel|threadTs|permalink|slack|idempotencyKey|actor)$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(value: Any) -> Any:
    """Remove people and Slack locations from a replay (names become 'A teammate')."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _PERSONAL_KEYS.match(str(k)):
                if str(k) in ("name", "author"):
                    out[k] = "A teammate"
                elif str(k) in ("by", "requester"):
                    out[k] = {"personId": None, "userId": None, "name": "A teammate", "avatarUrl": None}
                else:
                    out[k] = None
            elif str(k) == "signalPayload":
                continue
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _EMAIL.sub("[email]", value)
    return value


def _replay(ws: str, request_id: str) -> dict[str, Any]:
    with session_scope() as s:
        view = build_request_view(s, ws, request_id)
    if view["state"] not in {st.value for st in FINAL_STATES}:
        raise ApiError(409, "not_finished", "The replay is available once the request is done or cancelled.")
    events = [e.envelope() for e in load_request_events(ws, request_id)]
    for e in events:
        e["payload"].pop("signalPayload", None)
    return {"request": view, "events": events}


@router.get("/api/requests/{request_id}/replay")
async def replay(request_id: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return await asyncio.to_thread(_replay, ctx.ws, request_id)


def _public(request_id: str) -> dict[str, Any]:
    with session_scope() as s:
        row = s.scalar(select(m.Request).where(m.Request.id == request_id))
        ws = s.get(m.Workspace, row.workspace_id) if row else None
        allowed = bool(ws and (ws.settings or {}).get("allowPublicReplays"))
        if row is None or not allowed:
            raise ApiError(404, "not_found", "This replay is not public.")
        ws_id = row.workspace_id
    try:
        data = _replay(ws_id, request_id)
    except ApiError as exc:
        raise ApiError(404, "not_found", "This replay is not public.") from exc
    out: dict[str, Any] = redact(data)
    return out


@router.get("/api/public/replays/{request_id}")
async def public_replay(request_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_public, request_id)
