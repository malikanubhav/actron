"""Cross-source links from GitHub records to the code snapshot (spec A, A8 "Cross-source links").

Review comments and PR files point at paths and lines as they were when the PR was written. The
graph holds today's snapshot, so this module maps old paths and lines onto current files and
functions: it reads the file at the comment's commit (`git show <sha>:<path>` in the clone), finds
the innermost function at that line, then follows renames (graph `FILE_RENAMED_TO` and
`RENAMED_TO`, plus git's own rename history) to the node that exists now.

When the clone or the commit is not available, it maps on the current snapshot with lower
confidence and says so, so the weaker link can be told apart.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from actron.config import get_settings
from actron.graph import ids
from actron.graph.store import GraphStore
from actron.logging import get_logger

log = get_logger(__name__)

GIT_TIMEOUT = 30
CONF_NO_RENAME = 0.8
CONF_RENAMED = 0.7
CONF_PR_TOUCHED = 0.9
CONF_SNAPSHOT_GUESS = 0.5

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def parse_patch_hunks(patch: str | None) -> list[tuple[int, int]]:
    """New-file line ranges of a unified diff patch. A pure deletion maps to the line before it."""
    if not patch:
        return []
    out: list[tuple[int, int]] = []
    for m in _HUNK_RE.finditer(patch):
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        end = start + count - 1
        out.append((start, max(start, end)))
    return out


def hunks_to_strings(hunks: list[tuple[int, int]]) -> list[str]:
    return [f"{a}-{b}" for a, b in hunks]


def hunks_from_strings(values: list[str] | None) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for v in values or []:
        a, _, b = str(v).partition("-")
        if a.isdigit() and b.isdigit():
            out.append((int(a), int(b)))
    return out


# Symbols in a file (generic; used only for old file versions that are not in the graph)
@dataclass(frozen=True)
class Symbol:
    qualname: str
    name: str
    start: int
    end: int


_LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".go": "go", ".java": "java", ".rs": "rust",
}
_FUNC_TYPES = {
    "python": {"function_definition"},
    "typescript": {"function_declaration", "method_definition", "generator_function_declaration"},
    "tsx": {"function_declaration", "method_definition", "generator_function_declaration"},
    "javascript": {"function_declaration", "method_definition", "generator_function_declaration"},
    "go": {"function_declaration", "method_declaration"},
    "java": {"method_declaration", "constructor_declaration"},
    "rust": {"function_item"},
}
_CONTAINER_TYPES = {
    "python": {"class_definition"},
    "typescript": {"class_declaration"},
    "tsx": {"class_declaration"},
    "javascript": {"class_declaration"},
    "go": set(),
    "java": {"class_declaration", "interface_declaration", "enum_declaration"},
    "rust": {"impl_item", "trait_item"},
}
_CLJ_RE = re.compile(r"^\((?:defn-?|defmacro|defmulti|defmethod|def|defonce)\s+(?:\^\S+\s+)*([^\s()\[\]]+)",
                     re.MULTILINE)


def _text(node: Any, source: bytes) -> str:
    return bytes(source[node.start_byte : node.end_byte]).decode("utf-8", "replace")


def _name_of(node: Any, source: bytes, lang: str) -> str | None:
    named = node.child_by_field_name("name")
    if named is None and node.type == "impl_item":
        named = node.child_by_field_name("type")
    if named is None and node.type == "method_declaration" and lang == "go":
        return None
    return _text(named, source) if named is not None else None


def list_symbols(path: str, text: str) -> list[Symbol]:
    """Functions with dotted qualified names and 1-based line ranges. Unknown languages give []."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".clj", ".cljs", ".cljc", ".edn"):
        return _clojure_symbols(text)
    lang = _LANG_BY_EXT.get(ext)
    if lang is None:
        return []
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(lang)
    except Exception as exc:  # unsupported grammar or missing package
        log.warning("no parser for language", extra={"lang": lang, "error": str(exc)})
        return []
    source = text.encode("utf-8")
    tree = parser.parse(source)
    out: list[Symbol] = []
    funcs, containers = _FUNC_TYPES[lang], _CONTAINER_TYPES[lang]

    def walk(node: Any, prefix: list[str]) -> None:
        for child in node.children:
            t = child.type
            if t in funcs:
                name = _name_of(child, source, lang)
                if name:
                    qual = ".".join([*prefix, name])
                    out.append(Symbol(qual, name, child.start_point[0] + 1, child.end_point[0] + 1))
                    walk(child, [*prefix, name])
                    continue
            elif t in containers:
                name = _name_of(child, source, lang)
                if name:
                    walk(child, [*prefix, name])
                    continue
            elif lang in ("typescript", "tsx", "javascript") and t == "variable_declarator":
                value = child.child_by_field_name("value")
                if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                    name = _name_of(child, source, lang)
                    if name:
                        qual = ".".join([*prefix, name])
                        out.append(Symbol(qual, name, child.start_point[0] + 1, child.end_point[0] + 1))
                        walk(value, [*prefix, name])
                        continue
            walk(child, prefix)

    walk(tree.root_node, [])
    return out


