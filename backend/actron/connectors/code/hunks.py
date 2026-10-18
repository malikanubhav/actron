"""Hunk parsing and mapping changed lines onto functions and classes (spec A, A7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from actron.connectors.code.clone import git

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int


@dataclass
class FilePatch:
    path: str
    old_path: str | None = None
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False

    def new_ranges(self) -> list[tuple[int, int]]:
        return new_ranges(self.hunks)

    def old_ranges(self) -> list[tuple[int, int]]:
        return [(h.old_start, h.old_start + h.old_len - 1) for h in self.hunks if h.old_len > 0]


@dataclass(frozen=True)
class SymbolRange:
    key: str
    kind: str  # function or class
    start: int
    end: int


@dataclass
class TouchedSymbol:
    key: str
    kind: str
    lines_changed: int


def parse_hunks(diff: str) -> list[Hunk]:
    """`@@ -a,b +c,d @@` headers of one file diff (other lines, `\\ No newline` markers included, are ignored)."""
    out: list[Hunk] = []
    for line in diff.splitlines():
        m = _HUNK.match(line)
        if m:
            a, b, c, d = m.groups()
            out.append(Hunk(int(a), int(b) if b is not None else 1, int(c), int(d) if d is not None else 1))
    return out


def new_ranges(hunks: list[Hunk]) -> list[tuple[int, int]]:
    """Changed line ranges in the new file; a pure deletion maps to the line before it (at least line 1)."""
    out: list[tuple[int, int]] = []
    for h in hunks:
        if h.new_len == 0:
            line = max(h.new_start, 1)
            out.append((line, line))
        else:
            out.append((h.new_start, h.new_start + h.new_len - 1))
    return out


def _unquote(path: str) -> str:
    if path.startswith('"') and path.endswith('"'):
        return path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode(
            "latin-1", "replace").decode("utf-8", "replace")
    return path


def parse_patch(text: str) -> list[FilePatch]:
    """Split a multi-file `git diff`/`git show` patch into files with their hunks."""
    out: list[FilePatch] = []
    cur: FilePatch | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            path = rest
            if rest.startswith("a/") and " b/" in rest:
                path = rest.partition(" b/")[2]
            cur = FilePatch(path=_unquote(path))
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("rename from "):
            cur.old_path = _unquote(line[len("rename from "):])
        elif line.startswith("rename to "):
            cur.path = _unquote(line[len("rename to "):])
        elif line.startswith("+++ "):
            target = line[4:]
            if target != "/dev/null":
                cur.path = _unquote(target)[2:] if _unquote(target).startswith("b/") else _unquote(target)
        elif line.startswith("--- ") and line[4:] != "/dev/null" and not cur.hunks:
            src = _unquote(line[4:])
            src = src[2:] if src.startswith("a/") else src
            if cur.old_path is None and src != cur.path:
                cur.old_path = src
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            cur.binary = True
        elif line.startswith("@@"):
            m = _HUNK.match(line)
            if m:
                a, b, c, d = m.groups()
                cur.hunks.append(Hunk(int(a), int(b) if b is not None else 1, int(c), int(d) if d is not None else 1))
    return out


def read_patches(repo_dir: Path, since_sha: str | None, depth: int) -> dict[str, list[FilePatch]]:
    """One `git log -p --unified=0` stream for the same range as `read_log`, keyed by commit sha."""
    args = ["-c", "core.quotePath=false", "log", "-p", "--unified=0", "-M", "--no-color", "--no-ext-diff",
            "--format=%x1e%H"]
    args += [f"{since_sha}..HEAD"] if since_sha else [f"--max-count={depth}", "HEAD"]
    raw = git(args, cwd=repo_dir, timeout=900).stdout.decode("utf-8", "replace")
    out: dict[str, list[FilePatch]] = {}
    for rec in raw.split("\x1e"):
        if not rec.strip():
            continue
        sha, _, body = rec.partition("\n")
        out[sha.strip()] = parse_patch(body)
    return out


def map_hunks_to_symbols(file_symbols_at_commit: list[SymbolRange], hunks: list[tuple[int, int]]) -> list[TouchedSymbol]:
    """Each changed line goes to the innermost function containing it; lines inside a class but outside its
    methods go to the class. Lines outside every symbol are not mapped."""
    counts: dict[str, int] = {}
    kinds: dict[str, str] = {}
    lines: set[int] = set()
    for s, e in hunks:
        lines.update(range(s, e + 1))
    fns = [r for r in file_symbols_at_commit if r.kind == "function"]
    classes = [r for r in file_symbols_at_commit if r.kind == "class"]
    for line in sorted(lines):
        best: SymbolRange | None = None
        for r in fns:
            if r.start <= line <= r.end and (best is None or r.end - r.start < best.end - best.start):
                best = r
        if best is None:
            for r in classes:
                if r.start <= line <= r.end and (best is None or r.end - r.start < best.end - best.start):
                    best = r
        if best is not None:
            counts[best.key] = counts.get(best.key, 0) + 1
            kinds[best.key] = best.kind
    return [TouchedSymbol(k, kinds[k], n) for k, n in counts.items()]
