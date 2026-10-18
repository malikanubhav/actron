"""Notifications (spec B, B13; PRD 11.4): only four kinds interrupt a person.

- `question.asked` -> `needs_input` to the requester
- `ticket.synced` (approval is needed next) -> `awaiting_approval` to the requester and the configured approvers
- `build.failed`, or `request.state_changed` to `Needs attention` not caused by a build -> `build_failed` to the requester
- `pr.opened` -> `pr_ready` to the requester and the approvers (reviewers)

Rows are created inside `emit`'s transaction, together with one `notification.sent` event per recipient.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from actron.db import models as m

if TYPE_CHECKING:
    from actron.flow.events import Event

KINDS = ("needs_input", "awaiting_approval", "build_failed", "pr_ready")
TAB_FOR = {"needs_input": "questions", "awaiting_approval": "ticket", "build_failed": "build", "pr_ready": "pr"}


def kind_for(event_type: str, payload: dict[str, Any]) -> str | None:
    """The notification kind an event creates, or None for informational events."""
    if event_type == "question.asked":
        return "needs_input"
    if event_type == "ticket.synced":
        return "awaiting_approval"
    if event_type == "build.failed":
        return "build_failed"
    if event_type == "request.state_changed" and payload.get("to") == "Needs attention" and not payload.get("fromBuild"):
        return "build_failed"
    if event_type == "pr.opened":
        return "pr_ready"
    return None


def _copy(kind: str, payload: dict[str, Any], request: m.Request) -> tuple[str, str]:
    if kind == "needs_input":
        return "Actron needs your input", f"{request.title}: {payload.get('text', 'A question is waiting.')}"
    if kind == "awaiting_approval":
        n = payload.get("n")
        title = f"Ticket v{n} is ready for your approval" if n else "A ticket is ready for your approval"
        return title, request.title
    if kind == "build_failed":
        reason = payload.get("reason") or "The build stopped."
        return "This request needs your attention", f"{request.title}: {reason}"
    number = payload.get("number")
    return (f"PR #{number} is ready for review" if number else "A PR is ready for review"), request.title


def _approver_user_ids(session: Session, ws: str) -> list[uuid.UUID]:
    wsrow = session.get(m.Workspace, ws)
    approvers = [str(a) for a in ((wsrow.settings or {}).get("approvers") or [])] if wsrow else []
    if not approvers:
        return []
    rows = session.scalars(select(m.User.id).where(m.User.slack_user_id.in_(approvers))).all()
    return list(rows)


def create_for_event(session: Session, ev: Event) -> list[Event]:
    """Create notification rows for `ev` (if it is one of the four kinds) and their `notification.sent` events."""
    from actron.flow.events import insert_event

    kind = kind_for(ev.type, ev.payload)
    if kind is None or ev.request_id is None:
        return []
    request = session.get(m.Request, ev.request_id)
    if request is None:
        return []
    recipients: list[uuid.UUID | None] = [request.requester_user_id]
    if kind in ("awaiting_approval", "pr_ready"):
        recipients += _approver_user_ids(session, ev.workspace_id)
    unique: list[uuid.UUID | None] = []
    for r in recipients:
        if r not in unique:
            unique.append(r)
    title, body = _copy(kind, ev.payload, request)
    out: list[Event] = []
    for user_id in unique:
        # One unread notification per person, request and kind: several questions make one inbox item.
        dup = session.scalar(
            select(func.count()).select_from(m.Notification).where(
                m.Notification.request_id == request.id, m.Notification.kind == kind,
                m.Notification.read_at.is_(None),
                m.Notification.user_id.is_(None) if user_id is None else m.Notification.user_id == user_id,
            )
        )
        if dup:
            continue
        note = m.Notification(
            workspace_id=ev.workspace_id, user_id=user_id, request_id=request.id, kind=kind, title=title,
            body=body, tab=TAB_FOR[kind], created_at=datetime.now(UTC),
        )
        session.add(note)
        session.flush()
        out.append(insert_event(
            session, ev.workspace_id, request.id, "notification.sent",
            {"kind": kind, "toPersonId": None, "toUserId": str(user_id) if user_id else None, "channel": "ui",
             "notificationId": str(note.id), "title": title, "tab": TAB_FOR[kind]},
        ))
    return out


def view(row: m.Notification) -> dict[str, Any]:
    from actron.flow.events import iso

    return {
        "id": str(row.id), "kind": row.kind, "title": row.title, "body": row.body, "requestId": row.request_id,
        "tab": row.tab or TAB_FOR.get(row.kind, "evidence"), "readAt": iso(row.read_at), "createdAt": iso(row.created_at),
    }


def _visible(ws: str, user_id: uuid.UUID) -> Any:
    return (m.Notification.workspace_id == ws) & (
        (m.Notification.user_id == user_id) | m.Notification.user_id.is_(None)
    )


def list_for_user(session: Session, ws: str, user_id: uuid.UUID, *, unread_only: bool = False,
                  limit: int = 100) -> tuple[list[dict[str, Any]], int]:
    q = select(m.Notification).where(_visible(ws, user_id))
    if unread_only:
        q = q.where(m.Notification.read_at.is_(None))
    rows = session.scalars(q.order_by(m.Notification.created_at.desc()).limit(limit)).all()
    unread = session.scalar(
        select(func.count()).select_from(m.Notification).where(_visible(ws, user_id), m.Notification.read_at.is_(None))
    )
    return [view(r) for r in rows], int(unread or 0)


def mark_read(session: Session, ws: str, user_id: uuid.UUID, notification_id: uuid.UUID) -> int | None:
    """Mark one notification read. Returns the new unread count, or None when it is not visible to the user."""
    row = session.get(m.Notification, notification_id)
    if row is None or row.workspace_id != ws or (row.user_id is not None and row.user_id != user_id):
        return None
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    session.flush()
    unread = session.scalar(
        select(func.count()).select_from(m.Notification).where(_visible(ws, user_id), m.Notification.read_at.is_(None))
    )
    return int(unread or 0)
