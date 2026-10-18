"""Inbox notifications (spec B, B13): list and mark read; marking read is pushed on the workspace stream."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from actron.api import schemas as sc
from actron.api.deps import ApiError, Ctx, current, writer
from actron.db.session import session_scope
from actron.flow import notifications
from actron.flow.events import publish_workspace_event

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications", response_model=sc.NotificationList)
async def list_notifications(unread: int | None = None, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        with session_scope() as s:
            items, count = notifications.list_for_user(s, ctx.ws, uuid.UUID(ctx.user_id), unread_only=bool(unread))
            return {"notifications": items, "unread": count}

    return await asyncio.to_thread(run)


async def mark_read_and_publish(ws: str, user_id: uuid.UUID, notification_id: uuid.UUID) -> int | None:
    """B-AC-63: mark read, then publish `notification.read {notificationId, unread}` so the inbox count updates."""

    def run() -> int | None:
        with session_scope() as s:
            return notifications.mark_read(s, ws, user_id, notification_id)

    unread = await asyncio.to_thread(run)
    if unread is not None:
        await publish_workspace_event(ws, "notification.read", {"notificationId": str(notification_id),
                                                                "unread": unread, "userId": str(user_id)})
    return unread


@router.post("/api/notifications/{notification_id}/read", status_code=204)
async def read(notification_id: str, ctx: Ctx = Depends(writer)) -> Response:
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        raise ApiError(404, "not_found", "Notification not found.") from None
    if await mark_read_and_publish(ctx.ws, uuid.UUID(ctx.user_id), nid) is None:
        raise ApiError(404, "not_found", "Notification not found.")
    return Response(status_code=204)
