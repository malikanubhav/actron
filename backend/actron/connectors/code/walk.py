"""List tracked files and apply skip rules (spec A, A6.2).

Skipped files still get a `CodeFile` (with `isSkipped` and `skipReason`); only their text is not stored.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from actron.connectors.code.languages import ext_of, language_for
from actron.connectors.code.model import sha256_bytes

MAX_BYTES = 1_000_000
BINARY_EXTS = frozenset(
    [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".icns", ".webp", ".tif", ".tiff", ".psd", ".ai", ".eps", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".jar", ".war", ".ear", ".class", ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a", ".lib", ".pyc", ".pyo", ".mp3", ".mp4", ".m4a", ".mov", ".avi", ".webm", ".wav", ".ogg", ".flac", ".sqlite", ".db", ".vsix", ".wasm", ".node", ".dat", ".pkl", ".npy", ".parquet"]
)
LOCK_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock",
                        "yarn.lock", "Gemfile.lock", "composer.lock", "Pipfile.lock"})
GENERATED_DIRS = ("dist", "build", "node_modules", "vendor", "__generated__")


class WalkError(RuntimeError):
    """Listing files in the clone failed."""


@dataclass
class FileEntry:
    path: str
    size: int
    content_hash: str
    data: bytes
    text: str | None  # None when skipped
    is_skipped: bool
    skip_reason: str | None
    language: str
    tier: int

    @property
    def stored(self) -> bool:
        return not self.is_skipped and self.text is not None


def classify(path: str, data: bytes) -> str | None:
    """Return the skip reason for a file, or None when its text is stored."""
    name = PurePosixPath(path).name
    ext = ext_of(path)
    if len(data) > MAX_BYTES:
        return "too_large"
    if ext in BINARY_EXTS or b"\x00" in data[:8192]:
        return "binary"
    if name in LOCK_NAMES or ext == ".lock":
        return "lockfile"
    parts = PurePosixPath(path).parts[:-1]
    if any(p in GENERATED_DIRS for p in parts):
        return "generated"
    lower = name.lower()
    if lower.endswith((".min.js", ".min.css")):
        return "minified"
    head = data[:4096].split(b"\n", 1)[0]
    if b"@generated" in head or b"DO NOT EDIT" in head:
        return "generated"
    if ext in (".js", ".css") and any(len(line) > 1000 for line in data.split(b"\n")):
        return "minified"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        # Not UTF-8: try latin-1 only when it looks like text.
        if sum(1 for b in data[:8192] if b < 9 or 13 < b < 32) > 30:
            return "binary"
    return None


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def git_ls_files(repo_dir: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "ls-files", "-z", "--cached", "--stage"],
            capture_output=True, check=True, timeout=120,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise WalkError(f"git ls-files failed in {repo_dir}: {exc}") from exc
    paths: list[str] = []
    for rec in out.split(b"\x00"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        mode = meta.split(b" ", 1)[0]
        if mode == b"160000":  # submodule
            continue
        paths.append(path.decode("utf-8", errors="surrogateescape"))
    return sorted(set(paths))


def read_entry(repo_dir: Path, path: str) -> FileEntry | None:
    full = repo_dir / path
    try:
        data = os.readlink(full).encode() if full.is_symlink() else full.read_bytes()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None
    return make_entry(path, data)


def make_entry(path: str, data: bytes) -> FileEntry:
    reason = classify(path, data)
    lang = language_for(path)
    return FileEntry(
        path=path,
        size=len(data),
        content_hash=sha256_bytes(data),
        data=data,
        text=None if reason else decode(data),
        is_skipped=reason is not None,
        skip_reason=reason,
        language=lang.name,
        tier=lang.tier,
    )


def walk(repo_dir: Path) -> Iterator[FileEntry]:
    for path in git_ls_files(repo_dir):
        entry = read_entry(repo_dir, path)
        if entry is not None:
            yield entry
