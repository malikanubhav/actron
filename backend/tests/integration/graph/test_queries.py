"""Named queries on the fixture graph (spec B, B3). B-AC-14: expected rows per query, tombstones excluded."""

from __future__ import annotations

from typing import Any

import pytest

from actron.graph import queries as Q
from actron.graph.ontology import Ontology
from tests.integration.graph import fixture_graph as fx

pytestmark = pytest.mark.integration


def test_fixture_graph_matches_ontology(small_graph: Any, ontology: Ontology) -> None:
    """B-AC-14: every fixture node and link validates against the ontology (labels, properties, endpoints)."""
    nodes = small_graph.query("MATCH (n) RETURN n LIMIT 10000", read_only=True)
    assert 90 <= len(nodes) <= 200
    for row in nodes:
        node = dict(row["n"])
        label = node.pop("_label")
        assert node["workspaceId"] == small_graph.workspace_id
        ontology.validate_node(label, node)
    links = small_graph.query(
        "MATCH (a)-[r]->(b) RETURN labels(a)[0] AS a, labels(b)[0] AS b, r LIMIT 10000", read_only=True
    )
    assert len(links) > 150
    for row in links:
        props = {k: v for k, v in row["r"].items() if not k.startswith("_")}
        ontology.validate_rel(row["r"]["_type"], row["a"], row["b"], props)


def test_fulltext_query_builder() -> None:
    """B-AC-14: request text becomes an OR query of prefix terms; punctuation never becomes NOT."""
    q = Q.fulltext_query("Turn on auto-evaluate on save by default!")
    assert q == "turn*|auto*|evaluate*|save*|default*"
    assert Q.fulltext_query("the a of") == ""
    assert "evaluate*" in Q.fulltext_query("evaluateOnSave").split("|")


def test_seeds_fulltext_merges_labels_by_score(small_graph: Any, ontology: Ontology) -> None:
    """B-AC-14: seeds_fulltext queries each label's index and merges by score (top = 1.0)."""
    rows = Q.seeds_fulltext(small_graph, "auto-evaluate on save", search_fields=ontology.search_fields(), limit=20)
    found = {r.id for r in rows}
    assert fx.EVAL_SAVE in found
    assert fx.FEATURE_SAVE in found
    assert fx.D_SAVE in found  # decisions are searchable too
    assert rows[0].score == 1.0
    assert [r.score for r in rows] == sorted((r.score for r in rows), reverse=True)
    types = {r.type for r in rows}
    assert {"CodeFunction", "Feature", "Decision"} <= types
    save = next(r for r in rows if r.id == fx.EVAL_SAVE)
    assert save.nameMatch == 1.0 and not save.isTest


def test_seeds_fulltext_excludes_tombstones_and_respects_types(small_graph: Any, ontology: Ontology) -> None:
    """B-AC-14: tombstoned nodes never appear; `types` limits the labels searched."""
    rows = Q.seeds_fulltext(small_graph, "formatResult legacyEvaluate cached", search_fields=ontology.search_fields())
    ids_found = {r.id for r in rows}
    assert fx.FORMAT_OLD not in ids_found and fx.LEGACY not in ids_found and fx.D_CACHE not in ids_found
    only_fn = Q.seeds_fulltext(small_graph, "evaluate", search_fields=ontology.search_fields(), types=["CodeFunction"])
    assert only_fn and {r.type for r in only_fn} == {"CodeFunction"}
    assert Q.seeds_fulltext(small_graph, "kubernetes helm", search_fields=ontology.search_fields()) == []


def test_decisions_constraining(small_graph: Any) -> None:
    """B-AC-14: active CONSTRAINS only; approved/proposed/superseded; tombstoned, rejected and inactive excluded."""
    rows = Q.decisions_constraining(small_graph, [fx.EVAL_SAVE, fx.EVAL_CODE, fx.EVAL_SEL, fx.PRETTY, fx.SHOW])
    got = {r.id: r for r in rows}
    assert set(got) == {fx.D_SAVE, fx.D_WIDTH, fx.D_INLINE, fx.D_OUTPUT}
    save = got[fx.D_SAVE]
    assert save.status == "approved"
    assert save.path == [fx.EVAL_SAVE, fx.D_SAVE]
    assert save.source is not None and save.source.id == fx.M1 and save.source.type == "SlackMessage"
    assert save.sourceAuthor == "Alice Fixture"
    assert save.approvedIn == [fx.M2]
    assert got[fx.D_WIDTH].status == "proposed"
    assert got[fx.D_INLINE].status == "superseded"
    # newest first
    assert [r.id for r in rows] == sorted(got, key=lambda i: got[i].decidedAt or "", reverse=True)
    no_superseded = Q.decisions_constraining(small_graph, [fx.SHOW], include_superseded=False)
    assert [r.id for r in no_superseded] == [fx.D_OUTPUT]


def test_decisions_follow_renames_backwards(small_graph: Any) -> None:
    """B-AC-14: a decision on an earlier name (RENAMED_TO, up to 5 hops) is found for the new name."""
    rows = Q.decisions_constraining(small_graph, [fx.FORMAT])
    assert [r.id for r in rows] == [fx.D_PREFIX]
    assert rows[0].path == [fx.FORMAT, fx.FORMAT_OLD, fx.D_PREFIX]
    assert rows[0].targetId == fx.FORMAT_OLD


def test_related_work(small_graph: Any) -> None:
    """B-AC-14: PRs via PR_TOUCHED and review comments, tickets via IMPLEMENTED_BY, issues and messages via
    MENTIONS; renamed history included; tombstoned messages excluded; newest first."""
    rows = Q.related_work(small_graph, [fx.EVAL_SAVE, fx.EVAL_CODE, fx.FORMAT])
    got = {r.id: r for r in rows}
    assert set(got) == {fx.PR101, fx.PR103, fx.ISSUE55, fx.LI12}
    assert got[fx.PR101].state == "merged"
    assert got[fx.PR103].path == [fx.FORMAT, fx.FORMAT_OLD, fx.PR103]
    assert got[fx.LI12].path == [fx.EVAL_SAVE, fx.PR101, fx.LI12]
    assert got[fx.LI12].state == "completed"
    assert fx.M7 not in got  # tombstoned message mentioning evaluateCode
    assert [r.at for r in rows] == sorted((r.at or "" for r in rows), reverse=True)
    via_comment = Q.related_work(small_graph, [fx.EVAL_CODE])
    assert [r.id for r in via_comment] == [fx.LI12, fx.PR101]
    assert via_comment[1].path == [fx.EVAL_CODE, fx.RC1, fx.PR101]
    assert via_comment[0].path == [fx.EVAL_CODE, fx.RC1, fx.PR101, fx.LI12]
    slack = Q.related_work(small_graph, [fx.SEND])
    assert {r.id for r in slack} == {fx.M4, fx.M9}


def test_callers_backwards_min_depth(small_graph: Any) -> None:
    """B-AC-14: callers use a backwards variable-length match, each at its minimum depth; tombstoned callers
    (legacyEvaluate) are excluded."""
    rows = Q.callers(small_graph, fx.EVAL_CODE, 3)
    depth = {r.id: r.depth for r in rows}
    assert depth == {
        fx.EVAL_SAVE: 1, fx.EVAL_SEL: 1, fx.EVAL_TOP: 1, fx.T_EVAL: 1,
        fx.REGISTER: 2, fx.T_SAVE: 2, fx.ACTIVATE: 3,
    }
    assert fx.LEGACY not in depth
    save = next(r for r in rows if r.id == fx.EVAL_SAVE)
    assert save.callSiteLines == [29] and save.confidence == 1.0
    assert save.path == [fx.EVAL_CODE, fx.EVAL_SAVE]
    activate = next(r for r in rows if r.id == fx.ACTIVATE)
    assert activate.path == [fx.EVAL_CODE, fx.EVAL_SAVE, fx.REGISTER, fx.ACTIVATE] or activate.path[0] == fx.EVAL_CODE
    assert [r.depth for r in rows] == sorted(r.depth for r in rows)
    assert {r.id for r in Q.callers(small_graph, fx.EVAL_CODE, 1)} == {fx.EVAL_SAVE, fx.EVAL_SEL, fx.EVAL_TOP, fx.T_EVAL}


def test_callees_forward(small_graph: Any) -> None:
    """B-AC-14: callees follow CALLS forward."""
    rows = Q.callees(small_graph, fx.EVAL_CODE, 2)
    assert {r.id: r.depth for r in rows} == {
        fx.REPL_EVAL: 1, fx.FORMAT: 1, fx.SHOW: 1, fx.SEND: 2, fx.PRETTY: 2, fx.APPEND: 2,
    }
    with pytest.raises(Q.QueryError):
        Q.callees(small_graph, fx.EVAL_FILE, 1)


def test_impact(small_graph: Any) -> None:
    """B-AC-14: impact = callers over CALLS and INSTANTIATES (class via METHOD_OF), files, components, tests."""
    res = Q.impact(small_graph, [fx.REPL_CLASS], 3)
    fns = {f.id: f.depth for f in res.functions}
    assert fns[fx.CONNECT] == 1  # INSTANTIATES
    assert fns[fx.EVAL_CODE] == 1  # calls the method ReplSession.eval
    assert fns[fx.ACTIVATE] == 2
    assert fx.REPL_EVAL not in fns  # a start node, not an impacted caller
    assert all(not f.id.startswith(fx.FN + "src/extension-test") for f in res.functions)
    assert {f.path for f in res.files} >= {"src/connector.ts", "src/evaluate.ts", "src/extension.ts"}
    assert [c.id for c in res.components] == ["code:component:fixture/calva-lite:."]
    assert fx.T_EVAL in {t.id for t in res.tests}
    one = Q.impact(small_graph, [fx.EVAL_SAVE], 1)
    assert [f.id for f in one.functions] == [fx.REGISTER]
    assert [t.id for t in one.tests] == [fx.T_SAVE]


def test_tests_for(small_graph: Any) -> None:
    """B-AC-14: tests via TESTS (functions) and through a file's functions."""
    rows = Q.tests_for(small_graph, [fx.PRETTY, fx.PRETTY_MAP])
    assert {r.id for r in rows} == {fx.T_PRINT}
    assert rows[0].method == "calls" and rows[0].confidence == 0.9
    by_file = Q.tests_for(small_graph, [fx.EVAL_FILE])
    assert {r.id for r in by_file} == {fx.T_EVAL, fx.T_SAVE}


def test_criticality(small_graph: Any) -> None:
    """B-AC-14: stored PageRank, caller counts and percentile; non-functions ignored."""
    rows = Q.criticality(small_graph, [fx.SEND, fx.EVAL_CODE, fx.D_SAVE])
    assert [(r.id, r.criticalityPercentile, r.callerCount) for r in rows] == [
        (fx.SEND, 97.5, 3), (fx.EVAL_CODE, 95.0, 3)
    ]


def test_shortest_path_undirected(small_graph: Any) -> None:
    """B-AC-14: shortest path across mixed directions via algo.SPpaths."""
    res = Q.shortest_path(small_graph, fx.M1, fx.EVAL_CODE, 6)
    assert res.found and res.method == "algo.SPpaths"
    assert [n.id for n in res.nodes] == [fx.M1, fx.FEATURE_SAVE, fx.EVAL_SAVE, fx.EVAL_CODE]
    assert len(res.links) == 3
    assert Q.shortest_path(small_graph, fx.M1, fx.EVAL_CODE, 2).found is False


def test_owners(small_graph: Any) -> None:
    """B-AC-14: owners from KNOWS_ABOUT, OWNS and BLAME_OWNS via identities, best first, max 5."""
    rows = Q.owners(small_graph, [fx.EVAL_CODE, fx.SEND])
    assert [r.personId for r in rows] == [fx.CAROL, fx.ALICE, fx.BOB]
    carol = rows[0]
    assert carol.score == 1.0 and "codeowners" in carol.basis and "blame" in carol.basis
    alice = rows[1]
    assert alice.score == 0.8 and {"commits", "blame"} <= set(alice.basis)
    save = Q.owners(small_graph, [fx.EVAL_SAVE])
    assert save[0].personId == fx.ALICE and save[0].score == 1.0
    assert save[0].path == [fx.EVAL_SAVE, "git:author:alice@fixture.invalid",
                            "actron:identity:git:alice@fixture.invalid", fx.ALICE]


def test_procedures_for(small_graph: Any) -> None:
    """B-AC-14: procedures that apply to the ids or their files."""
    rows = Q.procedures_for(small_graph, [fx.FORMAT])
    assert [r.procedureId for r in rows] == [fx.PROC_EVAL]
    assert rows[0].path == [fx.FORMAT, fx.EVAL_FILE, fx.PROC_EVAL]
    assert rows[0].testCommand == "npm run unit-test -- --grep evaluate"


def test_every_lookup_by_id_is_labelled() -> None:
    """B-AC-14: no named query matches a node by id without a label (docs/falkordb.md)."""
    import inspect
    import re

    source = inspect.getsource(Q)
    assert not re.search(r"MATCH \(\w+ \{id:", source)
    assert "algo.BFS" not in source.replace("`algo.BFS`", "")


def test_unknown_ids_raise_or_skip(small_graph: Any) -> None:
    """B-AC-14: an unknown id prefix is a QueryError for single-id queries and skipped in lists."""
    with pytest.raises(Q.QueryError):
        Q.callers(small_graph, "nope:x:y", 1)
    assert Q.decisions_constraining(small_graph, ["nope:x:y"]) == []
