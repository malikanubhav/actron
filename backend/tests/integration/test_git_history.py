"""A-AC-39: scripted commits (add, modify, rename file, delete function, move function, merge) produce the
expected GitCommit, GitFileChange, TOUCHED and AUTHORED_BY. A-AC-42: an incremental run reads only new commits;
after a force push it re-reads and records the partial reason. A-AC-41 in the graph (BLAME_OWNS)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from actron.connectors.code.pipeline import CodeIngestReport, ingest_code
from actron.graph import ids
from tests.unit.code.repo_builder import SyntheticRepo

REPO = "acme/hist"
BOB = ("Bob Builder", "bob@example.com")


def ingest(graph: Any, repo: SyntheticRepo, tmp: Path, since: str | None = None) -> CodeIngestReport:
    return asyncio.run(ingest_code("hist", REPO, url=repo.url, clone_dir=tmp / "clones", depth=100,
                                   store=graph, since_sha=since))


def touches(graph: Any, fn_id: str) -> dict[str, str]:
    rows = graph.query("MATCH (c:GitCommit)-[t:TOUCHED]->(f:CodeFunction {id: $id}) RETURN c.subject AS s, "
                       "t.changeType AS ct", {"id": fn_id})
    return {r["s"]: r["ct"] for r in rows}


def scripted(tmp: Path) -> SyntheticRepo:
    r = SyntheticRepo(tmp / "src")
    r.write("a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    r.commit("add f and g")
    r.write("a.py", "def f():\n    return 10\n\n\ndef g():\n    return 2\n")
    r.commit("modify f", author=BOB)
    r.move("a.py", "b.py")
    r.commit("rename a to b")
    r.write("b.py", "def f():\n    return 10\n")
    r.commit("delete g")
    r.write("b.py", "X = 1\n")
    r.write("c.py", "def f():\n    return 10\n")
    r.commit("move f to c")
    r.git("checkout", "-q", "-b", "feature")
    r.write("d.py", "def h():\n    return 3\n")
    r.commit("add h on feature", author=BOB)
    r.git("checkout", "-q", "main")
    r.write("c.py", "def f():\n    return 11\n")
    r.commit("modify f in c")
    r.git("merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    return r


def test_scripted_history(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-39, A-AC-41"""
    graph = indexed_graph
    r = scripted(tmp_path)
    rep = ingest(graph, r, tmp_path)
    assert rep.commits == 8 and rep.counts["GitCommit"] == 8
    merge = graph.query("MATCH (c:GitCommit {subject: 'merge feature'}) RETURN c.isMerge AS m, c.parentShas AS p")[0]
    assert merge["m"] is True and len(merge["p"]) == 2
    assert graph.query("MATCH (c:GitCommit {subject: 'merge feature'})-[:HAS_FILE_CHANGE]->(x) RETURN count(x) AS n")[0]["n"] == 0
    ren = graph.query("MATCH (c:GitCommit {subject: 'rename a to b'})-[:HAS_FILE_CHANGE]->(x:GitFileChange) "
                      "RETURN x.status AS s, x.path AS p, x.oldPath AS o")
    assert ren == [{"s": "renamed", "p": "b.py", "o": "a.py"}]
    mod = graph.query("MATCH (c:GitCommit {subject: 'modify f in c'})-[:HAS_FILE_CHANGE]->(x:GitFileChange) "
                      "RETURN x.status AS s, x.hunks AS h, x.additions AS a, x.deletions AS d")
    assert mod == [{"s": "modified", "h": ["2-2"], "a": 1, "d": 1}]
    f_now = ids.code_fn(REPO, "c.py", "f")
    assert touches(graph, f_now) == {"move f to c": "added", "modify f in c": "modified"}
    assert touches(graph, ids.code_fn(REPO, "d.py", "h")) == {"add h on feature": "added"}
    authors = {x["s"]: x["e"] for x in graph.query(
        "MATCH (c:GitCommit)-[:AUTHORED_BY]->(a:GitAuthor) RETURN c.subject AS s, a.email AS e")}
    assert authors["modify f"] == "bob@example.com" and authors["add f and g"] == "ada@example.com"
    bob = graph.get_node(ids.git_author("bob@example.com"))
    assert bob is not None and bob["commitCount"] == 2
    fn_node = graph.get_node(f_now)
    assert fn_node is not None and fn_node["lastCommitSha"] == r.git("rev-parse", "HEAD^1")
    owners = graph.query("MATCH (a:GitAuthor)-[b:BLAME_OWNS]->(f:CodeFunction {id: $id}) RETURN a.email AS e, "
                         "b.lines AS l, b.lineShare AS s", {"id": f_now})
    assert owners == [{"e": "ada@example.com", "l": 2, "s": 1.0}]
    head = graph.query("MATCH (:CodeRepository {id: $r})-[:HEAD_COMMIT]->(c:GitCommit) RETURN c.sha AS s",
                       {"r": ids.code_repo(REPO)})
    assert head == [{"s": r.head()}]
    assert graph.query("MATCH (b:GitBranch)-[:BRANCH_HEAD]->(c:GitCommit) WHERE b.name = 'main' RETURN c.sha AS s")[0]["s"] == r.head()


