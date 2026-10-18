"""Earlier versions of code and commit history for one function or class (spec A, A6.10; spec B `get_code_at`
and `history` tools, B-AC-82).

Earlier versions are never stored as nodes: `get_code_at` reads `git show <sha>:<path>`, re-parses that file
version and slices the symbol's line range at that commit. Both helpers follow `RENAMED_TO` backwards (up to
5 hops) so a function that was renamed or moved still finds its earlier versions and commits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from actron.connectors.code.clone import GitError, clone_dir_for, git
from actron.connectors.code.parse import parse_file
from actron.graph import ids
from actron.graph.store import GraphStore

MAX_RENAME_HOPS = 5


def _repo_dir(store_or_repo_dir: GraphStore | Path | str, repo: str) -> Path:
    if isinstance(store_or_repo_dir, GraphStore):
        from actron.config import get_settings

        return clone_dir_for(get_settings().ACTRON_CLONE_DIR, store_or_repo_dir.workspace_id, repo)
    return Path(store_or_repo_dir)


def _predecessors(store: GraphStore, node_id: str) -> list[str]:
    """Ids this node was renamed from, nearest first."""
    label = ids.label_of(node_id)
    rel = "CLASS_RENAMED_TO" if label == "CodeClass" else "RENAMED_TO"
    rows = store.query(
        f"MATCH p = (old:`{label}`)-[:`{rel}`*1..{MAX_RENAME_HOPS}]->(n:`{label}` {{id: $id}}) "
        "RETURN old.id AS id, length(p) AS d ORDER BY d", {"id": node_id}, read_only=True)
    return [r["id"] for r in rows]


def get_code_at(store_or_repo_dir: GraphStore | Path | str, fn_id: str, sha: str, *,
                repo_dir: Path | None = None) -> dict[str, Any]:
    """The source of a function or class as it was at commit `sha`.

    Returns `{id, sha, path, qualifiedName, startLine, endLine, code, found, reason}`; `found` is false (with
    a reason) when the file or symbol did not exist at that commit.
    """
    parsed = ids.parse_id(fn_id)
    if parsed.label not in ("CodeFunction", "CodeClass"):
        raise ValueError(f"not a function or class id: {fn_id}")
    repo = parsed.parts["repo"]
    directory = repo_dir or _repo_dir(store_or_repo_dir, repo)
    candidates = [fn_id]
    if isinstance(store_or_repo_dir, GraphStore):
        candidates += _predecessors(store_or_repo_dir, fn_id)
    reason = "not found"
    for cand in candidates:
        parts = ids.parse_id(cand).parts
        path, key = parts["path"], parts["qualname"] + (f"~{parts['dup']}" if parts["dup"] != "1" else "")
        try:
            data = git(["show", f"{sha}:{path}"], cwd=directory, timeout=60).stdout
        except GitError:
            reason = f"{path} does not exist at {sha[:12]}"
            continue
        pf = parse_file(path, data)
        sym = next((s for s in (pf.symbols if pf else []) if s.key == key), None)
        if sym is None:
            reason = f"{key} is not in {path} at {sha[:12]}"
            continue
        return {"id": fn_id, "matchedId": cand, "sha": sha, "path": path, "qualifiedName": sym.qualname,
                "startLine": sym.start_line, "endLine": sym.end_line, "code": sym.body, "found": True,
                "reason": None}
    return {"id": fn_id, "matchedId": None, "sha": sha, "path": parsed.parts["path"],
            "qualifiedName": parsed.parts["qualname"], "startLine": None, "endLine": None, "code": None,
            "found": False, "reason": reason}


def history(store: GraphStore, fn_id: str, limit: int = 5, *, follow_renames: bool = True) -> list[dict[str, Any]]:
    """Most recent commits that touched a function (or class), newest first, with author and change type."""
    label = ids.label_of(fn_id)
    if label not in ("CodeFunction", "CodeClass"):
        raise ValueError(f"not a function or class id: {fn_id}")
    rel = "TOUCHED" if label == "CodeFunction" else "TOUCHED_CLASS"
    targets = [fn_id] + (_predecessors(store, fn_id) if follow_renames else [])
    rows = store.query(
        f"UNWIND $ids AS tid MATCH (c:GitCommit)-[t:`{rel}`]->(f:`{label}` {{id: tid}}) "
        "OPTIONAL MATCH (c)-[:AUTHORED_BY]->(a:GitAuthor) "
        "RETURN c.sha AS sha, c.subject AS subject, c.authoredAt AS authoredAt, a.name AS authorName, "
        "a.email AS authorEmail, t.changeType AS changeType, t.linesChanged AS linesChanged, f.id AS functionId "
        "ORDER BY authoredAt DESC, sha LIMIT $n",
        {"ids": targets, "n": int(limit)}, read_only=True)
    return rows
