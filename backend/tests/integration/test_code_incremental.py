"""Updates when new commits land (spec A, A6.10): A-AC-37 stable ids, A-AC-98 in-place updates keep links,
A-AC-99 renames and moves get RENAMED_TO and callers are re-pointed, A-AC-100 deletes are tombstones and
unchanged files are not rewritten."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from actron.connectors.code.pipeline import CodeIngestReport, ingest_code
from actron.graph import ids
from actron.graph.store import LinkRow
from tests.unit.code.repo_builder import SyntheticRepo

REPO = "acme/incr"
LIVE = "coalesce(n.deleted, false) = false"

M_PY = """\
def f(x):
    total = 0
    for i in range(x):
        total += i
    return total


def g(items):
    out = []
    for item in items:
        if item:
            out.append(item * 2)
    return sorted(out)
"""
CALLER_PY = "from m import f\n\n\ndef h():\n    return f(3)\n"


def ingest(graph: Any, repo: SyntheticRepo, tmp: Path, since: str | None = None) -> CodeIngestReport:
    return asyncio.run(ingest_code("incr", REPO, url=repo.url, clone_dir=tmp / "clones", depth=100,
                                   store=graph, since_sha=since))


def fn(path: str, q: str) -> str:
    return ids.code_fn(REPO, path, q)


def base(graph: Any, tmp: Path) -> SyntheticRepo:
    r = SyntheticRepo(tmp / "src")
    r.write("m.py", M_PY, raw=True)
    r.write("caller.py", CALLER_PY, raw=True)
    r.write("untouched.py", "def stay():\n    return 0\n", raw=True)
    r.commit("init")
    ingest(graph, r, tmp)
    return r


def live_count(graph: Any, label: str) -> int:
    return int(graph.query(f"MATCH (n:{label}) WHERE {LIVE} RETURN count(n) AS c")[0]["c"])


def test_ids_stable_after_inserting_lines(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-37"""
    graph = indexed_graph
    r = base(graph, tmp_path)
    before = {x["id"] for x in graph.query("MATCH (n:CodeFunction) RETURN n.id AS id")}
    cursor = r.head()
    r.write("m.py", "# a new comment\n\n\n" + M_PY, raw=True)
    r.commit("comments above")
    ingest(graph, r, tmp_path, since=cursor)
    after = {x["id"] for x in graph.query("MATCH (n:CodeFunction) RETURN n.id AS id")}
    assert before == after
    f = graph.get_node(fn("m.py", "f"))
    assert f is not None and f["startLine"] == 4 and not f.get("deleted")


