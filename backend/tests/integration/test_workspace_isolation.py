"""A-AC-20: two workspaces write the same ids without interference; a store never returns the other's nodes."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from actron.graph import ids
from actron.graph.ontology import Ontology
from actron.graph.store import GraphStore, LinkRow

pytestmark = pytest.mark.integration


@pytest.fixture
def two(falkordb_url: str, ontology: Ontology) -> Iterator[tuple[GraphStore, GraphStore]]:
    tag = uuid.uuid4().hex[:8]
    a = GraphStore(falkordb_url, f"actron_test_a_{tag}", ontology, workspace_id=f"a-{tag}")
    b = GraphStore(falkordb_url, f"actron_test_b_{tag}", ontology, workspace_id=f"b-{tag}")
    yield a, b
    for s in (a, b):
        s.drop()
        s.close()


def row(i: int, text: str) -> dict[str, Any]:
    ts = f"{1700000000 + i}.000000"
    return {
        "id": ids.slack_msg("C1", ts),
        "text": text,
        "ts": ts,
        "channelId": "C1",
        "postedAt": "2026-10-17T10:00:00Z",
    }


def test_same_ids_do_not_interfere_a_ac_20(two: tuple[GraphStore, GraphStore]) -> None:
    """A-AC-20"""
    a, b = two
    a.upsert_nodes("SlackMessage", [row(i, "from A") for i in range(20)])
    b.upsert_nodes("SlackMessage", [row(i, "from B") for i in range(10)])
    assert a.count("SlackMessage") == 20
    assert b.count("SlackMessage") == 10
    a_node = a.get_node(row(3, "")["id"])
    b_node = b.get_node(row(3, "")["id"])
    assert (
        a_node is not None
        and a_node["text"] == "from A"
        and a_node["workspaceId"] == a.workspace_id
    )
    assert (
        b_node is not None
        and b_node["text"] == "from B"
        and b_node["workspaceId"] == b.workspace_id
    )


def test_query_through_store_a_never_returns_b_a_ac_20(two: tuple[GraphStore, GraphStore]) -> None:
    """A-AC-20"""
    a, b = two
    a.upsert_nodes("SlackMessage", [row(1, "A only")])
    b.upsert_nodes("SlackMessage", [row(2, "B only"), row(3, "B only")])
    texts = {r["t"] for r in a.query("MATCH (n:SlackMessage) RETURN n.text AS t", read_only=True)}
    assert texts == {"A only"}
    assert a.get_node(row(2, "")["id"]) is None
    assert {n["workspaceId"] for n in a.list_nodes("SlackMessage")} == {a.workspace_id}


def test_writes_to_one_graph_leave_the_other_untouched_a_ac_20(
    two: tuple[GraphStore, GraphStore],
) -> None:
    """A-AC-20: tombstones, links and deletes stay inside one graph."""
    a, b = two
    rows = [row(1, "x"), row(2, "x")]
    a.upsert_nodes("SlackMessage", rows)
    b.upsert_nodes("SlackMessage", rows)
    a.upsert_links(
        "PREVIOUS_VERSION",
        "SlackMessage",
        "SlackMessage",
        [LinkRow(rows[0]["id"], rows[1]["id"], {"method": "structural", "confidence": 1.0})],
    )
    a.tombstone("SlackMessage", [rows[0]["id"]])
    assert b.query("MATCH ()-[r]->() RETURN count(r) AS c", read_only=True)[0]["c"] == 0
    assert len(b.list_nodes("SlackMessage")) == 2
    assert len(a.list_nodes("SlackMessage")) == 1


def test_dropping_one_graph_keeps_the_other_a_ac_20(two: tuple[GraphStore, GraphStore]) -> None:
    """A-AC-20"""
    a, b = two
    a.upsert_nodes("SlackMessage", [row(1, "x")])
    b.upsert_nodes("SlackMessage", [row(1, "x")])
    a.drop()
    assert b.count("SlackMessage") == 1
    assert a.count("SlackMessage") == 0


def test_store_for_gives_one_graph_per_workspace_a_ac_20(falkordb_url: str) -> None:
    """A-AC-20: `store_for` maps a workspace id to its own graph name and caches the store."""
    from actron.graph.store import store_for

    s1 = store_for("iso-one")
    s2 = store_for("iso-two")
    assert store_for("iso-one") is s1
    assert s1.graph_name != s2.graph_name
    assert s1.graph_name == ids.graph_name("actron", "iso-one")
    assert s1.workspace_id == "iso-one"
