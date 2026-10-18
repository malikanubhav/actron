# ruff: noqa: F403, F405
"""GitHub mapping onto the ontology: A-AC-45 and A-AC-48 (graph needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from actron.config import get_settings
from actron.connectors import github
from actron.graph import ids
from actron.graph.store import LinkRow
from tests.fakes.github import FakeGithub, build_pr_fixture, review_comment_json, user
from tests.fakes.support import *

REPO = "acme/widgets"


def _config(**extra: Any) -> dict[str, Any]:
    return {"repository": REPO, "token": "t0ken", "api_url": "http://fake.github", "history_days": 3650, **extra}


def _rows(store: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    return store.query(cypher, params, read_only=True)


async def test_a_ac_45_fixture_pr_maps_to_documented_nodes_and_links(fake_github: FakeGithub, store: Any,
                                                                    ws: str) -> None:
    """A-AC-45: PR with files, commits, two reviews, five review comments (one chain), two comments."""
    info = build_pr_fixture(fake_github)
    # The ingested clone knows the first commit only; the others are created with inClone=false.
    store.upsert_nodes("CodeRepository", [{"id": ids.code_repo(REPO), "name": "widgets", "url": "x",
                                           "defaultBranch": "main", "headSha": "f" * 40}])
    run = await drive(github, ws, _config())
    assert not run.partial, run.partial
    n = store.count
    assert n("GithubRepository") == 1 and n("GithubOrganization") == 0
    assert n("GithubPullRequest") == 1 and n("GithubPullRequestFile") == 2
    assert n("GithubReview") == 2 and n("GithubReviewComment") == 5 and n("GithubIssueComment") == 2
    assert n("GithubIssue") == 1 and n("GithubLabel") == 1 and n("GithubMilestone") == 1
    assert n("GithubRelease") == 1 and n("GithubBranch") >= 2
    assert n("GithubCheckRun") == 1 and n("GithubWorkflowRun") == 1
    pr = store.get_node(ids.github_pr(REPO, info["number"]))
    assert pr is not None
    assert pr["title"] == "Add retry to sync" and pr["merged"] is True and pr["state"] == "closed"
    assert pr["headRef"] == "retry-sync" and pr["headSha"] == info["head_sha"]
    assert pr["mergeCommitSha"] == "c" * 40 and pr["additions"] == 12 and pr["changedFiles"] == 2
    assert pr["url"].endswith("/pull/7") and pr["body"] == "Fixes #3. See ENG-12."

    def edge(rel: str, a: str, b: str) -> int:
        rows = _rows(store, f"MATCH (a:{a})-[r:{rel}]->(b:{b}) RETURN count(r) AS c")
        return int(rows[0]["c"])

    expected = {
        ("PR_IN_REPO", "GithubPullRequest", "GithubRepository"): 1,
        ("OPENED_BY", "GithubPullRequest", "GithubUser"): 1,
        ("MERGED_BY", "GithubPullRequest", "GithubUser"): 1,
        ("PR_ASSIGNED_TO", "GithubPullRequest", "GithubUser"): 1,
        ("REVIEW_REQUESTED_FROM", "GithubPullRequest", "GithubUser"): 1,
        ("PR_HAS_LABEL", "GithubPullRequest", "GithubLabel"): 1,
        ("PR_IN_MILESTONE", "GithubPullRequest", "GithubMilestone"): 1,
        ("FROM_BRANCH", "GithubPullRequest", "GithubBranch"): 1,
        ("INTO_BRANCH", "GithubPullRequest", "GithubBranch"): 1,
        ("CHANGES_FILE", "GithubPullRequest", "GithubPullRequestFile"): 2,
        ("INCLUDES_COMMIT", "GithubPullRequest", "GitCommit"): 2,
        ("HAS_REVIEW", "GithubPullRequest", "GithubReview"): 2,
        ("REVIEWED_BY", "GithubReview", "GithubUser"): 2,
        ("COMMENTS_ON_PR", "GithubReviewComment", "GithubPullRequest"): 5,
        ("PART_OF_REVIEW", "GithubReviewComment", "GithubReview"): 5,
        ("REPLIES_TO", "GithubReviewComment", "GithubReviewComment"): 2,
        ("REVIEW_COMMENT_BY", "GithubReviewComment", "GithubUser"): 5,
        ("COMMENTS_ON_FILE", "GithubReviewComment", "GithubPullRequestFile"): 5,
        ("PR_DISCUSSED_IN", "GithubPullRequest", "GithubIssueComment"): 2,
        ("COMMENT_BY", "GithubIssueComment", "GithubUser"): 2,
        ("ISSUE_OPENED_BY", "GithubIssue", "GithubUser"): 1,
        ("LABEL_IN_REPO", "GithubLabel", "GithubRepository"): 1,
        ("CHECK_FOR_PR", "GithubCheckRun", "GithubPullRequest"): 1,
        ("CHECK_PART_OF_RUN", "GithubCheckRun", "GithubWorkflowRun"): 1,
        ("RUN_FOR_PR", "GithubWorkflowRun", "GithubPullRequest"): 1,
        ("COLLABORATES_ON", "GithubUser", "GithubRepository"): 2,
        ("RELEASED_BY", "GithubRelease", "GithubUser"): 1,
    }
    for (rel, a, b), want in expected.items():
        assert edge(rel, a, b) == want, (rel, edge(rel, a, b), want)
    # PR file: hunks parsed from the patch; rename recorded
    pf = store.get_node(ids.github_prfile(REPO, 7, "src/new_name.py"))
    assert pf is not None and pf["previousPath"] == "src/old_name.py" and pf["status"] == "renamed"
    sync = store.get_node(ids.github_prfile(REPO, 7, "src/sync.py"))
    assert sync is not None and sync["hunks"] == ["10-14", "42-45"]
    # Commits not in the clone are API-created with inClone=false
    commit = store.get_node(ids.git_commit(REPO, "d" * 40))
    assert commit is not None and commit["inClone"] is False and commit["subject"] == "Add retry"
    assert commit["authorEmail"] == "alice@example.com"
    # Raw text kept for linking: the reference "ENG-12" lives in the body
    assert "ENG-12" in pr["body"]


async def test_merged_as_gets_a_target_when_commit_is_missing_from_clone(fake_github: FakeGithub, store: Any,
                                                                       ws: str) -> None:
    info = build_pr_fixture(fake_github)
    fake_github.commits[REPO]["c" * 40] = {
        "sha": "c" * 40, "commit": {"message": "Merge pull request #7", "author": {
            "name": "Bob", "email": "bob@example.com", "date": "2026-03-02T10:00:00Z"}, "committer": {}},
        "parents": [{"sha": "1" * 40}, {"sha": "2" * 40}]}
    await drive(github, ws, _config(), steps=["repo", "pulls"])
    rows = _rows(store, "MATCH (p:GithubPullRequest)-[:MERGED_AS]->(c:GitCommit) RETURN c.id AS id, "
                 "c.inClone AS inClone, c.isMerge AS isMerge")
    assert rows == [{"id": ids.git_commit(REPO, "c" * 40), "inClone": False, "isMerge": True}]
    assert info["number"] == 7


async def test_org_owner_creates_organisation_and_fork_of(fake_github: FakeGithub, store: Any, ws: str) -> None:
    fake_github.add_repo("orgx/lib", repo_id=200, owner_type="Organization")
    fake_github.add_repo("me/lib", repo_id=300, fork=True, parent="orgx/lib")
    await drive(github, ws, {"repository": "orgx/lib", "token": "t", "api_url": "http://fake.github"},
                steps=["repo", "org"])
    assert store.count("GithubOrganization") == 1
    rows = _rows(store, "MATCH (r:GithubRepository)-[:BELONGS_TO_ORG]->(o:GithubOrganization) RETURN o.login AS l")
    assert rows == [{"l": "orgx"}]
    await drive(github, ws, {"repository": "me/lib", "token": "t", "api_url": "http://fake.github"},
                steps=["repo"])
    rows = _rows(store, "MATCH (a:GithubRepository)-[:FORK_OF]->(b:GithubRepository) "
                 "RETURN a.fullName AS a, b.fullName AS b")
    assert rows == [{"a": "me/lib", "b": "orgx/lib"}]


async def test_collaborators_403_falls_back_to_contributors(fake_github: FakeGithub, store: Any, ws: str) -> None:
    fake_github.add_repo(REPO, repo_id=100)
    fake_github.collaborators_forbidden.add(REPO)
    from tests.fakes.github import user

    fake_github.contributors[REPO] = [user(21, "carol")]
    await drive(github, ws, _config(), steps=["repo", "contributors"])
    assert [r["login"] for r in _rows(store, "MATCH (u:GithubUser) RETURN u.login AS login")] == ["carol"]


async def test_anonymous_collaborators_401_falls_back_to_contributors(
    fake_github: FakeGithub, store: Any, ws: str
) -> None:
    """A-AC-47: without a token the run still reads public contributors instead of failing on 401."""
    fake_github.add_repo(REPO, repo_id=100)
    fake_github.collaborators_need_auth.add(REPO)
    from tests.fakes.github import user

    fake_github.contributors[REPO] = [user(22, "dave")]
    await drive(github, ws, _config(), steps=["repo", "contributors"])
    assert [r["login"] for r in _rows(store, "MATCH (u:GithubUser) RETURN u.login AS login")] == ["dave"]


async def test_upstream_history_is_read_for_both_repositories(fake_github: FakeGithub, store: Any, ws: str) -> None:
    """A-AC-105: upstream pulls and reviews land in the same graph, per-repository cursor, re-run adds nothing."""
    from tests.fakes.github import user

    fake_github.add_repo("me/widgets", repo_id=300, fork=True, parent="acme/widgets")
    build_pr_fixture(fake_github, "acme/widgets")
    fake_github.add_pull("me/widgets", 1, title="Fork PR", author=user(11, "alice"),
                         updated_at="2026-03-05T00:00:00Z")
    config = {"repository": "me/widgets", "upstream": "acme/widgets", "token": "t",
              "api_url": "http://fake.github", "history_days": 3650}
    run = await drive(github, ws, config)
    assert store.get_node(ids.github_pr("acme/widgets", 7)) is not None
    assert store.get_node(ids.github_pr("me/widgets", 1)) is not None
    assert set(run.cursor) >= {"me/widgets", "acme/widgets"}
    assert run.cursor["acme/widgets"]["pulls_updated"] == "2026-03-02T10:00:00Z"
    assert store.count("GithubLabel") == 1  # labels are ingested for the ingested repo only (it has none)
    before = store.count()
    await drive(github, ws, config, cursor=run.cursor)
    assert store.count() == before


# A-AC-48: cross-source links need a code snapshot
def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                         env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                              "GIT_COMMITTER_EMAIL": "t@e", "PATH": "/usr/bin:/bin:/usr/local/bin",
                              "HOME": str(cwd)})
    return res.stdout.strip()


SYNC_PY = """\
import os