def _clojure_symbols(text: str) -> list[Symbol]:
    out: list[Symbol] = []
    lines = text.split("\n")
    for m in _CLJ_RE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        out.append(Symbol(m.group(1), m.group(1), start, _form_end(lines, start)))
    return out


def _form_end(lines: list[str], start: int) -> int:
    depth = 0
    in_string = False
    for i in range(start - 1, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]
            if in_string:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == ";":
                break
            elif ch == "\\":
                j += 1
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth <= 0:
                    return i + 1
            j += 1
    return len(lines)


def innermost(symbols: list[Symbol], line: int) -> Symbol | None:
    best: Symbol | None = None
    for s in symbols:
        if s.start <= line <= s.end and (best is None or (s.end - s.start) < (best.end - best.start)):
            best = s
    return best


# Git helpers (clone directory)
def clone_dir_for(ws: str, repo: str) -> Path | None:
    base = get_settings().ACTRON_CLONE_DIR / ws
    owner, _, name = repo.partition("/")
    for candidate in (f"{owner}__{name}", f"{owner.lower()}__{name.lower()}"):
        path = base / candidate
        if (path / ".git").exists() or (path / "HEAD").exists():
            return path
    return None


def _git(clone: Path, *args: str, timeout: int = GIT_TIMEOUT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}, check=False,
    )


def git_show(clone: Path, sha: str, path: str) -> str | None:
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        return None
    try:
        res = _git(clone, "show", f"{sha}:{path}")
    except (subprocess.TimeoutExpired, OSError):
        return None
    return res.stdout if res.returncode == 0 else None


