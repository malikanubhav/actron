"""`history` and `get_code_at` against a synthetic git repository (spec B, B.C4). B-AC-82."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from actron.graph.store import LinkRow
from actron.mcp_graph.tools import ToolContext, call_tool

pytestmark = pytest.mark.integration

REPO = "synthetic/history"
V1 = "export function addNumbers(a: number, b: number): number {\n  return a + b;\n}\n"
V2 = ("// helpers\n\nexport function addNumbers(a: number, b: number): number {\n  const total = a + b;\n"
      "  return total;\n}\n")
V3 = ("// helpers\n\nexport function sumNumbers(a: number, b: number): number {\n  const total = a + b;\n"
      "  return total;\n}\n\nexport function double(x: number): number {\n  return sumNumbers(x, x);\n}\n")


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


@pytest.fixture
def history_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    readme = repo / "README.md"
    readme.write_text("synthetic\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Start", date="2026-01-01T10:00:00Z")
    shas.append(_git(repo, "rev-parse", "HEAD"))
    src = repo / "src"
    src.mkdir()
    for i, (text, msg) in enumerate([(V1, "Add addNumbers"), (V2, "Use a total"), (V3, "Rename to sumNumbers")]):
        (src / "calc.ts").write_text(text)
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", msg, date=f"2026-0{i + 2}-01T10:00:00Z")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


def _fn(qual: str) -> str:
    return f"code:fn:{REPO}:src/calc.ts::{qual}"


@pytest.fixture
def history_graph(indexed_graph: Any, history_repo: tuple[Path, list[str]]) -> Any:
    _repo, shas = history_repo
    g = indexed_graph
    g.upsert_nodes("CodeRepository", [{"id": f"code:repo:{REPO}", "name": "history", "url": "file:///x",
                                       "defaultBranch": "main", "headSha": shas[-1]}])
    g.upsert_nodes("CodeFunction", [
        {"id": _fn("sumNumbers"), "name": "sumNumbers", "qualifiedName": "sumNumbers", "startLine": 3, "endLine": 6,
         "body": V3.split("\n\n")[1], "contentHash": "s"},
        {"id": _fn("addNumbers"), "name": "addNumbers", "qualifiedName": "addNumbers", "startLine": 3, "endLine": 6,
         "body": "old", "contentHash": "a", "deleted": True},
        {"id": _fn("double"), "name": "double", "qualifiedName": "double", "startLine": 8, "endLine": 10,
         "body": "export function double(x: number): number {\n  return sumNumbers(x, x);\n}", "contentHash": "d"},
    ])
    commits = [{"id": f"git:commit:{REPO}:{sha}", "sha": sha, "shortSha": sha[:7], "subject": subj, "message": subj,
                "authoredAt": f"2026-0{i + 1}-01T10:00:00Z", "authorName": "Fixture"}
               for i, (sha, subj) in enumerate(zip(shas, ["Start", "Add addNumbers", "Use a total",
                                                         "Rename to sumNumbers"], strict=True))]
    g.upsert_nodes("GitCommit", commits)
    touched = [
        (shas[1], _fn("addNumbers"), "added"), (shas[2], _fn("addNumbers"), "modified"),
        (shas[3], _fn("addNumbers"), "deleted"), (shas[3], _fn("sumNumbers"), "added"),
    ]
    g.upsert_links("TOUCHED", "GitCommit", "CodeFunction", [
        LinkRow(f"git:commit:{REPO}:{sha}", fid, {"method": "structural", "confidence": 1.0, "changeType": ct,
                                                   "linesChanged": 3})
        for sha, fid, ct in touched
    ])
    g.upsert_links("RENAMED_TO", "CodeFunction", "CodeFunction", [
        LinkRow(_fn("addNumbers"), _fn("sumNumbers"), {"method": "structural", "confidence": 1.0,
                                                         "commitSha": shas[3], "similarity": 1.0})])
    return g


async def test_history_newest_first_across_rename(history_graph: Any, history_repo: tuple[Path, list[str]]) -> None:
    """B-AC-82: history returns the commits that touched a function newest first, including before the rename."""
    repo, shas = history_repo
    ctx = ToolContext(ws="w", store=history_graph, repo_dir=repo)
    out = await call_tool(ctx, "history", {"id": _fn("sumNumbers")})
    assert [(h["commitSha"], h["name"], h["changeType"]) for h in out] == [
        (shas[3], "sumNumbers", "added"),
        (shas[3], "addNumbers", "deleted"),
        (shas[2], "addNumbers", "modified"),
        (shas[1], "addNumbers", "added"),
    ]
    assert [h["renamed"] for h in out] == [False, True, True, True]


async def test_history_falls_back_to_git_log(history_graph: Any, history_repo: tuple[Path, list[str]]) -> None:
    """B-AC-82: with no TOUCHED links in the graph, history reads `git log -L` from the clone."""
    repo, shas = history_repo
    ctx = ToolContext(ws="w", store=history_graph, repo_dir=repo)
    out = await call_tool(ctx, "history", {"id": _fn("double")})
    assert [h["commitSha"] for h in out] == [shas[3]]
    assert out[0]["subject"] == "Rename to sumNumbers"


async def test_get_code_at_matches_git_show(history_graph: Any, history_repo: tuple[Path, list[str]]) -> None:
    """B-AC-82: get_code_at returns the exact earlier source (checked against `git show`), following the rename,
    and `found: false` when the function did not exist at that commit."""
    repo, shas = history_repo
    ctx = ToolContext(ws="w", store=history_graph, repo_dir=repo)
    at_v2 = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": shas[2][:10]})
    assert at_v2["found"] is True and at_v2["renamed"] is True and at_v2["name"] == "addNumbers"
    shown = _git(repo, "show", f"{shas[2]}:src/calc.ts").split("\n")
    expected = "\n".join(shown[at_v2["startLine"] - 1 : at_v2["endLine"]])
    code = "\n".join(line[7:] for line in at_v2["code"].split("\n"))
    assert code == expected
    assert (at_v2["startLine"], at_v2["endLine"]) == (3, 6)
    at_v1 = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": shas[1]})
    assert at_v1["found"] is True and "return a + b;" in at_v1["code"] and at_v1["startLine"] == 1
    now = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": shas[3]})
    assert now["found"] is True and now["renamed"] is False and "sumNumbers" in now["code"]
    before = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": shas[0]})
    assert before["found"] is False
    unknown = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": "deadbeef"})
    assert unknown["found"] is False
    bad = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": "not-hex!"})
    assert bad["error"]["code"] == "invalid_input"


async def test_get_code_at_without_clone_is_unavailable(history_graph: Any, tmp_path: Path) -> None:
    """B-AC-82: without a local clone the tool says so instead of guessing."""
    ctx = ToolContext(ws="w", store=history_graph, repo_dir=tmp_path / "missing")
    out = await call_tool(ctx, "get_code_at", {"id": _fn("sumNumbers"), "commitSha": "abcdef1"})
    assert out["error"]["code"] == "unavailable"
