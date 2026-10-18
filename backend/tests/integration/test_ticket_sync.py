"""Ticket revisions and Linear sync (spec B, B7): B-AC-33 (marker and JSON block round-trip), B-AC-34 (external
edit refuses approval), B-AC-35 (Linear not connected)."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from actron.activities import request as acts
from actron.flow import service
from actron.flow.ticket import parse_description, ticket_hash
from tests.api._fixtures import FakeGateway, W6Env, gateway, stack, w6  # noqa: F401
from tests.api._wf_harness import wait_db_state


class FakeLinear:
    issues: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def issue_create(self, *, issue_id: str, team_id: str, title: str, description: str) -> dict[str, Any]:
        n = len(self.issues) + 1
        self.issues[issue_id] = {"id": issue_id, "identifier": f"ENG-{n}", "url": f"https://linear.test/ENG-{n}",
                                 "title": title, "description": description}
        return self.issues[issue_id]

    async def issue_update(self, issue_id: str, *, title: str | None = None,
                           description: str | None = None) -> dict[str, Any]:
        issue = self.issues[issue_id]
        issue.update({k: v for k, v in {"title": title, "description": description}.items() if v is not None})
        return issue

    async def issue(self, issue_id: str) -> dict[str, Any] | None:
        return self.issues.get(issue_id)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def linear(monkeypatch: pytest.MonkeyPatch) -> type[FakeLinear]:
    FakeLinear.issues = {}
    monkeypatch.setattr(acts, "_linear_cfg", lambda ws: {"token": "lin_api_test", "team": "TEAM1"})
    monkeypatch.setattr(acts, "_linear_client", lambda cfg: FakeLinear())
    return FakeLinear


async def _awaiting(w6: W6Env) -> str:  # noqa: F811
    view = await service.create_request(w6.ws, text="Add CSV export, merge into main", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    await wait_db_state(w6.ws, view["id"], "Awaiting approval")
    return str(view["id"])


async def test_revision_synced_with_marker(w6: W6Env, stack: Any, linear: type[FakeLinear]) -> None:  # noqa: F811
    """B-AC-33: revisions increment; the description has the marker and JSON block; parsing gives the same hash."""
    rid = await _awaiting(w6)
    detail = await service.get_request_view(w6.ws, rid)
    rev = detail["revisions"][0]
    assert rev["n"] == 1 and rev["linear"]["identifier"] == "ENG-1"
    issue = next(iter(linear.issues.values()))
    parsed = parse_description(issue["description"])
    assert parsed is not None and parsed.revision == 1 and parsed.marker_hash == rev["hash"] == parsed.computed_hash
    await service.edit_ticket(w6.ws, rid, {"objective": "Export for admins", "targetBranch": "main"}, w6.actor(), "e1")
    detail = await service.get_request_view(w6.ws, rid)
    assert [r["n"] for r in detail["revisions"]] == [1, 2]
    parsed = parse_description(next(iter(linear.issues.values()))["description"])
    assert parsed is not None and parsed.revision == 2 and parsed.marker_hash == detail["revisions"][1]["hash"]
    assert len(linear.issues) == 1
    synced = [e for e in w6.events(rid) if e.type == "ticket.synced"]
    assert [e.payload["identifier"] for e in synced] == ["ENG-1", "ENG-1"]


async def test_external_edit_blocks_approval(w6: W6Env, stack: Any, linear: type[FakeLinear]) -> None:  # noqa: F811
    """B-AC-34: an edit made in Linear before approval -> refused with external_edit, new revision required."""
    rid = await _awaiting(w6)
    issue = next(iter(linear.issues.values()))
    issue["description"] = issue["description"].replace("Add CSV export", "Add PDF export")
    h = (await service.get_request_view(w6.ws, rid))["currentRevision"]["hash"]
    res = await service.approve(w6.ws, rid, "ticket", h, w6.actor(), "x1")
    assert res["status"] == "refused" and res["reason"] == "external_edit"
    detail = await service.get_request_view(w6.ws, rid)
    assert detail["revisions"][0]["externalEdit"] is True and detail["state"] == "Awaiting approval"
    await service.edit_ticket(w6.ws, rid, {"objective": "Add PDF export", "targetBranch": "main"}, w6.actor(), "x2")
    h2 = (await service.get_request_view(w6.ws, rid))["currentRevision"]["hash"]
    ok = await service.approve(w6.ws, rid, "ticket", h2, w6.actor(), "x3")
    assert ok["status"] == "accepted"


async def test_linear_not_connected(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-35: without Linear the ticket is stored, the event says so, and approval still works."""
    rid = await _awaiting(w6)
    synced = [e for e in w6.events(rid) if e.type == "ticket.synced"]
    assert synced[0].payload["reason"] == "Linear not connected" and synced[0].payload["skipped"] is True
    detail = await service.get_request_view(w6.ws, rid)
    rev = detail["revisions"][0]
    assert rev["linear"] is None
    assert rev["hash"] == ticket_hash({**rev["content"], "requestId": rid})
    res = await service.approve(w6.ws, rid, "ticket", rev["hash"], w6.actor(), "nl-1")
    assert res["status"] == "accepted"
