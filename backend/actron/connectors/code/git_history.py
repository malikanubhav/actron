"""Git history into the graph: commits, authors, file changes, TOUCHED by hunks, renames, refs, blame
(spec A, A7 and the rename part of A6.10)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from actron.connectors.code.blame import aggregate, read_blame
from actron.connectors.code.git_log import BlobReader, CommitRecord, read_refs
from actron.connectors.code.hunks import FilePatch, SymbolRange, map_hunks_to_symbols
from actron.connectors.code.incremental import RenameCandidate, RenameMatch, match_renames
from actron.connectors.code.languages import language_for
from actron.connectors.code.model import ParsedFile, Symbol
from actron.connectors.code.parse import parse_file
from actron.connectors.code.resolve import symbol_id
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow


def parse_time(value: str) -> datetime | str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value


@dataclass
class Touch:
    commit_sha: str
    target_id: str
    kind: str  # function or class
    change_type: str  # added, modified, deleted
    lines: int


@dataclass
class HistoryAnalysis:
    commits: list[CommitRecord] = field(default_factory=list)
    touches: list[Touch] = field(default_factory=list)
    hunks: dict[tuple[str, str], list[str]] = field(default_factory=dict)  # (sha, path) -> ["s-e"]
    renames: list[RenameMatch] = field(default_factory=list)
    file_renames: list[tuple[str, str, str, float]] = field(default_factory=list)  # old, new, sha, sim
    last_touch: dict[str, tuple[str, str]] = field(default_factory=dict)  # symbol id -> (sha, time)
    last_file_change: dict[str, tuple[str, str]] = field(default_factory=dict)  # path -> (sha, time)


class _ParseCache:
    def __init__(self, blobs: BlobReader, size: int = 4096) -> None:
        self.blobs = blobs
        self.cache: OrderedDict[tuple[str, str], ParsedFile | None] = OrderedDict()
        self.size = size

    def get(self, blob: str | None, path: str) -> ParsedFile | None:
        if not blob:
            return None
        key = (blob, language_for(path).name)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        data = self.blobs.read(blob)
        pf = parse_file(path, data) if data is not None and b"\x00" not in data[:8192] else None
        self.cache[key] = pf
        if len(self.cache) > self.size:
            self.cache.popitem(last=False)
        return pf


def _ranges(pf: ParsedFile | None) -> list[SymbolRange]:
    if pf is None:
        return []
    return [SymbolRange(s.key, s.kind, s.start_line, s.end_line) for s in pf.symbols]


def analyze_history(repo: str, repo_dir: Path, commits: list[CommitRecord], patches: dict[str, list[FilePatch]],
                    *, detect_renames: bool = True) -> HistoryAnalysis:
    """Map each commit's hunks onto the symbols of the file at that commit (and its parent for added/deleted)."""
    out = HistoryAnalysis(commits=commits)
    with BlobReader(repo_dir) as blobs:
        cache = _ParseCache(blobs)
        for commit in commits:  # newest first
            if not commit.changes:
                continue
            by_path = {p.path: p for p in patches.get(commit.sha, [])}
            deleted_syms: list[RenameCandidate] = []
            added_syms: list[RenameCandidate] = []
            for fc in commit.changes:
                patch = by_path.get(fc.path)
                if patch is not None and patch.hunks:
                    out.hunks[(commit.sha, fc.path)] = [f"{s}-{e}" for s, e in patch.new_ranges()]
                out.last_file_change.setdefault(fc.path, (commit.sha, commit.authored_at))
                if fc.status == "renamed" and fc.old_path:
                    out.file_renames.append((fc.old_path, fc.path, commit.sha, fc.similarity or 1.0))
                lang = language_for(fc.path)
                if fc.is_binary or lang.tier not in (1, 2):
                    continue
                old_path = fc.old_path or fc.path
                new_pf = cache.get(fc.new_blob, fc.path) if fc.status != "deleted" else None
                old_pf = cache.get(fc.old_blob, old_path) if fc.status != "added" else None
                new_keys = {s.key: s for s in new_pf.symbols} if new_pf else {}
                old_keys = {s.key: s for s in old_pf.symbols} if old_pf else {}
                if patch is None or not patch.hunks:
                    if fc.status == "renamed" and old_pf and new_pf:
                        continue  # pure rename: no line changes
                    if fc.status not in ("added", "deleted"):
                        continue
                    new_rng = [(1, max((s.end_line for s in new_keys.values()), default=0))] if new_keys else []
                else:
                    new_rng = patch.new_ranges()
                for t in map_hunks_to_symbols(_ranges(new_pf), new_rng):
                    sym = new_keys[t.key]
                    sid = symbol_id(repo, fc.path, sym)
                    change = "modified" if t.key in old_keys else "added"
                    out.touches.append(Touch(commit.sha, sid, t.kind, change, t.lines_changed))
                    out.last_touch.setdefault(sid, (commit.sha, commit.authored_at))
                    if change == "added":
                        added_syms.append(RenameCandidate(sid, sym))
                for key, sym in old_keys.items():
                    if key in new_keys:
                        continue
                    sid = symbol_id(repo, old_path, sym)
                    out.touches.append(Touch(commit.sha, sid, sym.kind, "deleted", sym.loc))
                    deleted_syms.append(RenameCandidate(sid, sym))
                if fc.status == "renamed" and fc.old_path:
                    # symbols kept in a moved file are moves too (same key, new path)
                    for key, sym in new_keys.items():
                        if key in old_keys:
                            old_id = symbol_id(repo, old_path, old_keys[key])
                            new_id = symbol_id(repo, fc.path, sym)
                            out.renames.append(RenameMatch(old_id, new_id, sym.kind, 1.0, commit.sha))
            if detect_renames and deleted_syms and added_syms:
                out.renames.extend(match_renames(deleted_syms, added_syms, commit.sha))
    return out


