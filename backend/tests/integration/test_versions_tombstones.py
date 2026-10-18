"""A-AC-18 (edit versions), A-AC-19 (tombstones and the shared filter)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from actron.graph import ids
from actron.graph.store import GraphStore, InvalidName, LinkRow, not_deleted
from actron.graph.versions import (
    NodeNotFound,
    is_version_id,
    version_linear_comment,
    version_linear_issue,
    version_slack_message,
)

pytestmark = pytest.mark.integration

MSG = ids.slack_msg("C1", "1712345678.000100")


def slack(text: str = "first") -> dict[str, Any]:
    return {
        "id": MSG,
        "text": text,
        "ts": "1712345678.000100",
        "channelId": "C1",
        "postedAt": "2026-10-17T10:00:00Z",
        "userId": "U1",
    }


def prev_edges(g: GraphStore) -> list[tuple[str, str]]:
    rows = g.query(
        "MATCH (a)-[r:PREVIOUS_VERSION]->(b) RETURN a.id AS a, b.id AS b ORDER BY a.id",
        read_only=True,
    )
    return [(r["a"], r["b"]) for r in rows]


def test_first_edit_creates_v1_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18"""
    graph.upsert_nodes("SlackMessage", [slack("original text")])
    new_version = version_slack_message(
        graph, MSG, {"text": "edited text", "editedAt": "2026-10-17T11:00:00Z"}
    )
    assert new_version == 2
    old = graph.get_node(f"{MSG}@v1")
    assert old is not None
    assert old["text"] == "original text"
    assert old["version"] == 1
    assert old["userId"] == "U1"
    main = graph.get_node(MSG)
    assert main is not None
    assert main["text"] == "edited text"
    assert main["version"] == 2
    assert main["edited"] is True
    assert main["editedAt"] == "2026-10-17T11:00:00Z"
    assert prev_edges(graph) == [(MSG, f"{MSG}@v1")]


def test_second_edit_creates_v2_and_chains_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18"""
    graph.upsert_nodes("SlackMessage", [slack("one")])
    version_slack_message(graph, MSG, {"text": "two"})
    assert version_slack_message(graph, MSG, {"text": "three"}) == 3
    assert graph.get_node(f"{MSG}@v1")["text"] == "one"  # type: ignore[index]
    assert graph.get_node(f"{MSG}@v2")["text"] == "two"  # type: ignore[index]
    assert graph.get_node(f"{MSG}@v2")["version"] == 2  # type: ignore[index]
    main = graph.get_node(MSG)
    assert main is not None and main["text"] == "three" and main["version"] == 3
    assert prev_edges(graph) == sorted([(MSG, f"{MSG}@v2"), (f"{MSG}@v2", f"{MSG}@v1")])


def test_many_edits_keep_one_chain_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18"""
    graph.upsert_nodes("SlackMessage", [slack("t0")])
    for i in range(1, 6):
        version_slack_message(graph, MSG, {"text": f"t{i}"})
    main = graph.get_node(MSG)
    assert main is not None and main["version"] == 6 and main["text"] == "t5"
    assert graph.count("SlackMessage") == 6
    out_of_main = graph.query(
        f"MATCH ({{id: '{MSG}'}})-[r:PREVIOUS_VERSION]->() RETURN count(r) AS c", read_only=True
    )
    assert out_of_main[0]["c"] == 1
    assert [graph.get_node(f"{MSG}@v{n}")["text"] for n in range(1, 6)] == [
        f"t{n - 1}" for n in range(1, 6)
    ]  # type: ignore[index]


def test_history_copies_are_hidden_from_list_by_default_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18"""
    graph.upsert_nodes("SlackMessage", [slack("a")])
    version_slack_message(graph, MSG, {"text": "b"})
    assert [n["id"] for n in graph.list_nodes("SlackMessage")] == [MSG]
    assert len(graph.list_nodes("SlackMessage", include_versions=True)) == 2


def test_edit_of_missing_message_raises(graph: GraphStore) -> None:
    with pytest.raises(NodeNotFound):
        version_slack_message(graph, ids.slack_msg("C1", "9.9"), {"text": "x"})


def test_wrong_label_rejected(graph: GraphStore) -> None:
    with pytest.raises(ValueError):
        version_slack_message(graph, ids.code_file("a/b", "x.py"), {})
    with pytest.raises(ValueError):
        version_linear_issue(graph, MSG, {})
    with pytest.raises(ValueError):
        version_linear_comment(graph, MSG, {})


def test_is_version_id() -> None:
    assert is_version_id(f"{MSG}@v3")
    assert not is_version_id(MSG)
    assert not is_version_id("code:fn:a/b:x.py::f@vx")


def test_linear_issue_versions_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18 (Linear equivalent: issues keep previous title and description)."""
    iid = ids.linear_issue("11111111-1111-1111-1111-111111111111")
    graph.upsert_nodes(
        "LinearIssue",
        [
            {
                "id": iid,
                "title": "Old title",
                "description": "old",
                "url": "https://l/1",
                "identifier": "ENG-1",
            }
        ],
    )
    assert version_linear_issue(graph, iid, {"title": "New title", "description": "new"}) == 2
    old = graph.get_node(f"{iid}@v1")
    assert old is not None and old["title"] == "Old title" and old["description"] == "old"
    main = graph.get_node(iid)
    assert main is not None and main["title"] == "New title" and main["version"] == 2
    rows = graph.query(
        "MATCH (a)-[r:ISSUE_PREVIOUS_VERSION]->(b) RETURN a.id AS a, b.id AS b", read_only=True
    )
    assert rows == [{"a": iid, "b": f"{iid}@v1"}]
    version_linear_issue(graph, iid, {"title": "Third"})
    assert graph.get_node(f"{iid}@v2")["title"] == "New title"  # type: ignore[index]


