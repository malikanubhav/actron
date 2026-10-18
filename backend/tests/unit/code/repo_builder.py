"""Builds synthetic git repositories inside tests (tmp_path + `git init`, scripted commits)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent


class SyntheticRepo:
    def __init__(self, root: Path, branch: str = "main") -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", branch)
        self._tick = 0

    def git(self, *args: str, author: tuple[str, str] = ("Ada Lovelace", "ada@example.com")) -> str:
        self._tick = getattr(self, "_tick", 0) + 1
        env = dict(os.environ)
        stamp = f"2026-01-01T00:{self._tick // 60:02d}:{self._tick % 60:02d}+00:00"
        env.update(GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1], GIT_COMMITTER_NAME=author[0],
                   GIT_COMMITTER_EMAIL=author[1], GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        proc = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, env=env,
                              check=True)
        return proc.stdout.strip()

    def write(self, path: str, content: str, *, raw: bool = False) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if raw else dedent(content))

    def write_bytes(self, path: str, data: bytes) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def remove(self, path: str) -> None:
        self.git("rm", "-q", path)

    def move(self, src: str, dst: str) -> None:
        (self.root / dst).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", src, dst)

    def commit(self, message: str, author: tuple[str, str] = ("Ada Lovelace", "ada@example.com")) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message, author=author)
        return self.git("rev-parse", "HEAD")

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    @property
    def url(self) -> str:
        return f"file://{self.root}"