@dataclass
class GitWriteResult:
    commits: int = 0
    authors: int = 0
    file_changes: int = 0
    touched: int = 0
    touched_class: int = 0
    renames: int = 0
    file_renames: int = 0
    branches: int = 0
    tags: int = 0


def write_history(store: GraphStore, repo: str, analysis: HistoryAnalysis, existing_fn: set[str],
                  existing_cls: set[str], existing_files: set[str], current_paths: set[str]) -> GitWriteResult:
    res = GitWriteResult()
    repo_id = ids.code_repo(repo)
    commits = analysis.commits
    if commits:
        rows: list[dict[str, Any]] = []
        authors: dict[str, dict[str, Any]] = {}
        for c in commits:
            rows.append({
                "id": ids.git_commit(repo, c.sha), "sha": c.sha, "shortSha": c.sha[:7], "subject": c.subject,
                "message": c.message, "authorName": c.author_name, "authorEmail": c.author_email,
                "authoredAt": parse_time(c.authored_at), "committedAt": parse_time(c.committed_at),
                "isMerge": c.is_merge, "parentShas": c.parents, "additions": c.additions,
                "deletions": c.deletions, "filesChanged": len(c.changes), "inClone": True,
            })
            if c.author_email:
                authors.setdefault(c.author_email.lower(), {"id": ids.git_author(c.author_email),
                                                            "email": c.author_email.lower(), "name": c.author_name})
        res.commits = store.upsert_nodes("GitCommit", rows)
        res.authors = store.upsert_nodes("GitAuthor", list(authors.values()))
        st = {"method": "structural", "confidence": 1.0}
        store.upsert_links("COMMIT_IN_REPO", "GitCommit", "CodeRepository",
                           [LinkRow(r["id"], repo_id, st) for r in rows])
        store.upsert_links("AUTHORED_BY", "GitCommit", "GitAuthor",
                           [LinkRow(ids.git_commit(repo, c.sha), ids.git_author(c.author_email), st)
                            for c in commits if c.author_email])
        store.upsert_links("HAS_PARENT", "GitCommit", "GitCommit",
                           [LinkRow(ids.git_commit(repo, c.sha), ids.git_commit(repo, p), st)
                            for c in commits for p in c.parents])
        changes: list[dict[str, Any]] = []
        for c in commits:
            for fc in c.changes:
                changes.append({
                    "id": ids.git_change(repo, c.sha, fc.path), "path": fc.path, "oldPath": fc.old_path,
                    "status": fc.status, "additions": fc.additions, "deletions": fc.deletions,
                    "isBinary": fc.is_binary, "hunks": analysis.hunks.get((c.sha, fc.path), []),
                    "_commit": ids.git_commit(repo, c.sha),
                })
        res.file_changes = store.upsert_nodes("GitFileChange", [{k: v for k, v in r.items() if k != "_commit"}
                                                                 for r in changes])
        store.upsert_links("HAS_FILE_CHANGE", "GitCommit", "GitFileChange",
                           [LinkRow(r["_commit"], r["id"], st) for r in changes])
        store.upsert_links("CHANGE_OF_FILE", "GitFileChange", "CodeFile",
                           [LinkRow(r["id"], ids.code_file(repo, r["path"]), st)
                            for r in changes if r["path"] in current_paths])
        fn_rows: dict[tuple[str, str], LinkRow] = {}
        cls_rows: dict[tuple[str, str], LinkRow] = {}
        for t in analysis.touches:
            cid = ids.git_commit(repo, t.commit_sha)
            props = {"method": "structural", "confidence": 1.0, "changeType": t.change_type,
                     "linesChanged": t.lines}
            if t.kind == "function" and t.target_id in existing_fn:
                fn_rows[(cid, t.target_id)] = LinkRow(cid, t.target_id, props)
            elif t.kind == "class" and t.target_id in existing_cls:
                cls_rows[(cid, t.target_id)] = LinkRow(cid, t.target_id, props)
        res.touched = store.upsert_links("TOUCHED", "GitCommit", "CodeFunction", list(fn_rows.values())).created
        res.touched_class = store.upsert_links("TOUCHED_CLASS", "GitCommit", "CodeClass",
                                               list(cls_rows.values())).created
        _recount_authors(store)
    # renames: only between nodes that exist (old tombstoned, new current)
    fr = [LinkRow(ids.code_file(repo, old), ids.code_file(repo, new),
                  {"method": "structural", "confidence": sim, "commitSha": sha, "similarity": sim})
          for old, new, sha, sim in analysis.file_renames
          if ids.code_file(repo, old) in existing_files and ids.code_file(repo, new) in existing_files and old != new]
    if fr:
        res.file_renames = store.upsert_links("FILE_RENAMED_TO", "CodeFile", "CodeFile", fr).created
    return res


