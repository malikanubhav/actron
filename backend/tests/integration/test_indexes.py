"""A-AC-13 (ensure_indexes is idempotent and complete), A-AC-14 (skipped relationships are reported)."""

from __future__ import annotations

import json

import pytest

from actron.config import REPO_ROOT
from actron.graph.ontology import FABRIC_FILES, FILE_ORDER, Ontology, ensure_indexes
from actron.graph.store import GraphError, GraphStore
from tests.integration.falkor_scratch import Server, server  # noqa: F401

pytestmark = pytest.mark.integration


def index_map(graph: GraphStore) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for row in graph.query("CALL db.indexes()", read_only=True):
        for prop in row["properties"]:
            out.setdefault((row["label"], prop), set()).update(row["types"].get(prop, []))
    return out


def test_first_run_creates_everything_a_ac_13(graph: GraphStore, ontology: Ontology) -> None:
    """A-AC-13: db.indexes() lists the expected range and full-text indexes after the first run."""
    report = ensure_indexes(graph, ontology)
    assert report.failed == []
    assert report.created
    assert report.existing == []
    indexes = index_map(graph)
    for node in ontology.nodes.values():
        assert "RANGE" in indexes[(node.name, "id")], node.name
        for prop in node.properties.values():
            if (
                prop.indexed
                and prop.name != "id"
                and not prop.full_text
                and prop.name.isidentifier()
            ):
                assert "RANGE" in indexes[(node.name, prop.name)], f"{node.name}.{prop.name}"
    for label, fields in ontology.search_fields().items():
        for field in fields:
            assert "FULLTEXT" in indexes[(label, field)], f"{label}.{field}"
    # Every ontology full-text field is part of the search fields.
    for label, fields in ontology.full_text_fields().items():
        assert set(fields) <= set(ontology.search_fields()[label])


def test_second_run_creates_nothing_a_ac_13(graph: GraphStore, ontology: Ontology) -> None:
    """A-AC-13: run twice, the second run creates nothing and reports the existing indexes."""
    first = ensure_indexes(graph, ontology)
    second = ensure_indexes(graph, ontology)
    assert second.created == []
    assert second.failed == []
    assert sorted(second.existing) == sorted(first.created)
    third = ensure_indexes(graph, ontology)
    assert third.created == [] and sorted(third.existing) == sorted(first.created)


def test_upsert_works_with_constraints_in_place_a_ac_13(indexed_graph: GraphStore) -> None:
    """A-AC-13: MERGE on id keeps working once constraints exist."""
    row = {"id": "slack:user:U7", "name": "Ada"}
    indexed_graph.upsert_nodes("SlackUser", [row], partial=True)
    indexed_graph.upsert_nodes("SlackUser", [row], partial=True)
    assert indexed_graph.count("SlackUser") == 1


def test_fulltext_index_is_usable_a_ac_13(indexed_graph: GraphStore) -> None:
    """A-AC-13: a full-text query finds a node through the index created by ensure_indexes."""
    indexed_graph.upsert_nodes(
        "LinearIssue",
        [
            {
                "id": "linear:issue:u1",
                "title": "Retry the webhook delivery",
                "url": "https://l/1",
                "identifier": "ENG-1",
            },
            {
                "id": "linear:issue:u2",
                "title": "Unrelated chore",
                "url": "https://l/2",
                "identifier": "ENG-2",
            },
        ],
    )
    rows = indexed_graph.query(
        "CALL db.idx.fulltext.queryNodes('LinearIssue', 'webhook') YIELD node RETURN node.id AS id",
        read_only=True,
    )
    assert [r["id"] for r in rows] == ["linear:issue:u1"]


def test_skipped_relationships_match_the_files_a_ac_14(
    graph: GraphStore, ontology: Ontology
) -> None:
    """A-AC-14: the report lists exactly the fabric relationships with undefined endpoints."""
    files = {s: json.loads((REPO_ROOT / "ontology" / f"{s}.json").read_text()) for s in FILE_ORDER}
    defined = {n["name"] for f in files.values() for n in f["nodes"]}
    expected = sorted(
        (f"{stem}.json", r["name"], r["from_node"], r["to_node"])
        for stem in FILE_ORDER
        if stem in {s.removesuffix(".json") for s in FABRIC_FILES} | set(FABRIC_FILES)
        for r in files[stem]["relationships"]
        if r["from_node"] not in defined or r["to_node"] not in defined
    )
    report = ensure_indexes(graph, ontology)
    assert sorted(report.skipped_relationships) == expected
    assert len([s for s in expected if s[0] == "slack.json"]) == 12
    assert len([s for s in expected if s[0] == "linear.json"]) == 78


def wait_operational(store: GraphStore) -> None:
    import time

    for _ in range(100):
        rows = store.query("CALL db.constraints()", read_only=True)
        if rows and all(r["status"] == "OPERATIONAL" for r in rows):
            return
        time.sleep(0.1)
    raise AssertionError("constraints did not become operational")


@pytest.fixture
def constrained(server: Server, ontology: Ontology):  # type: ignore[no-untyped-def]  # noqa: F811
    """A graph on the scratch server with unique constraints. Never dropped: see limitation 12."""
    import uuid

    store = GraphStore(server.url, f"actron_constrained_{uuid.uuid4().hex[:8]}", ontology)
    yield store
    store.close()


def test_constraints_created_once_and_enforced_a_ac_13(
    constrained: GraphStore, ontology: Ontology
) -> None:
    """A-AC-13: unique id constraints are created, enforced, and a second run writes nothing."""
    first = ensure_indexes(constrained, ontology, constraints=True)
    assert first.failed == []
    unique = [t for t in first.created if t.startswith("unique:")]
    assert len(unique) == len(ontology.nodes)
    wait_operational(constrained)
    second = ensure_indexes(constrained, ontology, constraints=True)
    assert second.created == []
    assert sorted(second.existing) == sorted(first.created)
    constrained.query("CREATE (:SlackUser {id: 'slack:user:U1'})")
    with pytest.raises(GraphError):
        constrained.query("CREATE (:SlackUser {id: 'slack:user:U1'})")
    assert constrained.count("SlackUser") == 1


def test_default_in_test_env_creates_no_constraints_a_ac_13(
    graph: GraphStore, ontology: Ontology
) -> None:
    """A-AC-13: ACTRON_ENV=test skips constraints (limitation 12), everything else is created."""
    report = ensure_indexes(graph, ontology)
    assert not [t for t in report.created if t.startswith("unique:")]
    assert graph.query("CALL db.constraints()", read_only=True) == []


def test_drop_refuses_a_constrained_graph_a_ac_13(
    constrained: GraphStore, ontology: Ontology
) -> None:
    """A-AC-13: deleting a graph with unique constraints is refused (it breaks replay on v4.22.1)."""
    ensure_indexes(constrained, ontology, constraints=True)
    with pytest.raises(GraphError, match="unique constraints"):
        constrained.drop()


@pytest.mark.slow
def test_dropped_unconstrained_graphs_survive_restarts_a_ac_13(
    server: Server, ontology: Ontology  # noqa: F811
) -> None:
    """A-AC-13 / limitation 12: without constraints, create, drop and restart three times is safe."""
    import uuid

    for _ in range(3):
        store = GraphStore(server.url, f"actron_drop_{uuid.uuid4().hex[:8]}", ontology)
        ensure_indexes(store, ontology, constraints=False)
        store.upsert_nodes("SlackUser", [{"id": "slack:user:U9", "name": "x"}], partial=True)
        store.drop()
        store.close()
    for _ in range(3):
        server.restart()
