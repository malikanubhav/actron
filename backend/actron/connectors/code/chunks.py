"""Chunks so that every line of every stored file is in the graph (spec A, A6.5).

Lines outside every function and class are grouped into maximal runs; each run is split into chunks of at
most 80 lines with 10 lines of overlap. Markdown and rst files are covered by document sections instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from actron.connectors.code.languages import chunk_kind, language_for
from actron.connectors.code.model import ParsedFile, split_lines

MAX_LINES = 80
OVERLAP = 10


@dataclass(frozen=True)
class ChunkSpan:
    start: int
    end: int
    kind: str
    text: str


def uncovered_runs(n_lines: int, covered: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    mark = [False] * (n_lines + 2)
    for start, end in covered:
        for i in range(max(1, start), min(n_lines, end) + 1):
            mark[i] = True
    runs: list[tuple[int, int]] = []
    i = 1
    while i <= n_lines:
        if mark[i]:
            i += 1
            continue
        j = i
        while j + 1 <= n_lines and not mark[j + 1]:
            j += 1
        runs.append((i, j))
        i = j + 1
    return runs


def split_run(start: int, end: int, max_lines: int = MAX_LINES, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    s = start
    while True:
        e = min(s + max_lines - 1, end)
        out.append((s, e))
        if e >= end:
            return out
        s = e - overlap + 1


def plan_chunks(path: str, text: str, parsed: ParsedFile | None) -> list[ChunkSpan]:
    if language_for(path).tier == 0:
        return []
    lines = split_lines(text)
    covered = [(s.start_line, s.end_line) for s in parsed.symbols] if parsed is not None else []
    kind = chunk_kind(path, bool(covered) or parsed is not None)
    out: list[ChunkSpan] = []
    for a, b in uncovered_runs(len(lines), covered):
        for s, e in split_run(a, b):
            out.append(ChunkSpan(s, e, kind, "\n".join(lines[s - 1 : e])))
    return out