def test_incremental_and_force_push(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-42"""
    graph = indexed_graph
    r = scripted(tmp_path)
    ingest(graph, r, tmp_path)
    cursor = r.head()
    r.write("c.py", "def f():\n    return 12\n")
    r.commit("next one")
    r.write("e.py", "def k():\n    return 4\n")
    r.commit("next two")
    rep = ingest(graph, r, tmp_path, since=cursor)
    assert rep.mode == "incremental" and rep.commits == 2 and rep.partial_reason is None
    assert rep.counts["GitCommit"] == 10
    assert rep.files_changed == 2  # c.py and e.py only
    assert touches(graph, ids.code_fn(REPO, "c.py", "f"))["next one"] == "modified"
    cursor2 = r.head()
    r.git("reset", "-q", "--hard", "HEAD~1")
    r.write("e.py", "def k():\n    return 5\n")
    r.commit("rewritten two")
    rep2 = ingest(graph, r, tmp_path, since=cursor2)
    assert rep2.partial_reason == "history rewritten"
    assert rep2.commits == 10  # re-read the history to the depth
    assert graph.query("MATCH (c:GitCommit {subject: 'rewritten two'}) RETURN count(c) AS n")[0]["n"] == 1
    same = ingest(graph, r, tmp_path, since=r.head())
    assert same.commits == 0 and same.counts == rep2.counts


def test_get_code_at_and_history(indexed_graph: Any, tmp_path: Path) -> None:
    """B-AC-82, A-AC-43: earlier versions are read from git on demand; history lists the touching commits."""
    from actron.connectors.code.history_tools import get_code_at, history

    graph = indexed_graph
    r = scripted(tmp_path)
    ingest(graph, r, tmp_path)
    f_now = ids.code_fn(REPO, "c.py", "f")
    hist = history(graph, f_now, limit=5)
    assert [h["subject"] for h in hist] == ["modify f in c", "move f to c"]
    assert hist[0]["authorEmail"] == "ada@example.com" and hist[0]["changeType"] == "modified"
    clone = tmp_path / "clones" / "hist" / "acme__hist"
    move_sha = r.git("log", "--format=%H", "-n1", "--grep", "move f to c")
    old = get_code_at(graph, f_now, move_sha, repo_dir=clone)
    assert old["found"] and old["code"] == "def f():\n    return 10" and old["startLine"] == 1
    missing = get_code_at(clone, f_now, r.git("log", "--format=%H", "-n1", "--grep", "add f and g"))
    assert missing["found"] is False and "does not exist" in missing["reason"]
    now = get_code_at(clone, f_now, r.head())
    assert now["code"] == "def f():\n    return 11"


def test_api_commit_arrives_in_clone(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-101 (code side): a GitCommit created from the GitHub API with inClone=false gets its file changes and
    inClone=true when the commit later arrives in the clone."""
    graph = indexed_graph
    r = scripted(tmp_path)
    ingest(graph, r, tmp_path)
    cursor = r.head()
    r.write("pr.py", "def from_pr():\n    return 1\n")
    sha = r.commit("PR commit merged later")
    graph.upsert_nodes("GitCommit", [{"id": ids.git_commit(REPO, sha), "sha": sha, "subject": "PR commit merged later",
                                      "message": "PR commit merged later", "authoredAt": "2026-01-01T00:00:00Z",
                                      "inClone": False}])
    before = graph.get_node(ids.git_commit(REPO, sha))
    assert before is not None and before["inClone"] is False
    ingest(graph, r, tmp_path, since=cursor)
    after = graph.get_node(ids.git_commit(REPO, sha))
    assert after is not None and after["inClone"] is True
    changes = graph.query("MATCH (c:GitCommit {id: $id})-[:HAS_FILE_CHANGE]->(x) RETURN x.path AS p",
                          {"id": ids.git_commit(REPO, sha)})
    assert changes == [{"p": "pr.py"}]
    assert touches(graph, ids.code_fn(REPO, "pr.py", "from_pr")) == {"PR commit merged later": "added"}