def usable_renames(analysis: HistoryAnalysis, existing_fn: set[str], existing_cls: set[str]) -> list[RenameMatch]:
    """Compose rename chains (oldest commit first) and keep pairs whose endpoints both exist."""
    existing = existing_fn | existing_cls
    forward: dict[str, RenameMatch] = {}
    for m in reversed(analysis.renames):  # oldest first
        forward[m.old_id] = m
    out: list[RenameMatch] = []
    for start, m in forward.items():
        if start not in existing:
            continue
        cur = m
        hops = 0
        while cur.new_id not in existing and cur.new_id in forward and hops < 10:
            cur = forward[cur.new_id]
            hops += 1
        if cur.new_id in existing and cur.new_id != start:
            out.append(RenameMatch(start, cur.new_id, m.kind, min(m.similarity, cur.similarity), cur.commit_sha))
    return out


def _recount_authors(store: GraphStore) -> None:
    skip = 0
    while True:
        rows = store.query(
            "MATCH (c:GitCommit)-[:AUTHORED_BY]->(a:GitAuthor) WITH a, count(c) AS n, min(c.authoredAt) AS f, "
            "max(c.authoredAt) AS l RETURN a.id AS id, n, f, l ORDER BY id SKIP $s LIMIT 5000",
            {"s": skip}, read_only=True, timeout_ms=60000,
        )
        if rows:
            store.update_nodes("GitAuthor", [{"id": r["id"], "commitCount": int(r["n"]), "firstCommitAt": r["f"],
                                               "lastCommitAt": r["l"]} for r in rows])
        if len(rows) < 5000:
            return
        skip += 5000


