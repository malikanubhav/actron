"""Diff guards of the build (spec B, B9 step 4): weakened tests and scope changes.

Rules for existing test files (a file that exists at the base commit and looks like a test):
- deleted test file;
- deleted test functions (`def test_*`, `it(`/`test(` names, `(deftest name`);
- fewer assertions than before (`assert`, `self.assert*`, `pytest.raises`; `expect(`, `assert.`/`assert(`;
  Clojure `(is `), or an assertion replaced by an always-true one (`assert True`, `... or True`);
- added skip markers (`pytest.skip`, `pytest.mark.skip`, `skipif`, `xfail`; `.skip(`, `.only(`, `xit(`,
  `xdescribe(`, `it.skip`, `describe.skip`, `test.todo`; Clojure `^:skip`).
Changing an assertion's expected value is allowed (the behaviour may change); removing one is not.

Scope: files outside the ticket's affected files, covering tests and the procedure's co-changed paths go to
J9 `is_scope_change`; probability >= 0.7 stops the build with `scope_change`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from actron.graph import ids
from actron.logging import get_logger

log = get_logger(__name__)

SCOPE_THRESHOLD = 0.7

Language = Literal["python", "js", "clojure"]


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Weakening(_Camel):
    path: str
    rule: Literal["deleted_test_file", "deleted_test", "assertion_removed", "assertion_loosened", "skip_added"]
    detail: str


class DiffCheck(_Camel):
    status: Literal["ok", "tests_weakened", "scope_change"] = "ok"
    files_changed: list[str] = Field(default_factory=list)
    weakened: list[Weakening] = Field(default_factory=list)
    outside_files: list[str] = Field(default_factory=list)
    scope_probability: float | None = None
    scope_stub: bool = False
    diff_summary: str = ""
    # path -> [additions, deletions] from `git diff --numstat` (binary files count as 0).
    line_counts: dict[str, list[int]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Test file detection and weakening rules
# ---------------------------------------------------------------------------

_JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_CLJ_EXT = (".clj", ".cljs", ".cljc")


def language_of(path: str) -> Language | None:
    if path.endswith(".py"):
        return "python"
    if path.endswith(_JS_EXT):
        return "js"
    if path.endswith(_CLJ_EXT):
        return "clojure"
    return None


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    parts = set(p.parts[:-1])
    lang = language_of(path)
    if lang == "python":
        return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
    if lang == "js":
        stem = name.rsplit(".", 1)[0]
        if re.search(r"[.-](test|spec)$", stem):
            return True
        return bool(parts & {"__tests__", "test", "tests", "extension-test"})
    if lang == "clojure":
        return bool(re.search(r"_test\.clj[sc]?$", name)) or "test" in parts
    return False


_PY_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(", re.M)
_JS_TEST_DEF = re.compile(r"\b(?:it|test)\s*\(\s*(['\"`])(.+?)\1", re.M)
_CLJ_TEST_DEF = re.compile(r"\(deftest\s+(?:\^[:\w-]+\s+)?([^\s()]+)", re.M)

_ASSERTIONS: dict[Language, re.Pattern[str]] = {
    "python": re.compile(r"^\s*assert\b|\bself\.assert\w*\s*\(|\bpytest\.raises\s*\(", re.M),
    "js": re.compile(r"\bexpect\s*\(|\bassert\s*(?:\.\w+)?\s*\(", re.M),
    "clojure": re.compile(r"\(is\s", re.M),
}
_TRIVIAL_ASSERT = re.compile(
    r"^\s*assert\s+(True|1|not\s+False)\s*(#.*)?$|\bor\s+True\s*$|expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)"
    r"|\(is\s+true\)|^\s*#\s*assert\b|^\s*//\s*(expect|assert)\b|^\s*;+\s*\(is\s",
    re.M,
)
_SKIP_MARKERS: dict[Language, re.Pattern[str]] = {
    "python": re.compile(r"pytest\.skip\b|pytest\.mark\.skip|\bskipif\b|\bxfail\b|unittest\.skip|@skip\b"),
    "js": re.compile(r"\.skip\s*\(|\.only\s*\(|\bxit\s*\(|\bxdescribe\s*\(|\bxtest\s*\(|\.todo\s*\("),
    "clojure": re.compile(r"\^:skip\b|\^:kaocha/skip\b"),
}


def _test_names(lang: Language, text: str) -> set[str]:
    if lang == "python":
        return set(_PY_TEST_DEF.findall(text))
    if lang == "js":
        return {m[1] for m in _JS_TEST_DEF.findall(text)}
    return set(_CLJ_TEST_DEF.findall(text))


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def _added_lines(old: str, new: str) -> list[str]:
    remaining: dict[str, int] = {}
    for line in old.splitlines():
        remaining[line] = remaining.get(line, 0) + 1
    added: list[str] = []
    for line in new.splitlines():
        if remaining.get(line, 0) > 0:
            remaining[line] -= 1
        else:
            added.append(line)
    return added


def weakenings_for(path: str, old: str, new: str | None) -> list[Weakening]:
    """Compare an existing test file at base (`old`) with its new content (`None` = deleted)."""
    if new is None:
        return [Weakening(path=path, rule="deleted_test_file", detail="The test file was deleted.")]
    lang = language_of(path)
    if lang is None:
        return []
    out: list[Weakening] = []
    gone = sorted(_test_names(lang, old) - _test_names(lang, new))
    for name in gone:
        out.append(Weakening(path=path, rule="deleted_test", detail=f"Test {name} was removed."))
    before, after = _count(_ASSERTIONS[lang], old), _count(_ASSERTIONS[lang], new)
    if after < before:
        out.append(Weakening(path=path, rule="assertion_removed",
                             detail=f"Assertions went from {before} to {after}."))
    added = _added_lines(old, new)
    for line in added:
        if _TRIVIAL_ASSERT.search(line):
            out.append(Weakening(path=path, rule="assertion_loosened", detail=f"Added: {line.strip()[:160]}"))
        elif _SKIP_MARKERS[lang].search(line):
            out.append(Weakening(path=path, rule="skip_added", detail=f"Added: {line.strip()[:160]}"))
    return out


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _path_of(node_id: str) -> str | None:
    try:
        parsed = ids.parse_id(node_id)
    except ids.InvalidId:
        return None
    return parsed.parts.get("path")


def allowed_paths(
    ticket: dict[str, Any], evidence: dict[str, Any], procedures: list[dict[str, Any]]
) -> set[str]:
    """Files the build may change without a scope check."""
    allowed: set[str] = set()
    for node_id in ticket.get("affectedFunctions") or []:
        path = _path_of(str(node_id))
        if path:
            allowed.add(path)
    for item in ticket.get("testPlan") or []:
        target = str((item or {}).get("target") or "")
        path = _path_of(target) if ":" in target else None
        if path:
            allowed.add(path)
        command = str((item or {}).get("command") or "")
        for word in command.split():
            word = word.split("::", 1)[0]
            if "/" in word or word.endswith((".py", ".ts", ".js", ".clj", ".cljs")):
                allowed.add(word.lstrip("./"))
    impact = evidence.get("impact") or {}
    for test in impact.get("tests") or []:
        path = _path_of(str(test.get("id") or ""))
        if path:
            allowed.add(path)
    for proc in procedures:
        for path in proc.get("coChangedPaths") or []:
            allowed.add(str(path))
    return allowed


def outside_scope(files: list[str], allowed: set[str]) -> list[str]:
    out = []
    for f in files:
        if f in allowed or is_test_file(f):
            continue
        if any(a.endswith("/") and f.startswith(a) for a in allowed):
            continue
        out.append(f)
    return out


ScopeJudge = Callable[[dict[str, Any], str, list[str]], Awaitable[tuple[float, bool]]]


async def default_scope_judge(ticket: dict[str, Any], diff_summary: str, outside: list[str]) -> tuple[float, bool]:
    """J9 through the model layer (W4). Without it, the stub answer is the conservative 1.0 (stop)."""
    try:
        from actron.models import is_scope_change
    except ImportError:
        log.warning("J9 is_scope_change is not available; using the stub answer 1.0")
        return 1.0, True
    judgment = await is_scope_change(ticket, diff_summary, outside)
    prob = judgment.probability
    if prob is None and isinstance(judgment.answer, int | float):
        prob = float(judgment.answer)
    return (1.0 if prob is None else float(prob)), bool(judgment.stub)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


async def _git(repo: Path, *args: str) -> tuple[int, str]:
    from actron.flow.test_runner import run_cmd

    return await run_cmd(["git", "-C", str(repo), *args], env=_git_env(), timeout=120)


def _git_env() -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


async def changed_files(repo: Path, base_sha: str) -> list[tuple[str, str]]:
    """(status, path) for every change against base, including new files. Stages the working tree."""
    await _git(repo, "add", "-A")
    code, out = await _git(repo, "diff", "--cached", "--name-status", "--no-renames", base_sha)
    if code != 0:
        raise RuntimeError(f"git diff failed: {out.strip()[-300:]}")
    rows = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        if path:
            rows.append((status.strip()[:1], path.strip()))
    return rows


def parse_numstat(text: str) -> dict[str, list[int]]:
    """`git diff --numstat` lines (`added<TAB>deleted<TAB>path`, `-` for binary files) to path -> [added, deleted]."""
    out: dict[str, list[int]] = {}
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or not parts[2].strip():
            continue
        added, deleted = (int(p) if p.strip().isdigit() else 0 for p in parts[:2])
        out[parts[2].strip()] = [added, deleted]
    return out


async def check_diff(
    repo: Path,
    base_sha: str,
    ticket: dict[str, Any],
    evidence: dict[str, Any],
    procedures: list[dict[str, Any]],
    *,
    scope_judge: ScopeJudge | None = None,
) -> DiffCheck:
    rows = await changed_files(repo, base_sha)
    _, stat = await _git(repo, "diff", "--cached", "--stat", base_sha)
    result = DiffCheck(files_changed=[p for _, p in rows], diff_summary=stat.strip()[-4000:])
    _, numstat = await _git(repo, "diff", "--cached", "--numstat", "--no-renames", base_sha)
    result.line_counts = parse_numstat(numstat)
    for status, path in rows:
        if status == "A" or not is_test_file(path):
            continue
        code, old = await _git(repo, "show", f"{base_sha}:{path}")
        if code != 0:
            continue
        new = None if status == "D" else (repo / path).read_text(encoding="utf-8", errors="replace")
        result.weakened.extend(weakenings_for(path, old, new))
    if result.weakened:
        result.status = "tests_weakened"
        return result
    outside = outside_scope(result.files_changed, allowed_paths(ticket, evidence, procedures))
    result.outside_files = outside
    if outside:
        judge = scope_judge or default_scope_judge
        prob, stub = await judge(ticket, result.diff_summary, outside)
        result.scope_probability, result.scope_stub = prob, stub
        if prob >= SCOPE_THRESHOLD:
            result.status = "scope_change"
    return result
