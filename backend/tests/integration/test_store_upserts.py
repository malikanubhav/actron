"""A-AC-16, A-AC-17, A-AC-21, A-AC-22 and the basics of the graph store, in both binding modes."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from actron.graph import ids
from actron.graph.ontology import Ontology, OntologyViolation
from actron.graph.store import GraphError, GraphStore, GraphTimeout, InvalidName, LinkRow

pytestmark = pytest.mark.integration


@pytest.fixture(params=["params", "literal"])
def store(
    request: pytest.FixtureRequest, falkordb_url: str, ontology: Ontology
) -> Iterator[GraphStore]:
    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    s = GraphStore(falkordb_url, name, ontology, workspace_id=name, binding=request.param)
    try:
        yield s
    finally:
        s.drop()
        s.close()


def msg(i: int, text: str = "hello", channel: str = "C1") -> dict[str, Any]:
    ts = f"{1700000000 + i}.{i % 1000000:06d}"
    return {
        "id": ids.slack_msg(channel, ts),
        "text": text,
        "ts": ts,
        "channelId": channel,
        "postedAt": "2026-10-17T10:00:00Z",
    }


def test_upsert_1000_rows_twice_is_idempotent_a_ac_16(store: GraphStore) -> None:
    """A-AC-16"""
    rows = [msg(i) for i in range(1000)]
    assert store.upsert_nodes("SlackMessage", rows) == 1000
    first = store.query(
        "MATCH (n:SlackMessage) RETURN n.id AS id, n.ingestedAt AS i, n.refreshedAt AS r",
        read_only=True,
    )
    assert len(first) == 1000
    time.sleep(0.05)
    assert store.upsert_nodes("SlackMessage", rows) == 1000
    second = store.query(
        "MATCH (n:SlackMessage) RETURN n.id AS id, n.ingestedAt AS i, n.refreshedAt AS r",
        read_only=True,
    )
    assert store.count("SlackMessage") == 1000
    before = {r["id"]: r for r in first}
    for row in second:
        assert row["i"] == before[row["id"]]["i"]
        assert row["r"] > before[row["id"]]["r"]


def test_every_upsert_adds_metadata_a_ac_16(store: GraphStore, ontology: Ontology) -> None:
    """A-AC-16: source, workspaceId, ontologyVersion, refreshedAt and ingestedAt are written."""
    store.upsert_nodes("SlackMessage", [msg(1)])
    node = store.get_node(msg(1)["id"])
    assert node is not None
    assert node["source"] == "slack"
    assert node["workspaceId"] == store.workspace_id
    assert node["ontologyVersion"] == ontology.version
    assert node["ingestedAt"] and node["refreshedAt"]
    assert node["_label"] == "SlackMessage"


def test_upsert_updates_changed_properties_and_keeps_others(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [{**msg(1), "replyCount": 3}])
    store.upsert_nodes("SlackMessage", [{**msg(1), "text": "changed"}], partial=True)
    node = store.get_node(msg(1)["id"])
    assert node is not None
    assert node["text"] == "changed"
    assert node["replyCount"] == 3


def test_batches_larger_than_batch_size(store: GraphStore) -> None:
    assert store.upsert_nodes("SlackMessage", [msg(i) for i in range(1230)], batch_size=500) == 1230
    assert store.count("SlackMessage") == 1230


def test_empty_rows_are_a_no_op(store: GraphStore) -> None:
    assert store.upsert_nodes("SlackMessage", []) == 0
    assert store.count() == 0


def test_required_property_checked_before_any_query(store: GraphStore) -> None:
    bad = msg(1)
    del bad["text"]
    with pytest.raises(OntologyViolation, match="text"):
        store.upsert_nodes("SlackMessage", [bad])
    with pytest.raises(OntologyViolation, match="without id"):
        store.upsert_nodes("SlackMessage", [{"text": "x"}])
    assert store.count() == 0


def test_none_values_are_dropped_not_stored(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [{**msg(1), "threadTs": None}])
    node = store.get_node(msg(1)["id"])
    assert node is not None and "threadTs" not in node


def test_datetimes_and_dates_are_stored_as_iso_strings(store: GraphStore) -> None:
    when = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    store.upsert_nodes("SlackMessage", [{**msg(1), "postedAt": when}])
    node = store.get_node(msg(1)["id"])
    assert node is not None and node["postedAt"] == "2026-10-17T10:00:00Z"


def test_update_nodes_never_creates(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [msg(1)])
    updated = store.update_nodes(
        "SlackMessage",
        [{"id": msg(1)["id"], "text": "new"}, {"id": "slack:msg:C9:9.9", "text": "ghost"}],
    )
    assert updated == 1
    assert store.count("SlackMessage") == 1


def test_links_with_missing_endpoints_a_ac_17(store: GraphStore) -> None:
    """A-AC-17: 10 rows, 2 with a missing endpoint: 8 links created, 2 reported missing."""
    store.upsert_nodes("SlackMessage", [msg(i) for i in range(11)])
    props = {"method": "structural", "confidence": 1.0, "version": 1}
    rows = [LinkRow(msg(i)["id"], msg(i + 1)["id"], props) for i in range(8)]
    rows.append(LinkRow(msg(0)["id"], "slack:msg:C1:404.000001", props))
    rows.append(LinkRow("slack:msg:C1:405.000001", msg(1)["id"], props))
    result = store.upsert_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", rows)
    assert result.created == 8
    assert sorted(result.missing) == sorted(
        [
            (msg(0)["id"], "slack:msg:C1:404.000001"),
            ("slack:msg:C1:405.000001", msg(1)["id"]),
        ]
    )
    edges = store.query("MATCH ()-[r:PREVIOUS_VERSION]->() RETURN count(r) AS c", read_only=True)
    assert edges[0]["c"] == 8


def test_link_upsert_is_idempotent_and_updates_props(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [msg(1), msg(2)])

    def row(c: float) -> list[LinkRow]:
        props = {"method": "structural", "confidence": c, "version": 1}
        return [LinkRow(msg(1)["id"], msg(2)["id"], props)]

    store.upsert_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", row(0.5))
    store.upsert_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", row(0.9))
    edges = store.query(
        "MATCH ()-[r:PREVIOUS_VERSION]->() RETURN r.confidence AS c, r._type AS t", read_only=True
    )
    assert len(edges) == 1 and edges[0]["c"] == 0.9


def test_link_props_must_include_method_and_confidence(store: GraphStore) -> None:
    with pytest.raises(OntologyViolation, match="method and confidence"):
        store.upsert_links(
            "PREVIOUS_VERSION",
            "SlackMessage",
            "SlackMessage",
            [LinkRow(msg(1)["id"], msg(2)["id"], {"version": 1})],
        )


def test_unknown_link_property_rejected(store: GraphStore) -> None:
    with pytest.raises(OntologyViolation, match="bogus"):
        store.upsert_links(
            "PREVIOUS_VERSION",
            "SlackMessage",
            "SlackMessage",
            [
                LinkRow(
                    msg(1)["id"],
                    msg(2)["id"],
                    {"method": "structural", "confidence": 1, "bogus": 1},
                )
            ],
        )


def test_delete_and_tombstone_links(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [msg(1), msg(2)])
    props = {"method": "structural", "confidence": 1.0}
    pair = (msg(1)["id"], msg(2)["id"])
    store.upsert_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", [LinkRow(*pair, props)])
    assert store.tombstone_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", [pair]) == 1
    rows = store.query("MATCH ()-[r:PREVIOUS_VERSION]->() RETURN r.deleted AS d", read_only=True)
    assert rows == [{"d": True}]
    assert store.delete_links("PREVIOUS_VERSION", "SlackMessage", "SlackMessage", [pair]) == 1
    assert store.query("MATCH ()-[r:PREVIOUS_VERSION]->() RETURN r", read_only=True) == []


def test_get_node_edge_cases(store: GraphStore) -> None:
    assert store.get_node("not-an-id") is None
    assert store.get_node("slack:msg:C1:1.0") is None
    assert store.get_node("weird:prefix:x") is None


def test_query_returns_nodes_edges_and_paths_as_dicts(store: GraphStore) -> None:
    store.upsert_nodes("SlackMessage", [msg(1), msg(2)])
    store.upsert_links(
        "PREVIOUS_VERSION",
        "SlackMessage",
        "SlackMessage",
        [LinkRow(msg(1)["id"], msg(2)["id"], {"method": "structural", "confidence": 1.0})],
    )
    rows = store.query("MATCH p = (a)-[r]->(b) RETURN a, r, p", read_only=True)
    assert rows[0]["a"]["_label"] == "SlackMessage"
    assert rows[0]["r"]["_type"] == "PREVIOUS_VERSION"
    assert len(rows[0]["p"]["nodes"]) == 2 and len(rows[0]["p"]["edges"]) == 1


def test_errors_are_typed(store: GraphStore) -> None:
    with pytest.raises(GraphError):
        store.query("THIS IS NOT CYPHER")
    with pytest.raises(GraphError):
        store.query("CREATE (n:SlackMessage {id: 'x'})", read_only=True)


def test_missing_parameter_is_an_error(store: GraphStore) -> None:
    with pytest.raises((GraphError, ValueError)):
        store.query("RETURN $nothing")


# A-AC-21
BAD_LABELS = [
    "Nope",
    "SlackMessage`",
    "Slack Message",
    "`SlackMessage`",
    "",
    "SlackMessage) DETACH DELETE n //",
    "slackmessage",
]


class Spy:
    """Fails the test if a query reaches the database."""

    def __init__(self, store: GraphStore) -> None:
        self.calls: list[str] = []
        store._graph.query = self._record  # type: ignore[method-assign,assignment]
        store._graph.ro_query = self._record  # type: ignore[method-assign,assignment]

    def _record(self, text: str, *a: Any, **k: Any) -> Any:
        self.calls.append(text)
        raise AssertionError("a query was sent")


@pytest.mark.parametrize("label", BAD_LABELS)
def test_invalid_label_rejected_before_any_query_a_ac_21(store: GraphStore, label: str) -> None:
    """A-AC-21"""
    spy = Spy(store)
    with pytest.raises(InvalidName):
        store.upsert_nodes(label, [msg(1)])
    with pytest.raises(InvalidName):
        store.tombstone(label, ["x"])
    with pytest.raises(InvalidName):
        store.count(label)
    with pytest.raises(InvalidName):
        store.update_nodes(label, [{"id": "x"}])
    assert spy.calls == []


@pytest.mark.parametrize(
    "rel",
    ["NOPE", "PREVIOUS_VERSION`", "PREVIOUS VERSION", "PREVIOUS_VERSION]->() DELETE x //", ""],
)
def test_invalid_relationship_rejected_before_any_query_a_ac_21(
    store: GraphStore, rel: str
) -> None:
    """A-AC-21"""
    spy = Spy(store)
    row = LinkRow("a", "b", {"method": "structural", "confidence": 1})
    with pytest.raises(InvalidName):
        store.upsert_links(rel, "SlackMessage", "SlackMessage", [row])
    with pytest.raises(InvalidName):
        store.delete_links(rel, "SlackMessage", "SlackMessage", [("a", "b")])
    with pytest.raises(InvalidName):
        store.tombstone_links(rel, "SlackMessage", "SlackMessage", [("a", "b")])
    assert spy.calls == []


def test_relationship_not_valid_between_these_labels_rejected_a_ac_21(store: GraphStore) -> None:
    """A-AC-21: the name exists, but not for this pair of labels."""
    spy = Spy(store)
    with pytest.raises(InvalidName, match="not in the ontology"):
        store.upsert_links(
            "PREVIOUS_VERSION",
            "SlackUser",
            "SlackMessage",
            [LinkRow("a", "b", {"method": "structural", "confidence": 1})],
        )
    assert spy.calls == []


def test_invalid_graph_name_rejected_a_ac_21(falkordb_url: str, ontology: Ontology) -> None:
    """A-AC-21"""
    for bad in ("a b", "a`b", "x;y", "1abc", ""):
        with pytest.raises(InvalidName):
            GraphStore(falkordb_url, bad, ontology)


class FlakyStore(GraphStore):
    """Fault injection: batches over `limit` rows get a 1 ms timeout on the real server, so they time out."""

    limit = 150
    seen: list[int]

    def query(self, cypher: str, params: Any = None, **kw: Any) -> list[dict[str, Any]]:
        if not hasattr(self, "seen"):
            self.seen = []
        rows = (params or {}).get("rows")
        if isinstance(rows, list):
            self.seen.append(len(rows))
            if len(rows) > self.limit:
                kw["timeout_ms"] = 1
        return super().query(cypher, params, **kw)


def test_timeout_halves_the_batch_and_succeeds_a_ac_22(
    falkordb_url: str, ontology: Ontology
) -> None:
    """A-AC-22: a forced timeout on a large batch triggers halving; the batch eventually succeeds."""
    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    s = FlakyStore(falkordb_url, name, ontology, workspace_id=name)
    try:
        rows = [{**msg(i), "text": "x" * 500} for i in range(1000)]
        assert s.upsert_nodes("SlackMessage", rows, batch_size=500) == 1000
        assert s.count("SlackMessage") == 1000
        assert s.seen[0] == 500
        assert 250 in s.seen and 125 in s.seen
        assert max(n for n in s.seen[-8:]) <= 150
    finally:
        s.drop()
        s.close()


def test_timeout_that_never_clears_raises_after_the_floor_a_ac_22(
    falkordb_url: str, ontology: Ontology
) -> None:
    """A-AC-22: halving stops at 50 rows, then the typed timeout error reaches the caller."""
    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    s = GraphStore(falkordb_url, name, ontology, workspace_id=name, timeout_ms=1)
    try:
        rows = [{**msg(i), "text": "x" * 2000} for i in range(2000)]
        with pytest.raises(GraphTimeout):
            s.upsert_nodes("SlackMessage", rows, batch_size=500)
    finally:
        s.drop()
        s.close()