def write_refs(store: GraphStore, repo: str, repo_dir: Path, working_branch: str) -> tuple[int, int]:
    refs = read_refs(repo_dir)
    branches: dict[str, dict[str, Any]] = {}
    for r in refs:
        if r.kind != "branch":
            continue
        bid = ids.git_branch(repo, r.name)
        row = branches.setdefault(bid, {"id": bid, "name": r.name, "headSha": r.sha, "isDefault": r.name == working_branch,
                                        "isRemote": r.is_remote})
        if r.is_remote:
            row["headSha"], row["isRemote"] = r.sha, True
    tags: list[dict[str, Any]] = [{"id": ids.git_tag(repo, r.name), "name": r.name, "sha": r.sha,
             "taggedAt": parse_time(r.tagged_at) if r.tagged_at else None, "message": r.message}
            for r in refs if r.kind == "tag"]
    st = {"method": "structural", "confidence": 1.0}
    nb = store.upsert_nodes("GitBranch", list(branches.values()))
    store.upsert_links("GIT_BRANCH_IN_REPO", "GitBranch", "CodeRepository",
                       [LinkRow(b["id"], ids.code_repo(repo), st) for b in branches.values()])
    store.upsert_links("BRANCH_HEAD", "GitBranch", "GitCommit",
                       [LinkRow(b["id"], ids.git_commit(repo, b["headSha"]), st) for b in branches.values()])
    nt = store.upsert_nodes("GitTag", tags)
    store.upsert_links("TAGS_COMMIT", "GitTag", "GitCommit",
                       [LinkRow(t["id"], ids.git_commit(repo, t["sha"]), st) for t in tags])
    return nb, nt


def write_blame(store: GraphStore, repo: str, repo_dir: Path, files: dict[str, list[Symbol]],
                progress: Callable[[int], None] | None = None, workers: int = 8) -> tuple[int, int]:
    """`files`: path -> current symbols. Replaces BLAME_OWNS / BLAME_OWNS_FILE for these files."""
    paths = sorted(files)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        blames = dict(zip(paths, pool.map(lambda p: read_blame(repo_dir, p), paths), strict=True))
    authors: dict[str, dict[str, Any]] = {}
    fn_links: list[LinkRow] = []
    file_links: list[LinkRow] = []
    fn_ids: list[str] = []
    for path in paths:
        blame = blames[path]
        if not blame:
            continue
        n_lines = max(b.line for b in blame)
        for b in blame:
            if b.author_email:
                authors.setdefault(b.author_email, {"id": ids.git_author(b.author_email), "email": b.author_email,
                                                    "name": b.author_name})
        fid = ids.code_file(repo, path)
        for s in aggregate(blame, 1, n_lines):
            file_links.append(LinkRow(ids.git_author(s.email), fid, {"method": "structural", "confidence": 1.0,
                                                                     "lines": s.lines, "lineShare": s.line_share}))
        for sym in files[path]:
            if sym.kind != "function":
                continue
            sid = symbol_id(repo, path, sym)
            fn_ids.append(sid)
            for s in aggregate(blame, sym.start_line, sym.end_line):
                fn_links.append(LinkRow(ids.git_author(s.email), sid, {"method": "structural", "confidence": 1.0,
                                                                       "lines": s.lines, "lineShare": s.line_share}))
    store.upsert_nodes("GitAuthor", list(authors.values()))
    file_ids = [ids.code_file(repo, p) for p in paths]
    for i in range(0, len(file_ids), 500):
        store.query("UNWIND $ids AS x MATCH (:GitAuthor)-[r:BLAME_OWNS_FILE]->(f:CodeFile {id: x}) DELETE r",
                    {"ids": file_ids[i : i + 500]}, timeout_ms=60000)
    for i in range(0, len(fn_ids), 500):
        store.query("UNWIND $ids AS x MATCH (:GitAuthor)-[r:BLAME_OWNS]->(f:CodeFunction {id: x}) DELETE r",
                    {"ids": fn_ids[i : i + 500]}, timeout_ms=60000)
    n_file = store.upsert_links("BLAME_OWNS_FILE", "GitAuthor", "CodeFile", file_links).created
    n_fn = store.upsert_links("BLAME_OWNS", "GitAuthor", "CodeFunction", fn_links).created
    if progress:
        progress(len(paths))
    return n_file, n_fn
