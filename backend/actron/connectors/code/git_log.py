"""Read git history (spec A, A7).

`git log --raw --numstat -M -z` gives, per commit, the metadata, file statuses with blob ids, and line counts.
Decision (recorded in BUILD-LOG.md): merge commits are recorded with `isMerge` and their parents but no file
changes; the changes arrive through the merged commits themselves, which `git log` also lists. Commits at the
shallow-clone boundary are recorded without file changes (git would show the whole tree as added).
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from actron.connectors.code.clone import GitError, git

ZERO_SHA = "0" * 40
_FORMAT = "%x1e%H%x00%P%x00%an%x00%ae%x00%aI%x00%cI%x00%s%x00%b%x00"
_STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "added", "T": "modified"}


@dataclass
class FileChange:
    status: str  # added, modified, deleted, renamed
    path: str
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False
    old_blob: str | None = None
    new_blob: str | None = None
    similarity: float | None = None


@dataclass
class CommitRecord:
    sha: str
    parents: list[str]
    author_name: str
    author_email: str
    authored_at: str
    committed_at: str
    subject: str
    body: str
    changes: list[FileChange] = field(default_factory=list)
    is_boundary: bool = False

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def message(self) -> str:
        return f"{self.subject}\n\n{self.body}".strip() if self.body.strip() else self.subject

    @property
    def additions(self) -> int:
        return sum(c.additions for c in self.changes)

    @property
    def deletions(self) -> int:
        return sum(c.deletions for c in self.changes)


def shallow_boundary(repo_dir: Path) -> set[str]:
    f = repo_dir / ".git" / "shallow"
    if not f.exists():
        return set()
    return {line.strip() for line in f.read_text().splitlines() if line.strip()}


def parse_log_output(raw: bytes, boundary: set[str] | None = None) -> list[CommitRecord]:
    out: list[CommitRecord] = []
    boundary = boundary or set()
    for rec in raw.split(b"\x1e"):
        if not rec.strip(b"\x00\n"):
            continue
        parts = rec.split(b"\x00", 8)
        if len(parts) < 8:
            continue
        dec = [p.decode("utf-8", "replace") for p in parts[:8]]
        sha, parents, an, ae, ad, cd, subject, body = dec
        commit = CommitRecord(sha=sha.strip(), parents=parents.split(), author_name=an, author_email=ae,
                              authored_at=ad, committed_at=cd, subject=subject, body=body.strip())
        commit.is_boundary = commit.sha in boundary
        rest = parts[8] if len(parts) > 8 else b""
        changes = _parse_changes(rest)
        if not commit.is_merge and not commit.is_boundary:
            commit.changes = changes
        out.append(commit)
    return out


def _parse_changes(rest: bytes) -> list[FileChange]:
    tokens = [t.decode("utf-8", "surrogateescape") for t in rest.split(b"\x00")]
    by_path: dict[str, FileChange] = {}
    order: list[FileChange] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].lstrip("\n")
        if not tok:
            i += 1
            continue
        if tok.startswith(":"):
            meta = tok[1:].split()
            if len(meta) < 5:
                i += 1
                continue
            old_blob, new_blob, status = meta[2], meta[3], meta[4]
            letter = status[0]
            if letter in ("R", "C"):
                old, new = tokens[i + 1], tokens[i + 2]
                i += 3
            else:
                old = new = tokens[i + 1]
                i += 2
            fc = FileChange(
                status=_STATUS.get(letter, "modified"), path=new,
                old_path=old if letter in ("R", "C") else None,
                old_blob=None if old_blob == ZERO_SHA else old_blob,
                new_blob=None if new_blob == ZERO_SHA else new_blob,
                similarity=int(status[1:]) / 100 if letter in ("R", "C") and status[1:].isdigit() else None,
            )
            if letter == "D":
                fc.new_blob = None
            by_path[new] = fc
            order.append(fc)
            continue
        if "\t" in tok:
            add, _, rest_tok = tok.partition("\t")
            dele, _, path = rest_tok.partition("\t")
            if path == "":  # rename: old and new paths follow
                path = tokens[i + 2] if i + 2 < len(tokens) else ""
                i += 3
            else:
                i += 1
            fc2 = by_path.get(path)
            if fc2 is not None:
                if add == "-" and dele == "-":
                    fc2.is_binary = True
                else:
                    fc2.additions = int(add) if add.isdigit() else 0
                    fc2.deletions = int(dele) if dele.isdigit() else 0
            continue
        i += 1
    return order


def is_ancestor(repo_dir: Path, ancestor: str, head: str = "HEAD") -> bool:
    proc = git(["merge-base", "--is-ancestor", ancestor, head], cwd=repo_dir, check=False, timeout=60)
    return proc.returncode == 0


def read_log(repo_dir: Path, since_sha: str | None, depth: int) -> Iterator[CommitRecord]:
    """Commits newest first: `since_sha..HEAD` when a cursor is given, else the last `depth` commits."""
    args = ["-c", "core.quotePath=false", "log", f"--format={_FORMAT}", "--raw", "--numstat", "-M", "-z",
            "--no-abbrev", "--no-color"]
    if since_sha:
        args.append(f"{since_sha}..HEAD")
    else:
        args += [f"--max-count={depth}", "HEAD"]
    raw = git(args, cwd=repo_dir, timeout=900).stdout
    yield from parse_log_output(raw, shallow_boundary(repo_dir))


def head_sha(repo_dir: Path) -> str:
    return git(["rev-parse", "HEAD"], cwd=repo_dir, timeout=60).stdout.decode().strip()


@dataclass
class RefRecord:
    kind: str  # branch, tag
    name: str
    sha: str
    is_remote: bool = False
    tagged_at: str | None = None
    message: str | None = None


def read_refs(repo_dir: Path) -> list[RefRecord]:
    fmt = "%(refname)%00%(objectname)%00%(*objectname)%00%(taggerdate:iso-strict)%00%(contents:subject)"
    raw = git(["for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes", "refs/tags"], cwd=repo_dir,
              timeout=120).stdout.decode("utf-8", "replace")
    out: list[RefRecord] = []
    for line in raw.splitlines():
        parts = line.split("\x00")
        if len(parts) < 5:
            continue
        ref, obj, peeled, tdate, subject = parts[:5]
        if ref.endswith("/HEAD"):
            continue
        if ref.startswith("refs/tags/"):
            out.append(RefRecord("tag", ref[len("refs/tags/"):], peeled or obj, tagged_at=tdate or None,
                                 message=subject or None))
        elif ref.startswith("refs/remotes/"):
            name = ref[len("refs/remotes/"):].split("/", 1)[-1]
            out.append(RefRecord("branch", name, obj, is_remote=True))
        elif ref.startswith("refs/heads/"):
            out.append(RefRecord("branch", ref[len("refs/heads/"):], obj, is_remote=False))
    return out


class BlobReader:
    """Reads blobs through one long-running `git cat-file --batch` process."""

    def __init__(self, repo_dir: Path) -> None:
        self._proc = subprocess.Popen(["git", "-C", str(repo_dir), "cat-file", "--batch"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._lock = threading.Lock()

    def read(self, obj: str) -> bytes | None:
        """`obj` is a blob id or `<rev>:<path>`."""
        assert self._proc.stdin is not None and self._proc.stdout is not None
        with self._lock:
            self._proc.stdin.write(obj.encode("utf-8", "surrogateescape") + b"\n")
            self._proc.stdin.flush()
            header = self._proc.stdout.readline()
            if not header or header.endswith(b"missing\n") or b" " not in header:
                return None
            fields = header.split()
            if len(fields) < 3 or fields[1] != b"blob":
                if len(fields) >= 3 and fields[2].isdigit():
                    self._proc.stdout.read(int(fields[2]) + 1)
                return None
            size = int(fields[2])
            data = self._proc.stdout.read(size)
            self._proc.stdout.read(1)
            return data

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()

    def __enter__(self) -> BlobReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["BlobReader", "CommitRecord", "FileChange", "GitError", "RefRecord", "head_sha", "is_ancestor",
           "parse_log_output", "read_log", "read_refs"]