def test_in_place_update_keeps_links(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-98"""
    graph = indexed_graph
    r = base(graph, tmp_path)
    graph.upsert_nodes("Decision", [{"id": ids.decision("t", "1"), "statement": "f must stay pure", "status": "approved",
                                     "quote": "keep f pure", "confidence": 1.0, "extractedBy": "test"}])
    graph.upsert_links("CONSTRAINS", "Decision", "CodeFunction",
                       [LinkRow(ids.decision("t", "1"), fn("m.py", "f"), {"method": "explicit", "confidence": 1.0})])
    graph.upsert_nodes("GithubReviewComment", [{"id": ids.github_review_comment(7), "body": "nit", "path": "m.py",
                                                "createdAt": "2026-01-01T00:00:00Z", "url": "https://x/7"}])
    graph.upsert_links("COMMENT_ON_FUNCTION", "GithubReviewComment", "CodeFunction",
                       [LinkRow(ids.github_review_comment(7), fn("m.py", "g"), {"method": "structural", "confidence": 0.8})])
    old_f = graph.get_node(fn("m.py", "f"))
    counts_before = {lbl: live_count(graph, lbl) for lbl in ("CodeFunction", "CodeClass", "CodeFile")}
    cursor = r.head()
    r.write("m.py", M_PY.replace("total += i", "total += i * 2").replace("return sorted(out)",
                                                                         "out.reverse()\n    return out"), raw=True)
    sha = r.commit("change f and g")
    rep = ingest(graph, r, tmp_path, since=cursor)
    assert rep.files_changed == 1
    f = graph.get_node(fn("m.py", "f"))
    g = graph.get_node(fn("m.py", "g"))
    assert f is not None and g is not None and old_f is not None
    assert "total += i * 2" in f["body"] and f["contentHash"] != old_f["contentHash"]
    assert f["lastCommitSha"] == sha and g["lastCommitSha"] == sha
    assert g["startLine"] == 8 and g["endLine"] == 14
    assert {lbl: live_count(graph, lbl) for lbl in counts_before} == counts_before
    assert graph.query("MATCH (d:Decision)-[:CONSTRAINS]->(f:CodeFunction {id: $id}) RETURN count(d) AS c",
                       {"id": fn("m.py", "f")})[0]["c"] == 1
    assert graph.query("MATCH (c:GithubReviewComment)-[:COMMENT_ON_FUNCTION]->(f:CodeFunction {id: $id}) "
                       "RETURN count(c) AS c", {"id": fn("m.py", "g")})[0]["c"] == 1
    touched = graph.query("MATCH (c:GitCommit {sha: $s})-[t:TOUCHED]->(f) RETURN f.name AS n, t.changeType AS ct",
                          {"s": sha})
    assert sorted((x["n"], x["ct"]) for x in touched) == [("f", "modified"), ("g", "modified")]


def test_rename_and_move(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-99"""
    graph = indexed_graph
    r = base(graph, tmp_path)
    graph.upsert_nodes("Decision", [{"id": ids.decision("t", "2"), "statement": "f returns ints", "status": "approved",
                                     "quote": "ints only", "confidence": 1.0, "extractedBy": "test"}])
    graph.upsert_links("CONSTRAINS", "Decision", "CodeFunction",
                       [LinkRow(ids.decision("t", "2"), fn("m.py", "f"), {"method": "explicit", "confidence": 1.0})])
    assert graph.query("MATCH (a {id: $a})-[:CALLS]->(b {id: $b}) RETURN count(*) AS c",
                       {"a": fn("caller.py", "h"), "b": fn("m.py", "f")})[0]["c"] == 1
    cursor = r.head()
    renamed = M_PY.replace("def f(x):", "def f_total(x):").split("\n\n\ndef g")[0] + "\n"
    r.write("m.py", renamed, raw=True)
    moved_g = M_PY.split("\n\n\n")[1].replace("return sorted(out)", "return sorted(out, reverse=True)")
    r.write("lib.py", moved_g, raw=True)
    sha = r.commit("rename f, move g")
    rep = ingest(graph, r, tmp_path, since=cursor)
    assert rep.renames >= 2
    links = {(x["a"], x["b"]): x for x in graph.query(
        "MATCH (a:CodeFunction)-[r:RENAMED_TO]->(b:CodeFunction) RETURN a.id AS a, b.id AS b, r.commitSha AS s, "
        "r.similarity AS sim, a.deleted AS d")}
    f_link = links[(fn("m.py", "f"), fn("m.py", "f_total"))]
    assert f_link["s"] == sha and f_link["sim"] == 1.0 and f_link["d"] is True
    g_link = links[(fn("m.py", "g"), fn("lib.py", "g"))]
    assert 0.8 <= g_link["sim"] < 1.0 and g_link["s"] == sha
    # the decision on the old function is found for the new one by following RENAMED_TO backwards
    found = graph.query("MATCH (n:CodeFunction {id: $id})<-[:RENAMED_TO*1..5]-(old)<-[:CONSTRAINS]-(d:Decision) "
                        "RETURN d.statement AS s", {"id": fn("m.py", "f_total")})
    assert found == [{"s": "f returns ints"}]
    # earlier code of the renamed function is read from git through the rename chain
    from actron.connectors.code.history_tools import get_code_at, history

    before = get_code_at(graph, fn("m.py", "f_total"), cursor, repo_dir=tmp_path / "clones" / "incr" / "acme__incr")
    assert before["found"] and before["matchedId"] == fn("m.py", "f") and before["code"].startswith("def f(x):")
    assert [h["functionId"] for h in history(graph, fn("m.py", "f_total"))][-1] == fn("m.py", "f")
    # the caller in the unchanged file now points at the new function
    assert graph.query("MATCH (a {id: $a})-[:CALLS]->(b) RETURN b.id AS b", {"a": fn("caller.py", "h")}) == [
        {"b": fn("m.py", "f_total")}]


def test_delete_tombstones_and_unchanged_files(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-100"""
    graph = indexed_graph
    r = base(graph, tmp_path)
    stay_file = graph.get_node(ids.code_file(REPO, "untouched.py"))
    stay_fn = graph.get_node(fn("untouched.py", "stay"))
    assert stay_file is not None and stay_fn is not None
    cursor = r.head()
    r.write("m.py", M_PY.split("\n\n\ndef g")[0] + "\n", raw=True)
    sha = r.commit("delete g")
    ingest(graph, r, tmp_path, since=cursor)
    g = graph.get_node(fn("m.py", "g"))
    assert g is not None and g["deleted"] is True and g["deletedAt"]
    live = graph.query(f"MATCH (n:CodeFunction) WHERE {LIVE} RETURN n.name AS n")
    assert "g" not in {x["n"] for x in live}
    hist = graph.query("MATCH (c:GitCommit)-[t:TOUCHED]->(f:CodeFunction {id: $id}) RETURN c.sha AS s, "
                       "t.changeType AS ct ORDER BY c.authoredAt", {"id": fn("m.py", "g")})
    assert hist[-1] == {"s": sha, "ct": "deleted"} and hist[0]["ct"] == "added"
    after_file = graph.get_node(ids.code_file(REPO, "untouched.py"))
    assert after_file is not None and after_file["refreshedAt"] == stay_file["refreshedAt"]
    after_fn = graph.get_node(fn("untouched.py", "stay"))
    assert after_fn is not None and after_fn["contentHash"] == stay_fn["contentHash"]
    # deleting a whole file tombstones it and its symbols
    cursor = r.head()
    r.remove("untouched.py")
    r.commit("drop file")
    ingest(graph, r, tmp_path, since=cursor)
    gone = graph.get_node(ids.code_file(REPO, "untouched.py"))
    assert gone is not None and gone["deleted"] is True
    assert graph.get_node(fn("untouched.py", "stay"))["deleted"] is True  # type: ignore[index]
