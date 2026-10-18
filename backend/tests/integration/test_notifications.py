"""Notifications (spec B, B13): only four kinds interrupt (B-AC-62); marking read updates the count (B-AC-63)."""

from __future__ import annotations

import uuid

import pytest

from actron.db.session import session_scope
from actron.flow import notifications, service
from actron.flow.events import emit, load_workspace_events
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401

INFORMATIONAL = [
    ("request.state_changed", {"from": "Investigating", "to": "Ticket ready"}),
    ("tool.called", {"callId": "c", "tool": "search", "args": {}, "by": "investigator"}),
    ("evidence.found", {"evidenceId": "e"}),
    ("ticket.revised", {"n": 1, "hash": "h"}),
    ("build.step", {"text": "Editing"}),
    ("tests.result", {"passed": 1, "failed": 0}),
    ("writeback.done", {"counts": {}}),
    ("request.done", {"outcome": "approved"}),
    ("approval.recorded", {"kind": "ticket"}),
    ("request.state_changed", {"from": "Building", "to": "Needs attention", "fromBuild": True}),
]
INTERRUPTING = [
    ("question.asked", {"questionId": "q1", "text": "Keep?"}, "needs_input"),
    ("ticket.synced", {"n": 1, "identifier": "ENG-1"}, "awaiting_approval"),
    ("build.failed", {"buildId": "b", "reason": "timeout"}, "build_failed"),
    ("request.state_changed", {"from": "Investigating", "to": "Needs attention", "reason": "memory_stale"},
     "build_failed"),
    ("pr.opened", {"number": 4, "url": "u", "headSha": "h"}, "pr_ready"),
]


async def _req(w6: W6Env) -> str:  # noqa: F811
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    return str(view["id"])


def _list(w6: W6Env, user_id: str) -> tuple[list[dict[str, object]], int]:  # noqa: F811
    with session_scope() as s:
        return notifications.list_for_user(s, w6.ws, uuid.UUID(user_id))


@pytest.mark.parametrize(("etype", "payload"), INFORMATIONAL)
async def test_informational_events_do_not_notify(w6: W6Env, etype: str, payload: dict[str, object]) -> None:  # noqa: F811
    """B-AC-62: informational events create no notification."""
    rid = await _req(w6)
    await emit(w6.ws, rid, etype, payload)
    assert _list(w6, w6.owner_id) == ([], 0)
    assert "notification.sent" not in w6.types(rid)


@pytest.mark.parametrize(("etype", "payload", "kind"), INTERRUPTING)
async def test_interrupting_events_notify(w6: W6Env, etype: str, payload: dict[str, object], kind: str) -> None:  # noqa: F811
    """B-AC-62: exactly the four kinds notify the requester, with a `notification.sent` event."""
    rid = await _req(w6)
    await emit(w6.ws, rid, etype, payload)
    items, unread = _list(w6, w6.owner_id)
    assert unread == 1 and items[0]["kind"] == kind and items[0]["requestId"] == rid
    assert items[0]["tab"] == notifications.TAB_FOR[kind]
    assert w6.types(rid)[-1] == "notification.sent"


async def test_approvers_notified_for_approval_and_pr(w6: W6Env) -> None:  # noqa: F811
    """B13: ticket approval and PR review also go to the configured approvers."""
    approver = w6.add_user("Approver", slack_user_id="UAPP")
    w6.set_settings(approvers=["UAPP"])
    rid = await _req(w6)
    await emit(w6.ws, rid, "ticket.synced", {"n": 1})
    await emit(w6.ws, rid, "question.asked", {"questionId": "q", "text": "?"})
    assert [i["kind"] for i in _list(w6, approver)[0]] == ["awaiting_approval"]
    assert _list(w6, w6.owner_id)[1] == 2


async def test_one_unread_per_kind_and_request(w6: W6Env) -> None:  # noqa: F811
    """B13: three questions make one inbox item, not three."""
    rid = await _req(w6)
    for i in range(3):
        await emit(w6.ws, rid, "question.asked", {"questionId": f"q{i}", "text": "?"})
    assert _list(w6, w6.owner_id)[1] == 1


async def test_mark_read_updates_count_live(w6: W6Env) -> None:  # noqa: F811
    """B-AC-63: marking read lowers the unread count and publishes `notification.read` on the workspace stream."""
    from actron.api.routes.notifications import mark_read_and_publish

    rid = await _req(w6)
    await emit(w6.ws, rid, "pr.opened", {"number": 1})
    items, unread = _list(w6, w6.owner_id)
    assert unread == 1
    count = await mark_read_and_publish(w6.ws, uuid.UUID(w6.owner_id), uuid.UUID(str(items[0]["id"])))
    assert count == 0
    assert _list(w6, w6.owner_id)[1] == 0
    last = load_workspace_events(w6.ws)[-1]
    assert last.type == "notification.read" and last.payload == {"notificationId": items[0]["id"], "unread": 0,
                                                                  "userId": w6.owner_id}
