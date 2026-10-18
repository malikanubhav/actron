# ruff: noqa: F403
"""Live Slack events: A-AC-51 (edit versions, delete tombstones), new messages, renames, joins."""

from __future__ import annotations

from typing import Any

from actron.connectors import slack
from actron.graph import ids
from actron.graph.store import LinkRow
from tests.fakes.support import *

WORKSPACE = {"id": "T0001", "domain": "northwind", "bot_user_id": "UBOT"}


def _rows(store: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    return store.query(cypher, params, read_only=True)


def _channel(store: Any) -> None:
    store.upsert_nodes("SlackChannel", [{"id": ids.slack_channel("C1"), "name": "eng"}])


async def _post(ws: str, ts: str = "1760000001.000100", text: str = "We decided to retry.", **extra: Any) -> Any:
    event = {"type": "message", "channel": "C1", "user": "U1", "text": text, "ts": ts, **extra}
    return await slack.handle_message_event(ws, event, workspace=WORKSPACE)


async def test_new_message_event_upserts_and_enqueues_linking(store: Any, ws: str) -> None:
    _channel(store)
    enqueued: list[tuple[str, list[str]]] = []

    async def enqueue(w: str, changed: list[str]) -> None:
        enqueued.append((w, changed))

    event = {"type": "message", "channel": "C1", "user": "U1", "text": "hello", "ts": "1760000001.000100"}
    out = await slack.handle_message_event(ws, event, workspace=WORKSPACE, enqueue=enqueue)
    mid = ids.slack_msg("C1", "1760000001.000100")
    assert out.kind == "new" and out.changed_ids == [mid]
    assert enqueued == [(ws, [mid])]
    node = store.get_node(mid)
    assert node["text"] == "hello" and node["version"] == 1
    assert node["permalink"] == "https://northwind.slack.com/archives/C1/p1760000001000100"
    again = await slack.handle_message_event(ws, event, workspace=WORKSPACE, enqueue=enqueue)
    assert again.kind == "ignored" and len(enqueued) == 1  # the same delivery twice changes nothing


async def test_a_ac_51_message_changed_creates_previous_version(store: Any, ws: str) -> None:
    """A-AC-51: message_changed keeps the old text as @v1 and updates the main node."""
    _channel(store)
    await _post(ws)
    mid = ids.slack_msg("C1", "1760000001.000100")
    changed = {"type": "message", "subtype": "message_changed", "channel": "C1", "ts": "1760000050.000200",
               "message": {"type": "message", "user": "U1", "text": "We decided to retry twice.",
                           "ts": "1760000001.000100", "edited": {"user": "U1", "ts": "1760000050.000200"}},
               "previous_message": {"text": "We decided to retry.", "ts": "1760000001.000100"}}
    out = await slack.handle_message_event(ws, changed, workspace=WORKSPACE)
    assert out.kind == "edited" and out.version == 2
    node = store.get_node(mid)
    assert node["text"] == "We decided to retry twice." and node["version"] == 2 and node["edited"] is True
    old = store.get_node(mid + "@v1")
    assert old["text"] == "We decided to retry."
    assert _rows(store, "MATCH (a:SlackMessage {id: $id})-[:PREVIOUS_VERSION]->(b:SlackMessage) RETURN b.id AS id",
                 id=mid) == [{"id": mid + "@v1"}]
    # a second edit creates @v2
    changed["message"]["text"] = "Final wording."
    changed["message"]["edited"]["ts"] = "1760000090.000300"
    changed["ts"] = "1760000090.000300"
    await slack.handle_message_event(ws, changed, workspace=WORKSPACE)
    assert store.get_node(mid)["version"] == 3 and store.get_node(mid + "@v2")["text"] == "We decided to retry twice."
    # delivering the same edit again does not add a version
    await slack.handle_message_event(ws, changed, workspace=WORKSPACE)
    assert store.get_node(mid)["version"] == 3 and store.get_node(mid + "@v3") is None


async def test_a_ac_51_message_deleted_tombstones_and_removes_reference_links(store: Any, ws: str) -> None:
    """A-AC-51: message_deleted tombstones the message and its outgoing reference links, keeping an audit list."""
    _channel(store)
    await _post(ws)
    mid = ids.slack_msg("C1", "1760000001.000100")
    store.upsert_nodes("Reference", [{"id": "actron:ref:linear_issue:ENG-1", "kind": "linear_issue", "key": "ENG-1",
                                      "rawText": "ENG-1", "status": "pending"}])
    store.upsert_nodes("GithubPullRequest", [{"id": ids.github_pr("a/b", 1), "number": 1, "title": "t",
                                             "state": "open", "createdAt": "2026-01-01T00:00:00Z",
                                             "updatedAt": "2026-01-01T00:00:00Z", "url": "u"}])
    store.upsert_links("CONTAINS_REFERENCE", "SlackMessage", "Reference", [LinkRow(
        mid, "actron:ref:linear_issue:ENG-1", {"method": "explicit", "confidence": 1.0})])
    store.upsert_links("MENTIONS", "SlackMessage", "GithubPullRequest", [LinkRow(
        mid, ids.github_pr("a/b", 1), {"method": "explicit", "confidence": 1.0})])
    event = {"type": "message", "subtype": "message_deleted", "channel": "C1", "deleted_ts": "1760000001.000100",
             "previous_message": {"ts": "1760000001.000100"}}
    out = await slack.handle_message_event(ws, event, workspace=WORKSPACE)
    assert out.kind == "deleted"
    assert {(r["rel"], r["target"]) for r in out.removed_links} == {
        ("CONTAINS_REFERENCE", "actron:ref:linear_issue:ENG-1"), ("MENTIONS", ids.github_pr("a/b", 1))}
    node = store.get_node(mid)
    assert node["deleted"] is True and node["deletedAt"]
    live = _rows(store, "MATCH (m:SlackMessage {id: $id})-[r:MENTIONS|CONTAINS_REFERENCE]->() "
                 "WHERE coalesce(r.deleted, false) = false RETURN count(r) AS c", id=mid)
    assert live[0]["c"] == 0
    audit = _rows(store, "MATCH (m:SlackMessage {id: $id})-[r:MENTIONS|CONTAINS_REFERENCE]->() "
                  "RETURN count(r) AS c", id=mid)
    assert audit[0]["c"] == 2  # kept for history, flagged deleted
    # the deletion is recorded in the workspace event journal
    from sqlalchemy import select

    from actron.db.models import Event
    from actron.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(select(Event).where(Event.workspace_id == ws, Event.type == "slack.message_deleted")
                               ).scalars().all()
        assert len(rows) == 1 and rows[0].request_id is None
        assert len(rows[0].payload["removedLinks"]) == 2
    # deleting something never ingested is ignored
    ghost = dict(event, deleted_ts="1760000999.000000")
    assert (await slack.handle_message_event(ws, ghost, workspace=WORKSPACE)).kind == "ignored"


async def test_edit_of_a_message_not_yet_ingested_creates_it(store: Any, ws: str) -> None:
    _channel(store)
    changed = {"type": "message", "subtype": "message_changed", "channel": "C1",
               "message": {"user": "U1", "text": "late edit", "ts": "1760000007.000100",
                           "edited": {"user": "U1", "ts": "1760000008.000100"}}}
    out = await slack.handle_message_event(ws, changed, workspace=WORKSPACE)
    assert out.kind == "edited"
    assert store.get_node(ids.slack_msg("C1", "1760000007.000100"))["text"] == "late edit"


async def test_channel_rename_and_member_joined(store: Any, ws: str) -> None:
    _channel(store)
    out = await slack.handle_message_event(ws, {"type": "channel_rename", "channel": {"id": "C1", "name": "platform"}},
                                           workspace=WORKSPACE)
    assert out.kind == "renamed" and store.get_node(ids.slack_channel("C1"))["name"] == "platform"
    out = await slack.handle_message_event(ws, {"type": "member_joined_channel", "user": "U7", "channel": "C1"},
                                           workspace=WORKSPACE)
    assert out.kind == "joined"
    rows = _rows(store, "MATCH (u:SlackUser)-[:RELATED_TO_CHANNEL]->(c:SlackChannel) RETURN u.id AS u, c.id AS c")
    assert rows == [{"u": "slack:user:U7", "c": "slack:channel:C1"}]
    # a real name stored earlier is not overwritten by a join event
    store.upsert_nodes("SlackUser", [{"id": ids.slack_user("U8"), "name": "hana"}])
    await slack.handle_message_event(ws, {"type": "member_joined_channel", "user": "U8", "channel": "C1"},
                                     workspace=WORKSPACE)
    assert store.get_node(ids.slack_user("U8"))["name"] == "hana"


async def test_join_leave_and_unknown_events_are_ignored(store: Any, ws: str) -> None:
    _channel(store)
    out = await slack.handle_message_event(ws, {"type": "message", "subtype": "channel_join", "channel": "C1",
                                               "user": "U1", "ts": "1760000003.000100", "text": "joined"},
                                           workspace=WORKSPACE)
    assert out.kind == "ignored"
    assert (await slack.handle_message_event(ws, {"type": "reaction_added"}, workspace=WORKSPACE)).kind == "ignored"
