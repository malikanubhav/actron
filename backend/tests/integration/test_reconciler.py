"""Reconciler (spec B, B1): signals that failed after commit are re-sent and applied once (B-AC-5)."""

from __future__ import annotations

from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import service
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401


async def test_failed_signal_resent_once(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-5: the action stays `pending` when signalling fails; the reconciler re-sends it once."""
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    rid = view["id"]
    gateway.fail_signals = 1
    res = await service.cancel(w6.ws, rid, "stop", w6.actor(), "rec-1")
    assert res["status"] == "accepted"
    ev = w6.events(rid)[-1]
    assert ev.signal_status == "pending"
    assert not gateway.signals
    fixed = await service.reconcile_once(older_than_s=0)
    assert fixed >= 1
    assert [(s[0], s[1], s[2]["idempotencyKey"]) for s in gateway.signals] == [(rid, "cancel", "rec-1")]
    assert w6.events(rid)[-1].signal_status == "sent"
    await service.reconcile_once(older_than_s=0)
    assert len(gateway.signals) == 1


async def test_unstarted_workflow_started(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: a request whose workflow failed to start is started by the reconciler."""
    gateway.fail_start = True
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    gateway.fail_start = False
    await service.reconcile_once(older_than_s=0)
    assert [s[1] for s in gateway.started] == [view["id"]]
    with session_scope() as s:
        row = s.get(m.Request, view["id"])
        assert row is not None and row.data["workflowStarted"] is True