def test_linear_comment_versions_a_ac_18(graph: GraphStore) -> None:
    """A-AC-18"""
    cid = ids.linear_comment("22222222-2222-2222-2222-222222222222")
    graph.upsert_nodes("LinearComment", [{"id": cid, "body": "before", "issueId": "x"}])
    assert version_linear_comment(graph, cid, {"body": "after"}) == 2
    assert graph.get_node(f"{cid}@v1")["body"] == "before"  # type: ignore[index]
    assert graph.get_node(cid)["body"] == "after"  # type: ignore[index]
    rows = graph.query(
        "MATCH (a)-[r:COMMENT_PREVIOUS_VERSION]->(b) RETURN count(r) AS c", read_only=True
    )
    assert rows[0]["c"] == 1


# A-AC-19
def seed(graph: GraphStore) -> list[str]:
    rows = [
        {
            "id": ids.slack_msg("C1", f"{i}.000000"),
            "text": f"m{i}",
            "ts": f"{i}.000000",
            "channelId": "C1",
            "postedAt": "2026-10-17T10:00:00Z",
        }
        for i in range(1, 6)
    ]
    graph.upsert_nodes("SlackMessage", rows)
    return [r["id"] for r in rows]


def test_tombstone_marks_nodes_a_ac_19(graph: GraphStore) -> None:
    """A-AC-19"""
    node_ids = seed(graph)
    at = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    assert graph.tombstone("SlackMessage", node_ids[:2], at) == 2
    node = graph.get_node(node_ids[0])
    assert node is not None
    assert node["deleted"] is True
    assert node["deletedAt"] == "2026-10-17T12:00:00Z"
    other = graph.get_node(node_ids[4])
    assert other is not None and "deleted" not in other


def test_shared_helpers_exclude_tombstones_by_default_a_ac_19(graph: GraphStore) -> None:
    """A-AC-19"""
    node_ids = seed(graph)
    graph.tombstone("SlackMessage", node_ids[:2])
    assert {n["id"] for n in graph.list_nodes("SlackMessage")} == set(node_ids[2:])
    assert {n["id"] for n in graph.list_nodes("SlackMessage", include_deleted=True)} == set(
        node_ids
    )
    q = f"MATCH (n:SlackMessage) WHERE {not_deleted('n')} RETURN count(n) AS c"
    assert graph.query(q, read_only=True)[0]["c"] == 3
    q_all = f"MATCH (n:SlackMessage) WHERE {not_deleted('n', include_deleted=True)} RETURN count(n) AS c"
    assert graph.query(q_all, read_only=True)[0]["c"] == 5


def test_links_from_tombstoned_nodes_remain_a_ac_19(graph: GraphStore) -> None:
    """A-AC-19"""
    a, b, *_ = seed(graph)
    graph.upsert_links(
        "PREVIOUS_VERSION",
        "SlackMessage",
        "SlackMessage",
        [LinkRow(a, b, {"method": "structural", "confidence": 1.0})],
    )
    graph.tombstone("SlackMessage", [a])
    rows = graph.query(
        "MATCH (x {id: $a})-[r:PREVIOUS_VERSION]->(y) RETURN y.id AS y", {"a": a}, read_only=True
    )
    assert rows == [{"y": b}]


def test_tombstone_is_idempotent_and_ignores_unknown_ids_a_ac_19(graph: GraphStore) -> None:
    """A-AC-19"""
    node_ids = seed(graph)
    assert graph.tombstone("SlackMessage", [node_ids[0], "slack:msg:C9:9.0"]) == 1
    assert graph.tombstone("SlackMessage", [node_ids[0]]) == 1
    assert len(graph.list_nodes("SlackMessage")) == 4


def test_a_live_upsert_does_not_resurrect_silently_but_can_clear(graph: GraphStore) -> None:
    """A re-sync that sees the record again clears the tombstone by writing deleted=false."""
    node_ids = seed(graph)
    graph.tombstone("SlackMessage", node_ids[:1])
    graph.upsert_nodes("SlackMessage", [{"id": node_ids[0], "deleted": False}], partial=True)
    assert len(graph.list_nodes("SlackMessage")) == 5


def test_alias_must_be_safe() -> None:
    with pytest.raises(InvalidName):
        not_deleted("n) OR (true")
