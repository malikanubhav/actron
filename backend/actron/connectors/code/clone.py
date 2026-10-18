"""Clone or update the working branch of a repository (spec A, A6.1).

Private repositories authenticate through a `GIT_ASKPASS` helper that reads the token from the subprocess
environment; the token never appears in the command line or the remote URL (A-AC-38).

Decision (recorded in BUILD-LOG.md): the first clone does not use `--filter=blob:none`. With a partial clone
every historical blob needed by hunks, blame and `get_code_at` is fetched on demand, one round trip per commit
(measured on Calva: 2 minutes for 200 commits). A shallow clone with blobs to the history depth took 42 s.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from actron.logging import get_logger

log = get_logger(__name__)

Runner = Callable[..., subprocess.CompletedProcess[bytes]]
TOKEN_ENV = "ACTRON_GIT_TOKEN"
_ASKPASS = """#!/bin/sh
case "$1" in
  Username*) echo "x-access-token" ;;
  *) printf '%s\\n' "$ACTRON_GIT_TOKEN" ;;
esac
"""


class GitError(RuntimeError):
    """A git command failed (the message never contains a token)."""


@dataclass(frozen=True)
class CloneInfo:
    path: Path
    head_sha: str
    branch: str


def strip_credentials(url: str) -> str:
    parts = urlsplit(url)
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return url


def clone_dir_for(base: Path, ws: str, repo: str) -> Path:
    owner, _, name = repo.lower().partition("/")
    return base / ws / f"{owner}__{name}"


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "[REDACTED]") if token else text


def git(args: Sequence[str], *, cwd: Path | None = None, token: str | None = None, timeout: float = 600,
        runner: Runner = subprocess.run, retries: int = 0, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    """Run git with a token supplied only through GIT_ASKPASS and the environment."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop(TOKEN_ENV, None)
    askpass_dir: str | None = None
    if token:
        askpass_dir = tempfile.mkdtemp(prefix="actron-askpass-")
        script = Path(askpass_dir) / "askpass.sh"
        script.write_text(_ASKPASS)
        script.chmod(stat.S_IRWXU)
        env["GIT_ASKPASS"] = str(script)
        env[TOKEN_ENV] = token
    cmd = ["git", *args]
    try:
        attempt = 0
        while True:
            try:
                proc = runner(cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if attempt >= retries:
                    raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
            else:
                if proc.returncode == 0 or not check:
                    return proc
                if attempt >= retries:
                    err = _redact(proc.stderr.decode("utf-8", "replace").strip(), token)
                    raise GitError(f"git {args[0]} failed ({proc.returncode}): {err[-500:]}")
            attempt += 1
            time.sleep(min(2**attempt, 30))
    finally:
        if askpass_dir:
            shutil.rmtree(askpass_dir, ignore_errors=True)


def _out(args: Sequence[str], cwd: Path, runner: Runner = subprocess.run) -> str:
    return git(args, cwd=cwd, runner=runner, timeout=120).stdout.decode().strip()


def clone_or_fetch(url: str, dest: Path, branch: str | None, depth: int, token: str | None = None, *,
                   runner: Runner = subprocess.run) -> CloneInfo:
    """First time: shallow clone of one branch. Later: fetch that branch and reset to it."""
    url = strip_credentials(url)
    depth_args = ["--depth", str(depth)] if depth and depth > 0 else []
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        args = ["clone", "--no-tags", "--single-branch", *depth_args]
        if branch:
            args += ["--branch", branch]
        git([*args, url, str(dest)], token=token, runner=runner, retries=2, timeout=1800)
        if not branch:
            branch = _out(["rev-parse", "--abbrev-ref", "HEAD"], dest, runner)
    else:
        git(["remote", "set-url", "origin", url], cwd=dest, runner=runner)
        if not branch:
            branch = _out(["rev-parse", "--abbrev-ref", "HEAD"], dest, runner)
        git(["fetch", "--no-tags", *depth_args, "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
            cwd=dest, token=token, runner=runner, retries=2, timeout=1800)
        git(["checkout", "-q", "-B", branch, f"refs/remotes/origin/{branch}"], cwd=dest, runner=runner)
        git(["reset", "-q", "--hard", f"refs/remotes/origin/{branch}"], cwd=dest, runner=runner)
    head = _out(["rev-parse", "HEAD"], dest, runner)
    log.info("clone ready", extra={"path": str(dest), "branch": branch, "head": head})
    return CloneInfo(path=dest, head_sha=head, branch=branch)
