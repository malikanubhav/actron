"""A-AC-38: cloning never exposes the token in process arguments or in the remote URL."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from actron.connectors.code.clone import clone_or_fetch, strip_credentials

TOKEN = "ghp_FAKEfakeFAKEfakeFAKEfake0123456789"


def _make_origin(tmp_path: Path) -> Path:
    src = tmp_path / "origin"
    src.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "a.py").write_text("def f():\n    return 1\n")
    subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.name=T", "-c", "user.email=t@example.com",
                    "commit", "-qm", "init"], check=True)
    return src


def test_token_not_in_argv_or_remote(tmp_path: Path) -> None:
    """A-AC-38"""
    origin = _make_origin(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def spy(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((list(cmd), dict(kwargs.get("env") or {})))
        return subprocess.run(cmd, **kwargs)

    url = f"https://user:{TOKEN}@example.invalid/acme/app.git"
    assert TOKEN not in strip_credentials(url)
    dest = tmp_path / "clones" / "ws" / "acme__app"
    info = clone_or_fetch(f"file://{origin}", dest, "main", 50, TOKEN, runner=spy)
    info2 = clone_or_fetch(f"file://{origin}", dest, "main", 50, TOKEN, runner=spy)
    assert info.head_sha == info2.head_sha and len(info.head_sha) == 40
    assert calls, "git was not called"
    for argv, env in calls:
        assert all(TOKEN not in a for a in argv)
        if any(a in ("clone", "fetch") for a in argv):
            assert env.get("ACTRON_GIT_TOKEN") == TOKEN
            assert env.get("GIT_ASKPASS")
            assert env.get("GIT_TERMINAL_PROMPT") == "0"
    remotes = subprocess.run(["git", "-C", str(dest), "remote", "-v"], capture_output=True, text=True).stdout
    assert TOKEN not in remotes
    config = (dest / ".git" / "config").read_text()
    assert TOKEN not in config


def test_credentials_in_url_are_dropped(tmp_path: Path) -> None:
    """A-AC-38"""
    assert strip_credentials("https://x:secret@github.com/a/b.git") == "https://github.com/a/b.git"
    assert strip_credentials("https://github.com/a/b.git") == "https://github.com/a/b.git"