def helper():
    return 1


def run(items):
    out = []
    for item in items:
        out.append(item)
    return out


def other():
    return 2
"""


@pytest.fixture
def clone(ws: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    base = tmp_path / "clones"
    monkeypatch.setenv("ACTRON_CLONE_DIR", str(base))
    get_settings.cache_clear()
    repo_dir = base / ws / "acme__widgets"
    repo_dir.mkdir(parents=True)
    _git(repo_dir, "init", "-q", "-b", "main")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "sync.py").write_text(SYNC_PY)
    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-q", "-m", "initial")
    first = _git(repo_dir, "rev-parse", "HEAD")
    yield {"dir": repo_dir, "first": first}
    get_settings.cache_clear()


def _snapshot(store: Any, path: str, fns: dict[str, tuple[int, int]], *, deleted: bool = False) -> None:
    store.upsert_nodes("CodeFile", [{"id": ids.code_file(REPO, path), "path": path, "contentHash": "h"}])
    rows = [{"id": ids.code_fn(REPO, path, q), "name": q.split(".")[-1], "qualifiedName": q, "startLine": s,
             "endLine": e, "body": "x", "contentHash": "h"} for q, (s, e) in fns.items()]
    store.upsert_nodes("CodeFunction", rows)
    if deleted:
        store.tombstone("CodeFunction", [r["id"] for r in rows])


async def test_a_ac_48_pr_touched_and_comment_on_function_confidences(fake_github: FakeGithub, store: Any,
                                                                    ws: str, clone: dict[str, Any]) -> None:
    """A-AC-48: PR_TOUCHED 0.9; COMMENT_ON_FUNCTION 0.8 (no rename) from the file at the comment's commit."""
    build_pr_fixture(fake_github, head_sha=clone["first"], commit_id=clone["first"])
    _snapshot(store, "src/sync.py", {"helper": (4, 5), "run": (8, 13), "other": (16, 17)})
    # hunks are 10-14 and 42-45: only `run` (8-13) overlaps lines 10-13, and nothing overlaps 42-45
    await drive(github, ws, _config())
    touched = _rows(store, "MATCH (p:GithubPullRequest)-[r:PR_TOUCHED]->(f:CodeFunction) "
                    "RETURN f.id AS id, r.confidence AS c, r.linesChanged AS n, r.method AS m")
    assert touched == [{"id": ids.code_fn(REPO, "src/sync.py", "run"), "c": 0.9, "n": 4, "m": "structural"}]
    on_fn = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_FUNCTION]->(f:CodeFunction) "
                  "RETURN c.id AS cid, f.id AS fid, r.confidence AS conf")
    fn_run = ids.code_fn(REPO, "src/sync.py", "run")
    by_comment = {r["cid"]: (r["fid"], r["conf"]) for r in on_fn}
    # comments 401, 402, 405 are on line 11 (inside run); 403 is on line 43 (no function there)
    for cid in (401, 402, 405):
        assert by_comment[ids.github_review_comment(cid)] == (fn_run, 0.8)
    assert ids.github_review_comment(403) not in by_comment
    on_file = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_CODE_FILE]->(f:CodeFile) "
                    "RETURN f.id AS fid, r.confidence AS conf")
    assert {(r["fid"], r["conf"]) for r in on_file} == {(ids.code_file(REPO, "src/sync.py"), 0.8)}
    pr_file = _rows(store, "MATCH (a:GithubPullRequestFile)-[r:PR_FILE_IS]->(f:CodeFile) RETURN r.confidence AS c")
    assert pr_file == [{"c": 1.0}]


