# ruff: noqa: F403
"""Linear writes and external-edit detection: A-AC-60, A-AC-61 (A-AC-60 repeated end to end through the writer)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from actron.connectors import linear
from actron.integrations.linear_client import LinearClient, deterministic_issue_id
from tests.fakes.linear import FakeLinear, build_team_fixture
from tests.fakes.support import *

TICKET = {"title": "Retry on 429", "acceptanceCriteria": ["backs off", "gives up after 8 tries"],
          "targetBranch": "main", "requestId": "req_1", "revision": 2}


def render(ticket: dict[str, Any], rev: int | None = None) -> str:
    digest = linear.ticket_hash(ticket)
    block = linear.canonical_ticket_json(ticket)
    return (f"## {ticket['title']}\n\nBackoff matters.\n\n<!-- actron:ticket sha256={digest} rev={rev or ticket['revision']} -->\n"
            f"```json\n{block}\n```\n")


def test_canonical_hash_ignores_revision_and_key_order() -> None:
    a = linear.ticket_hash(TICKET)
    reordered = {k: TICKET[k] for k in reversed(list(TICKET))}
    assert a == linear.ticket_hash(reordered) == linear.ticket_hash({**TICKET, "revision": 9})
    assert a != linear.ticket_hash({**TICKET, "title": "other"})


def test_a_ac_61_untouched_description_is_not_flagged() -> None:
    """A-AC-61"""
    result = linear.detect_external_edit(render(TICKET), linear.ticket_hash(TICKET))
    assert not result.edited and result.revision == 2


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d.replace("Backoff matters.", "Someone typed here. Backoff matters."), None),  # prose outside the block
    (lambda d: d.replace("backs off", "does whatever"), "no longer matches"),
    (lambda d: d.replace("```json", "```text"), "JSON block is missing"),
    (lambda d: d.split("<!--")[0], "marker is missing"),
    (lambda d: d.replace("{", "{{", 1).replace('"title"', '"ti tle"', 1), None),
])
def test_a_ac_61_edits_inside_the_marker_or_block_are_detected(mutate: Any, reason: str | None) -> None:
    edited = mutate(render(TICKET))
    result = linear.detect_external_edit(edited, linear.ticket_hash(TICKET))
    if reason is None and "Someone typed" in edited:
        assert not result.edited  # rendered markdown may change; the hashed block did not
    else:
        assert result.edited and (reason is None or reason in (result.reason or ""))


def test_a_ac_61_hash_mismatch_with_expected_revision_is_reported() -> None:
    newer = {**TICKET, "title": "Revised title"}
    result = linear.detect_external_edit(render(newer), linear.ticket_hash(TICKET))
    assert result.edited and "differs from the approved revision" in (result.reason or "")
    assert linear.detect_external_edit(None, "x").edited
    assert linear.detect_external_edit("", "x").reason == "the ticket marker is missing"


def test_a_ac_61_block_with_forged_marker_hash_is_detected() -> None:
    forged = render(TICKET).replace(linear.ticket_hash(TICKET), "0" * 64)
    result = linear.detect_external_edit(forged, linear.ticket_hash(TICKET))
    assert result.edited and "no longer matches its hash" in (result.reason or "")
    bad_json = render(TICKET).replace('"targetBranch":"main"', '"targetBranch":')
    assert linear.detect_external_edit(bad_json, linear.ticket_hash(TICKET)).edited


async def test_a_ac_60_write_flow_create_update_comment_then_read_back_hash(fake_linear: FakeLinear) -> None:
    """A-AC-60 plus A-AC-61 end to end: create with the canonical block, an outside edit is then caught."""
    build_team_fixture(fake_linear)
    iid = deterministic_issue_id("acme", "req_1")
    expected = linear.ticket_hash(TICKET)
    async with LinearClient("lin_api_test", base_url="http://fake.linear/graphql",
                            transport=fake_linear.transport()) as c:
        fake_linear.lose_next_create_answer = True
        created = await c.issue_create(issue_id=iid, team_id="t1", title=TICKET["title"], description=render(TICKET),
                                       label_ids=["l2"])
        assert created["id"] == iid and fake_linear.created_ids == [iid]
        stored = await c.issue(iid)
        assert stored is not None
        assert not linear.detect_external_edit(stored["description"], expected).edited
        await c.issue_update(iid, description=stored["description"].replace("backs off", "does anything"))
        after = await c.issue(iid)
    assert after is not None and linear.detect_external_edit(after["description"], expected).edited
    assert json.loads(fake_linear.issues[iid]["description"].split("```json\n")[1].split("\n```")[0])["requestId"] == "req_1"
