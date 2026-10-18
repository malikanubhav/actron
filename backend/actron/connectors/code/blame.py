"""`git blame` on the current snapshot, aggregated per author per function and per file (spec A, A7)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from actron.connectors.code.clone import GitError, git


@dataclass(frozen=True)
class BlameLine:
    line: int  # line number in the current file
    sha: str
    author_name: str
    author_email: str
    author_time: int


def parse_line_porcelain(text: str) -> list[BlameLine]:
    out: list[BlameLine] = []
    sha = ""
    final = 0
    name = ""
    mail = ""
    when = 0
    for raw in text.split("\n"):
        if raw.startswith("\t"):
            out.append(BlameLine(final, sha, name, mail, when))
            continue
        parts = raw.split(" ")
        if len(parts) >= 3 and len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
            sha = parts[0]
            final = int(parts[2])
        elif raw.startswith("author "):
            name = raw[len("author "):]
        elif raw.startswith("author-mail "):
            mail = raw[len("author-mail "):].strip().strip("<>").lower()
        elif raw.startswith("author-time "):
            when = int(raw[len("author-time "):] or 0)
    return out


def read_blame(repo_dir: Path, path: str) -> list[BlameLine]:
    try:
        proc = git(["blame", "--line-porcelain", "HEAD", "--", path], cwd=repo_dir, timeout=300)
    except GitError:
        return []
    return parse_line_porcelain(proc.stdout.decode("utf-8", "replace"))


@dataclass
class Share:
    email: str
    name: str
    lines: int
    line_share: float


def aggregate(blame: list[BlameLine], start: int, end: int) -> list[Share]:
    """Lines per author inside [start, end]; lineShare = lines / (end - start + 1)."""
    loc = max(end - start + 1, 1)
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for b in blame:
        if start <= b.line <= end and b.author_email:
            counts[b.author_email] += 1
            names.setdefault(b.author_email, b.author_name)
    return [Share(email, names[email], n, round(n / loc, 4)) for email, n in sorted(counts.items())]