async def test_comment_on_function_follows_renames(fake_github: FakeGithub, store: Any, ws: str,
                                                   clone: dict[str, Any]) -> None:
    """A-AC-48: a comment on a file that was later moved attaches to today's function (confidence 0.7)."""
    d = clone["dir"]
    (d / "src" / "sync.py").rename(d / "src" / "engine.py")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "move sync to engine")
    build_pr_fixture(fake_github, head_sha=clone["first"], commit_id=clone["first"])
    # snapshot has only the moved file; the old file node is tombstoned with a FILE_RENAMED_TO link
    _snapshot(store, "src/engine.py", {"run": (8, 13)})
    store.upsert_nodes("CodeFile", [{"id": ids.code_file(REPO, "src/sync.py"), "path": "src/sync.py",
                                     "contentHash": "h"}])
    store.tombstone("CodeFile", [ids.code_file(REPO, "src/sync.py")])
    store.upsert_links("FILE_RENAMED_TO", "CodeFile", "CodeFile", [LinkRow(
        ids.code_file(REPO, "src/sync.py"), ids.code_file(REPO, "src/engine.py"),
        {"method": "structural", "confidence": 1.0})])
    await drive(github, ws, _config())
    rows = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_FUNCTION]->(f:CodeFunction) "
                 "RETURN c.id AS cid, f.id AS fid, r.confidence AS conf")
    fn = ids.code_fn(REPO, "src/engine.py", "run")
    assert {(r["fid"], r["conf"]) for r in rows} == {(fn, 0.7)}
    assert len(rows) == 3