def git_has_commit(clone: Path, sha: str) -> bool:
    try:
        return _git(clone, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def git_fetch_commit(clone: Path, sha: str, token: str | None = None) -> bool:
    """Fetch one commit from `origin`. The token reaches git only through a GIT_ASKPASS script."""
    if git_has_commit(clone, sha):
        return True
    env: dict[str, str] = {}
    script: str | None = None
    if token:
        fd, script = tempfile.mkstemp(prefix="askpass-", suffix=".sh")
        with os.fdopen(fd, "w") as fh:
            fh.write('#!/bin/sh\ncase "$1" in\n*sername*) echo x-access-token;;\n*) echo "$ACTRON_GIT_TOKEN";;\nesac\n')
        os.chmod(script, 0o700)
        env = {"GIT_ASKPASS": script, "ACTRON_GIT_TOKEN": token}
    try:
        res = _git(clone, "fetch", "--depth", "1", "--no-tags", "origin", sha, timeout=90, env=env)
        return res.returncode == 0 and git_has_commit(clone, sha)
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        if script:
            os.unlink(script)


@lru_cache(maxsize=16)
def _rename_map(clone: str, head: str) -> dict[str, str]:
    """old path -> newest path from `git log -M`, oldest commit first so chains resolve forward."""
    try:
        res = _git(Path(clone), "log", "--reverse", "--name-status", "-M", "--diff-filter=R", "--format=")
    except (subprocess.TimeoutExpired, OSError):
        return {}
    renames: dict[str, str] = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            renames[parts[1]] = parts[2]
    return renames


def git_rename_target(clone: Path, path: str) -> str | None:
    """Where git history moved `path` to (following chains), or None when it was never renamed."""
    try:
        head = _git(clone, "rev-parse", "HEAD").stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None
    renames = _rename_map(str(clone), head)
    current, seen = path, {path}
    while current in renames and renames[current] not in seen:
        current = renames[current]
        seen.add(current)
    return None if current == path else current


# The code snapshot in the graph
@dataclass
class FnRow:
    id: str
    start: int
    end: int
    qualname: str
    deleted: bool


class Snapshot:
    """Reads of the current code snapshot for one repository (all reads, no writes)."""

    def __init__(self, store: GraphStore, repo: str) -> None:
        self.store = store
        self.repo = repo.lower()
        self._fns: dict[str, list[FnRow]] = {}

    def file(self, path: str) -> dict[str, Any] | None:
        rows = self.store.query("MATCH (f:CodeFile {id: $id}) RETURN f.id AS id, f.deleted AS deleted",
                                {"id": ids.code_file(self.repo, path)}, read_only=True)
        return rows[0] if rows else None

    def functions(self, path: str) -> list[FnRow]:
        if path not in self._fns:
            prefix = f"code:fn:{self.repo}:{path}::"
            rows = self.store.query(
                "MATCH (f:CodeFunction) WHERE f.id STARTS WITH $p "
                "RETURN f.id AS id, f.startLine AS s, f.endLine AS e, f.qualifiedName AS q, f.deleted AS d",
                {"p": prefix}, read_only=True)
            self._fns[path] = [FnRow(r["id"], int(r["s"] or 0), int(r["e"] or 0), r["q"] or "",
                                     bool(r["d"])) for r in rows]
        return self._fns[path]

    def file_renamed_to(self, path: str) -> str | None:
        rows = self.store.query(
            "MATCH (a:CodeFile {id: $id})-[:FILE_RENAMED_TO]->(b:CodeFile) RETURN b.path AS path LIMIT 1",
            {"id": ids.code_file(self.repo, path)}, read_only=True)
        return str(rows[0]["path"]) if rows else None

    def fn_renamed_to(self, fn_id: str) -> str | None:
        rows = self.store.query(
            "MATCH (a:CodeFunction {id: $id})-[:RENAMED_TO]->(b:CodeFunction) RETURN b.id AS id LIMIT 1",
            {"id": fn_id}, read_only=True)
        return str(rows[0]["id"]) if rows else None

    def fn_node(self, fn_id: str) -> dict[str, Any] | None:
        rows = self.store.query("MATCH (f:CodeFunction {id: $id}) RETURN f.id AS id, f.deleted AS deleted",
                                {"id": fn_id}, read_only=True)
        return rows[0] if rows else None


@dataclass
class ResolvedPath:
    path: str
    renamed: bool
    file_id: str | None


def resolve_current_path(snap: Snapshot, path: str, clone: Path | None = None) -> ResolvedPath:
    """Today's path for an old path: the same path when it still exists, else follow renames."""
    node = snap.file(path)
    if node is not None and not node.get("deleted"):
        return ResolvedPath(path, False, node["id"])
    current, seen = path, {path}
    for _ in range(8):
        nxt = snap.file_renamed_to(current)
        if nxt is None and clone is not None:
            nxt = git_rename_target(clone, current)
        if nxt is None or nxt in seen:
            break
        current = nxt
        seen.add(current)
        target = snap.file(current)
        if target is not None and not target.get("deleted"):
            return ResolvedPath(current, True, target["id"])
    if node is not None:  # still there as a tombstone; link to it rather than lose the comment
        return ResolvedPath(path, False, node["id"])
    return ResolvedPath(path, False, None)


@dataclass
class FnLink:
    fn_id: str
    confidence: float
    method: str
    note: str | None = None


def functions_touched(snap: Snapshot, path: str, hunks: list[tuple[int, int]]) -> list[tuple[str, int]]:
    """(function id, changed lines inside it) for hunk ranges overlapping live functions of `path`."""
    out: list[tuple[str, int]] = []
    for fn in snap.functions(path):
        if fn.deleted:
            continue
        lines = 0
        for a, b in hunks:
            lo, hi = max(a, fn.start), min(b, fn.end)
            if lo <= hi:
                lines += hi - lo + 1
        if lines:
            out.append((fn.id, lines))
    return out


def comment_function_link(
    snap: Snapshot, *, path: str, line: int | None, sha: str | None, clone: Path | None,
    token: str | None, resolved: ResolvedPath,
) -> FnLink | None:
    """The function a review comment was about, as it exists today (see module docstring)."""
    if not line:
        return None
    text = None
    if clone is not None and sha and git_fetch_commit(clone, sha, token):
        text = git_show(clone, sha, path)
    if text is not None:
        fn = innermost(list_symbols(path, text), line)
        if fn is None:
            return None
        conf = CONF_RENAMED if resolved.renamed else CONF_NO_RENAME
        old_id = ids.code_fn(snap.repo, path, fn.qualname)
        new_id = ids.code_fn(snap.repo, resolved.path, fn.qualname)
        for fid in (new_id,):
            node = snap.fn_node(fid)
            if node is not None and not node.get("deleted"):
                return FnLink(fid, conf, "structural")
        # follow function renames from the old id
        current, seen = old_id, {old_id}
        for _ in range(8):
            nxt = snap.fn_renamed_to(current)
            if nxt is None or nxt in seen:
                break
            current = nxt
            seen.add(current)
            node = snap.fn_node(current)
            if node is not None and not node.get("deleted"):
                return FnLink(current, CONF_RENAMED, "structural")
        for fid in (new_id, old_id):
            node = snap.fn_node(fid)
            if node is not None:
                return FnLink(fid, CONF_RENAMED if fid != new_id or resolved.renamed else CONF_NO_RENAME,
                              "structural", note="function no longer exists; linked to its tombstone")
        return FnLink("", 0.0, "structural", note="function no longer exists in the snapshot")
    # No clone or commit: guess on today's lines, with lower confidence, and say so.
    for fn_row in snap.functions(resolved.path):
        if not fn_row.deleted and fn_row.start <= line <= fn_row.end:
            return FnLink(fn_row.id, CONF_SNAPSHOT_GUESS, "inferred",
                          note="commit not available; mapped on the current snapshot")
    return None
