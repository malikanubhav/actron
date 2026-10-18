"""Diff guards: weakened tests per language and the scope check (spec B, B-AC-41 and B-AC-42)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from actron.flow import diff_check as dc

PY_OLD = "def test_a():\n    assert f(1) == 2\n\n\ndef test_b():\n    assert f(2) == 4\n"
JS_OLD = "describe('f', () => {\n  it('adds', () => {\n    expect(f(1)).toBe(2);\n  });\n" \
         "  it('doubles', () => {\n    expect(f(2)).toBe(4);\n  });\n});\n"
CLJ_OLD = "(ns calva.fmt-test)\n(deftest formats\n  (is (= 1 1)))\n(deftest indents\n  (is (= 2 2)))\n"


def _rules(path: str, old: str, new: str | None) -> list[str]:
    return [w.rule for w in dc.weakenings_for(path, old, new)]


@pytest.mark.parametrize(("path", "old", "new", "rule"), [
    ("tests/test_x.py", PY_OLD, None, "deleted_test_file"),
    ("tests/test_x.py", PY_OLD, "def test_a():\n    assert f(1) == 2\n", "deleted_test"),
    ("tests/test_x.py", PY_OLD, PY_OLD.replace("    assert f(2) == 4\n", "    f(2)\n"), "assertion_removed"),
    ("tests/test_x.py", PY_OLD, PY_OLD.replace("assert f(2) == 4", "assert True"), "assertion_loosened"),
    ("tests/test_x.py", PY_OLD, PY_OLD.replace("assert f(2) == 4", "assert f(2) == 4 or True"),
     "assertion_loosened"),
    ("tests/test_x.py", PY_OLD, "import pytest\n\n@pytest.mark.skip\n" + PY_OLD, "skip_added"),
    ("tests/test_x.py", PY_OLD, PY_OLD.replace("def test_b():\n", "def test_b():\n    pytest.skip('x')\n"),
     "skip_added"),
    ("tests/test_x.py", PY_OLD, "@pytest.mark.xfail\n" + PY_OLD, "skip_added"),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("  it('doubles', () => {\n    expect(f(2)).toBe(4);\n  });\n", ""),
     "deleted_test"),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("    expect(f(2)).toBe(4);\n", ""), "assertion_removed"),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("it('adds'", "it.skip('adds'"), "skip_added"),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("it('adds'", "it.only('adds'"), "skip_added"),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("describe('f'", "describe.skip('f'"), "skip_added"),
    ("src/extension-test/unit/f-test.ts", JS_OLD, JS_OLD.replace("it('adds'", "xit('adds'"), "skip_added"),
    ("test/calva/fmt_test.clj", CLJ_OLD, CLJ_OLD.replace("(deftest indents\n  (is (= 2 2)))\n", ""),
     "deleted_test"),
    ("test/calva/fmt_test.clj", CLJ_OLD, CLJ_OLD.replace("  (is (= 2 2)))", "  (= 2 2))"), "assertion_removed"),
    ("test/calva/fmt_test.clj", CLJ_OLD, CLJ_OLD.replace("(deftest formats", "(deftest ^:skip formats"),
     "skip_added"),
])
def test_weakening_rules(path: str, old: str, new: str | None, rule: str) -> None:
    """B-AC-41: deleted tests, removed or loosened assertions, skip/only markers, deleted files (Python, JS/TS,
    Clojure)."""
    assert rule in _rules(path, old, new)


@pytest.mark.parametrize(("path", "old", "new"), [
    ("tests/test_x.py", PY_OLD, PY_OLD + "\n\ndef test_c():\n    assert f(3) == 6\n"),
    ("tests/test_x.py", PY_OLD, PY_OLD.replace("assert f(2) == 4", "assert f(2) == 5")),
    ("src/f.test.ts", JS_OLD, JS_OLD.replace("toBe(4)", "toEqual(4)")),
    ("test/calva/fmt_test.clj", CLJ_OLD, CLJ_OLD + "(deftest more\n  (is (= 3 3)))\n"),
])
def test_allowed_test_changes(path: str, old: str, new: str) -> None:
    """B-AC-41: adding tests and changing an expected value are not weakening."""
    assert dc.weakenings_for(path, old, new) == []


@pytest.mark.parametrize(("path", "is_test"), [
    ("tests/test_ops.py", True), ("calc/ops_test.py", True), ("calc/ops.py", False),
    ("src/a.spec.ts", True), ("src/extension-test/unit/util-test.ts", True), ("src/util.ts", False),
    ("test/calva/fmt_test.cljs", True), ("src/calva/fmt.cljs", False),
])
def test_test_file_detection(path: str, is_test: bool) -> None:
    assert dc.is_test_file(path) is is_test


def test_allowed_paths_and_outside() -> None:
    """B-AC-42: affected files, test plan files, covering tests and co-changed paths are in scope."""
    ticket = {"affectedFunctions": ["code:fn:acme/calc:calc/ops.py::add"],
              "testPlan": [{"target": "code:fn:acme/calc:tests/test_ops.py::test_add", "command": "pytest -q"}]}
    evidence = {"impact": {"tests": [{"id": "code:fn:acme/calc:tests/test_more.py::test_x"}]}}
    procs = [{"coChangedPaths": ["CHANGELOG.md"]}]
    allowed = dc.allowed_paths(ticket, evidence, procs)
    assert {"calc/ops.py", "tests/test_ops.py", "tests/test_more.py", "CHANGELOG.md"} <= allowed
    assert dc.outside_scope(["calc/ops.py", "CHANGELOG.md", "tests/test_new.py", "calc/other.py"],
                            allowed) == ["calc/other.py"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@x", *args], cwd=repo, check=True,
                   capture_output=True)


async def test_check_diff_on_repo(tmp_path: Path) -> None:
    """B-AC-41 and B-AC-42 on a real git diff: deleted test file, then scope via the judge."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(PY_OLD)
    (tmp_path / "x.py").write_text("A = 1\n")
    (tmp_path / "y.py").write_text("B = 1\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    ticket: dict[str, Any] = {"affectedFunctions": ["code:fn:o/r:x.py::f"]}
    seen: list[list[str]] = []

    async def judge(t: dict[str, Any], diff: str, outside: list[str]) -> tuple[float, bool]:
        seen.append(outside)
        return 0.75, False

    (tmp_path / "y.py").write_text("B = 2\n")
    (tmp_path / "x.py").write_text("A = 2\n")
    res = await dc.check_diff(tmp_path, base, ticket, {}, [], scope_judge=judge)
    assert res.status == "scope_change" and res.outside_files == ["y.py"] and seen == [["y.py"]]
    assert res.scope_probability == 0.75

    (tmp_path / "tests" / "test_x.py").unlink()
    res = await dc.check_diff(tmp_path, base, ticket, {}, [], scope_judge=judge)
    assert res.status == "tests_weakened" and res.weakened[0].rule == "deleted_test_file"


async def test_scope_judge_stub_is_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-AC-42: without the model layer, J9's stub answer (1.0) stops the build."""
    import sys

    monkeypatch.setitem(sys.modules, "actron.models", None)  # import fails
    prob, stub = await dc.default_scope_judge({}, "", ["y.py"])
    assert prob == 1.0 and stub is True
