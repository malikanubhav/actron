"""Who may approve (spec B, B12a): requester, workspace owner, or a listed approver; others are refused (B-AC-84)."""

from __future__ import annotations

from typing import Any

import pytest

from actron.flow import service
from actron.flow.approvals import publish_outcome
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401


async def _awaiting(w6: W6Env, requester: str) -> str:  # noqa: F811
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(requester), source="ui",
                                        kind_hint="feature")
    service.set_request_fields(view["id"], state="Awaiting approval")
    return str(view["id"])


@pytest.fixture
def decide(gateway: FakeGateway) -> FakeGateway:  # noqa: F811
    async def on_signal(rid: str, name: str, payload: dict[str, Any]) -> None:
        await publish_outcome(rid, payload["idempotencyKey"], {"status": "accepted", "reason": None, "state": "Building"})

    gateway.on_signal = on_signal
    return gateway


@pytest.mark.parametrize("who", ["requester", "owner", "listed"])
async def test_allowed_approvers(w6: W6Env, decide: FakeGateway, who: str) -> None:  # noqa: F811
    """B-AC-84: the requester, the owner and a listed approver are accepted."""
    requester = w6.add_user("Requester")
    listed = w6.add_user("Listed", slack_user_id="ULISTED")
    w6.set_settings(approvers=["ULISTED"])
    rid = await _awaiting(w6, requester)
    actor = {"requester": w6.actor(requester), "owner": w6.actor(), "listed": w6.actor(listed)}[who]
    res = await service.approve(w6.ws, rid, "ticket", "h" * 64, actor, f"k-{who}")
    assert res["status"] == "accepted"
    assert decide.signals[-1][1] == "approve_ticket"


async def test_slack_listed_approver(w6: W6Env, decide: FakeGateway) -> None:  # noqa: F811
    """B-AC-84: a listed approver acting from Slack (by Slack user id) is accepted."""
    requester = w6.add_user("Requester")
    w6.set_settings(approvers=["USLACKAPP"])
    rid = await _awaiting(w6, requester)
    actor = service.Actor(slack_user_id="USLACKAPP", surface="slack", name="Ana")
    assert (await service.approve(w6.ws, rid, "ticket", "h" * 64, actor, "slack-a"))["status"] == "accepted"


async def test_other_member_refused(w6: W6Env, decide: FakeGateway) -> None:  # noqa: F811
    """B-AC-84: anyone else is refused with not_an_approver and `approval.refused` is recorded."""
    requester = w6.add_user("Requester")
    other = w6.add_user("Other", slack_user_id="UOTHER")
    w6.set_settings(approvers=["ULISTED"])
    rid = await _awaiting(w6, requester)
    with pytest.raises(service.Forbidden) as exc:
        await service.approve(w6.ws, rid, "ticket", "h" * 64, w6.actor(other), "k-other")
    assert exc.value.code == "not_an_approver"
    assert w6.types(rid)[-1] == "approval.refused"
    assert not decide.signals
