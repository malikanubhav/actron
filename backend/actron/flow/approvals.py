"""Approvals (spec B, B8, B12a): who may approve, the approvals rows, and the outcome hand-back to the service.

The service records the user's request (`approval.requested`); the workflow decides and writes the row. The
service waits up to 3 seconds for that decision on Redis key `outcome:<idempotencyKey>`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from actron.db import models as m
from actron.logging import get_logger

log = get_logger(__name__)

OUTCOME_TTL_S = 3600


def is_member(session: Session, ws: str, user_id: uuid.UUID | None) -> bool:
    if user_id is None:
        return False
    return session.get(m.Membership, (user_id, ws)) is not None


def is_approver(session: Session, ws: str, request: m.Request, user_id: uuid.UUID | None,
                slack_user_id: str | None) -> bool:
    """B12a: the requester, the workspace owner, or anyone on `settings.approvers` (Slack user ids)."""
    if user_id is not None and request.requester_user_id == user_id:
        return True
    if user_id is not None:
        membership = session.get(m.Membership, (user_id, ws))
        if membership is not None and membership.role == "owner":
            return True
        if slack_user_id is None:
            user = session.get(m.User, user_id)
            slack_user_id = user.slack_user_id if user else None
    wsrow = session.get(m.Workspace, ws)
    approvers = {str(a) for a in ((wsrow.settings or {}).get("approvers") or [])} if wsrow else set()
    return bool(slack_user_id and slack_user_id in approvers)


def record(
    session: Session,
    request_id: str,
    *,
    kind: str,
    target: str,
    status: str,
    reason: str | None,
    actor: dict[str, Any],
) -> m.Approval:
    surface = actor.get("surface") if actor.get("surface") in ("slack", "ui") else "ui"
    user_id = actor.get("userId")
    row = m.Approval(
        request_id=request_id, kind=kind, target=target, status=status, reason=reason, surface=surface,
        actor_user_id=uuid.UUID(str(user_id)) if user_id else None, actor_slack_id=actor.get("slackUserId"),
        actor_name=actor.get("name"), created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def accepted_targets(session: Session, request_id: str, kind: str) -> set[str]:
    rows = session.scalars(
        select(m.Approval.target).where(
            m.Approval.request_id == request_id, m.Approval.kind == kind, m.Approval.status == "accepted"
        )
    ).all()
    return set(rows)


def view(row: m.Approval) -> dict[str, Any]:
    from actron.flow.events import iso

    return {
        "id": str(row.id),
        "kind": row.kind,
        "target": row.target,
        "status": row.status,
        "reason": row.reason,
        "by": {"personId": None, "userId": str(row.actor_user_id) if row.actor_user_id else None,
               "name": row.actor_name or row.actor_slack_id or "Someone", "avatarUrl": None},
        "surface": row.surface,
        "at": iso(row.created_at),
    }


# Outcome hand-back (Redis). Keys are per request and idempotency key, so a retried request reads the same
# outcome and two requests never share one.
def outcome_key(request_id: str, idempotency_key: str) -> str:
    return f"outcome:{request_id}:{idempotency_key}"


async def publish_outcome(request_id: str, idempotency_key: str, outcome: dict[str, Any]) -> None:
    from actron.flow.events import redis_client

    key = outcome_key(request_id, idempotency_key)
    try:
        client = redis_client()
        data = json.dumps(outcome)
        await client.set(key, data, ex=OUTCOME_TTL_S)
        await client.publish(key, data)
    except Exception as exc:
        log.warning("outcome publish failed", extra={"error": type(exc).__name__})


async def wait_outcome(request_id: str, idempotency_key: str, timeout_s: float = 3.0) -> dict[str, Any] | None:
    """Wait for the workflow's decision. Subscribes first, then checks the stored value, so nothing is missed."""
    from actron.flow.events import redis_client

    key = outcome_key(request_id, idempotency_key)
    client = redis_client()
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(key)
        stored = await client.get(key)
        if stored:
            result: dict[str, Any] = json.loads(stored)
            return result
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                return None
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(left, 0.5))
            if msg:
                out: dict[str, Any] = json.loads(msg["data"])
                return out
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass
