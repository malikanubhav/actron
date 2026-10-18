"""Write-back (spec B, B10): the graph records the PR, its links and the procedure success (B-AC-49); running it
twice creates nothing new (B-AC-50)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from actron.activities import request as acts
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import service
from actron.graph import ids
from actron.graph.store import store_for
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401

FN = "code:fn:o/r:src/export.py::export_csv"
OTHER = "code:fn:o/r:src/other.py::f"
PROC = "actron:procedure:exports"
INV = "actron:investigation:inv1"


def _seed(ws: str) -> None:
    store = store_for(ws)
    meta = "workspaceId: $ws, ingestedAt: '2026-10-17T00:00:00Z', refreshedAt: '2026-10-17T00:00:00Z'"
    store.query(f"CREATE (:CodeFunction {{id: $f, name: 'export_csv', source: 'code', {meta}}})", {"f": FN, "ws": ws})
    store.query(f"CREATE (:CodeFunction {{id: $f, name: 'f', source: 'code', {meta}}})", {"f": OTHER, "ws": ws})
    store.query(f"CREATE (:Procedure {{id: $p, title: 'Exports', area: 'exports', successCount: 2, source: 'actron', "
                f"{meta}}})", {"p": PROC, "ws": ws})
    store.query(f"CREATE (:Investigation {{id: $i, summary: 's', conflictLabel: 'none', startedAt: '2026-10-17', "
                f"source: 'actron', {meta}}})", {"i": INV, "ws": ws})


async def _delivered(w6: W6Env) -> str:  # noqa: F811
    view = await service.create_request(w6.ws, text="Change the export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    rid = view["id"]
    with session_scope() as s:
        row = s.get(m.Request, rid)
        assert row is not None
        row.data = {**(row.data or {}), "pr": {"number": 42, "url": "https://github.com/o/r/pull/42",
                                               "headSha": "abc", "state": "open", "targetBranch": "main"},
                    "findings": {"procedures": [{"id": PROC, "testCommand": "pytest -q"}]},
                    "investigation": {"investigationId": INV}}
        s.add(m.BuildRun(id="bld_wb", request_id=rid, status="passed", branch="actron/x", base_sha="base",
                         head_sha="abc", tests_passed=5, started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                         report={"filesChanged": ["src/export.py"]}))
    return str(rid)


def _count(ws: str, cypher: str, params: dict[str, Any]) -> int:
    rows = store_for(ws).query(cypher, params, read_only=True)
    return int(rows[0]["c"]) if rows else 0


async def test_writeback_links_and_is_idempotent(w6: W6Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """B-AC-49 / B-AC-50."""
    monkeypatch.setattr(acts, "_github_cfg", lambda ws: {"repository": "o/r", "fork": "o/r"})
    _seed(w6.ws)
    rid = await _delivered(w6)
    first = await acts.writeback({"ws": w6.ws, "requestId": rid, "buildId": "bld_wb", "prNumber": 42})
    assert first["counts"]["prs"] == 1 and first["counts"]["functions"] == 1 and first["counts"]["procedures"] == 1
    pr = ids.github_pr("o/r", 42)
    bid = ids.build("bld_wb")
    checks = {
        "DELIVERED_BY": ("MATCH (:Request {id: $r})-[x:DELIVERED_BY]->(:GithubPullRequest {id: $p}) RETURN count(x) AS c",
                         {"r": ids.request(rid), "p": pr}),
        "PRODUCED": ("MATCH (:BuildRun {id: $b})-[x:PRODUCED]->(:GithubPullRequest {id: $p}) RETURN count(x) AS c",
                     {"b": bid, "p": pr}),
        "HANDED_TO": ("MATCH (:Investigation {id: $i})-[x:HANDED_TO]->(:BuildRun {id: $b}) RETURN count(x) AS c",
                      {"i": INV, "b": bid}),
        "USED_PROCEDURE": ("MATCH (:BuildRun {id: $b})-[x:USED_PROCEDURE]->(:Procedure {id: $p}) RETURN count(x) AS c",
                           {"b": bid, "p": PROC}),
        "LEARNED_FROM_BUILD": ("MATCH (:Procedure {id: $p})-[x:LEARNED_FROM_BUILD]->(:BuildRun {id: $b}) "
                               "RETURN count(x) AS c", {"b": bid, "p": PROC}),
        "BUILD_TOUCHED": ("MATCH (:BuildRun {id: $b})-[x:BUILD_TOUCHED]->(f:CodeFunction) RETURN count(x) AS c",
                          {"b": bid}),
    }
    for name, (cypher, params) in checks.items():
        assert _count(w6.ws, cypher, params) == 1, name
    success = "MATCH (p:Procedure {id: $p}) RETURN p.successCount AS c"
    assert _count(w6.ws, success, {"p": PROC}) == 3
    assert "writeback.done" in w6.types(rid)
    nodes_before = _count(w6.ws, "MATCH (n) RETURN count(n) AS c", {})
    links_before = _count(w6.ws, "MATCH ()-[r]->() RETURN count(r) AS c", {})
    second = await acts.writeback({"ws": w6.ws, "requestId": rid, "buildId": "bld_wb", "prNumber": 42})
    assert second["counts"]["procedures"] == 0
    assert _count(w6.ws, "MATCH (n) RETURN count(n) AS c", {}) == nodes_before
    assert _count(w6.ws, "MATCH ()-[r]->() RETURN count(r) AS c", {}) == links_before
    assert _count(w6.ws, success, {"p": PROC}) == 3