async def test_comment_without_commit_maps_on_snapshot_with_lower_confidence(
        fake_github: FakeGithub, store: Any, ws: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No clone: lines are mapped on the current snapshot (confidence 0.5, method inferred) and recorded."""
    monkeypatch.setenv("ACTRON_CLONE_DIR", str(tmp_path / "none"))
    get_settings.cache_clear()
    build_pr_fixture(fake_github, head_sha="9" * 40, commit_id="9" * 40)
    _snapshot(store, "src/sync.py", {"run": (8, 13)})
    run = await drive(github, ws, _config())
    rows = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_FUNCTION]->(f:CodeFunction) "
                 "RETURN r.confidence AS conf, r.method AS m")
    assert rows and all(r == {"conf": 0.5, "m": "inferred"} for r in rows)
    assert any(e["action"] == "comment_on_function" for e in run.errors)
    get_settings.cache_clear()


async def test_comment_on_deleted_function_links_to_tombstone_and_records(
        fake_github: FakeGithub, store: Any, ws: str, clone: dict[str, Any]) -> None:
    build_pr_fixture(fake_github, head_sha=clone["first"], commit_id=clone["first"])
    _snapshot(store, "src/sync.py", {"run": (8, 13)}, deleted=True)
    run = await drive(github, ws, _config())
    rows = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_FUNCTION]->(f:CodeFunction) "
                 "RETURN f.deleted AS d")
    assert rows and all(r["d"] is True for r in rows)
    assert any("tombstone" in e["error"] for e in run.errors)


TS_OLD = """export function parse(input: string): number {
  return input.length
}

export class Reader {
  read(path: string): string {
    return path
  }
}
"""


async def test_a_ac_102_comment_before_a_typescript_file_moved_links_through_the_rename_chain(
        fake_github: FakeGithub, store: Any, ws: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A-AC-102: src/old/name.ts renamed to src/new/name.ts; the comment attaches to today's method, 0.7."""
    base = tmp_path / "clones"
    monkeypatch.setenv("ACTRON_CLONE_DIR", str(base))
    get_settings.cache_clear()
    d = base / ws / "acme__widgets"
    (d / "src" / "old").mkdir(parents=True)
    _git(d, "init", "-q", "-b", "main")
    (d / "src" / "old" / "name.ts").write_text(TS_OLD)
    _git(d, "add", ".")
    _git(d, "commit", "-q", "-m", "initial")
    first = _git(d, "rev-parse", "HEAD")
    (d / "src" / "new").mkdir()
    (d / "src" / "old" / "name.ts").rename(d / "src" / "new" / "name.ts")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "move")
    build_pr_fixture(fake_github, head_sha=first, commit_id=first)
    fake_github.review_comments[REPO] = [review_comment_json(
        901, 7, REPO, path="src/old/name.ts", line=7, body="Why read here?", author=user(12, "bob"),
        commit_id=first, created="2026-03-01T12:00:00Z")]
    _snapshot(store, "src/new/name.ts", {"Reader.read": (6, 8), "parse": (1, 3)})
    await drive(github, ws, _config(), steps=["repo", "pulls", "review_comments"])
    rows = _rows(store, "MATCH (c:GithubReviewComment)-[r:COMMENT_ON_FUNCTION]->(f:CodeFunction) "
                 "RETURN f.id AS fid, r.confidence AS conf")
    assert rows == [{"fid": ids.code_fn(REPO, "src/new/name.ts", "Reader.read"), "conf": 0.7}]
    get_settings.cache_clear()
