"""Test command resolution, reporters and parsers (spec B, B9 step 5; B-AC-46)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from actron.flow import test_runner as tr

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="1" tests="4">
<testcase classname="tests.test_ops" name="test_add" time="0.001"/>
<testcase classname="tests.test_ops" name="test_total" time="0.001"/>
<testcase classname="tests.test_ops" name="test_sub" time="0.001">
  <failure message="assert 8 == 2">def test_sub():
&gt;       assert subtract(5, 3) == 2
E       assert 8 == 2</failure></testcase>
<testcase classname="tests.test_ops" name="test_later" time="0"><skipped message="later"/></testcase>
</testsuite></testsuites>"""

MOCHA = {
    "stats": {"suites": 2, "tests": 3, "passes": 2, "pending": 0, "failures": 1, "duration": 12},
    "tests": [], "pending": [],
    "failures": [{"title": "formats a form", "fullTitle": "formatter formats a form",
                  "err": {"message": "expected '(a b)' to equal '(a  b)'", "stack": "AssertionError: ..."}}],
    "passes": [{"title": "a"}, {"title": "b"}],
}

VITEST = {
    "numTotalTestSuites": 1, "numPassedTestSuites": 0, "numFailedTestSuites": 1, "numPendingTestSuites": 0,
    "numTotalTests": 4, "numPassedTests": 2, "numFailedTests": 1, "numPendingTests": 1, "numTodoTests": 0,
    "success": False,
    "testResults": [{"name": "/work/src/x.test.ts", "status": "failed", "assertionResults": [
        {"fullName": "x adds", "title": "adds", "status": "passed", "failureMessages": []},
        {"fullName": "x subtracts", "title": "subtracts", "status": "failed",
         "failureMessages": ["AssertionError: expected 8 to be 2"]},
    ]}],
}


def test_parse_pytest_junit() -> None:
    """B-AC-46: pytest JUnit XML."""
    r = tr.parse_junit_xml(JUNIT)
    assert (r.passed, r.failed, r.skipped) == (2, 1, 1)
    assert r.failing[0].name == "tests.test_ops::test_sub" and "assert 8 == 2" in r.failing[0].output


def test_parse_mocha_json_with_npm_noise() -> None:
    """B-AC-46: Mocha JSON reporter output, with npm's lines around it."""
    out = "> calva@2.0.0 unit-test\n> npx mocha --exit\n\n" + json.dumps(MOCHA, indent=2) + "\nnpm ERR! code 1\n"
    r = tr.parse_mocha_json(out)
    assert (r.passed, r.failed, r.skipped) == (2, 1, 0)
    assert r.failing[0].name == "formatter formats a form" and "to equal" in r.failing[0].output


def test_parse_vitest_and_jest_json() -> None:
    """B-AC-46: Vitest JSON reporter (Jest-compatible shape) and Jest --json."""
    r = tr.parse_jest_json(json.dumps(VITEST), "vitest")
    assert (r.passed, r.failed, r.skipped, r.parser) == (2, 1, 1, "vitest")
    assert r.failing[0].name == "x subtracts"
    j = tr.parse_jest_json(json.dumps(VITEST), "jest")
    assert j.parser == "jest" and j.failed == 1


def test_exit_code_fallback_keeps_last_200_lines(tmp_path: Path) -> None:
    """B-AC-46: without a reporter, the exit code and the last 200 lines decide."""
    output = "\n".join(f"line {i}" for i in range(500))
    r = tr.parse_results("exit_code", exit_code=2, output=output, reports_dir=tmp_path, command="make test")
    assert (r.passed, r.failed, r.parser) == (0, 1, "exit_code")
    assert r.failing[0].output.splitlines()[0] == "line 300" and len(r.failing[0].output.splitlines()) == 200
    ok = tr.parse_results("exit_code", exit_code=0, output="fine", reports_dir=tmp_path, command="make test")
    assert ok.ok and ok.passed == 1
    broken = tr.parse_results("junit", exit_code=1, output="ImportError", reports_dir=tmp_path, command="pytest")
    assert broken.parser == "exit_code" and broken.failed == 1


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def test_command_resolution_order_and_source(tmp_path: Path) -> None:
    """B-AC-46: ticket → procedure → repository default, and the source is recorded."""
    repo = _repo(tmp_path, {"package.json": json.dumps({"scripts": {"unit-test": "npx mocha", "test": "jest"}})})
    ticket = {"testPlan": [{"kind": "existing", "target": "x", "command": "npm test -- x.test.ts"}]}
    assert tr.resolve_test_command(ticket, [], repo) == ("npm test -- x.test.ts", "ticket")
    procs = [{"testCommand": "npm run unit-test"}]
    assert tr.resolve_test_command({}, procs, repo) == ("npm run unit-test", "procedure")
    assert tr.resolve_test_command({}, [], repo) == ("npm run unit-test -- --reporter json", "repo_default")


@pytest.mark.parametrize(("files", "expected"), [
    ({"package.json": json.dumps({"scripts": {"test": "vitest run"}})}, "npm test"),
    ({"pyproject.toml": "[project]\nname='x'\n"}, "pytest -q"),
    ({"deps.edn": "{:aliases {:test {}}}"}, "clojure -M:test"),
])
def test_repo_defaults(tmp_path: Path, files: dict[str, str], expected: str) -> None:
    """B-AC-46: repository defaults for Node, Python and Clojure-only repositories."""
    assert tr.resolve_test_command({}, [], _repo(tmp_path, files)) == (expected, "repo_default")


def test_no_command_raises(tmp_path: Path) -> None:
    with pytest.raises(tr.NoTestCommand):
        tr.resolve_test_command({}, [], tmp_path)


def test_ticket_pytest_commands_are_merged(tmp_path: Path) -> None:
    ticket = {"testPlan": [{"command": "pytest tests/a.py::t1"}, {"command": "pytest tests/b.py -q"}]}
    assert tr.resolve_test_command(ticket, [], tmp_path) == ("pytest tests/a.py::t1 tests/b.py -q", "ticket")


@pytest.mark.parametrize(("command", "pkg", "parser", "suffix"), [
    ("pytest -q", None, "junit", "--junitxml=/reports/junit.xml"),
    ("npm run unit-test -- --reporter json", {"unit-test": "npx mocha"}, "mocha", "--reporter json"),
    ("npm test", {"test": "vitest run"}, "vitest", "-- --reporter=json --outputFile=/reports/vitest.json"),
    ("npm test", {"test": "jest"}, "jest", "-- --json --outputFile=/reports/jest.json"),
    ("make check", None, "exit_code", "make check"),
])
def test_instrumentation(tmp_path: Path, command: str, pkg: dict[str, str] | None, parser: str,
                         suffix: str) -> None:
    """B-AC-46: reporters are added per runner."""
    if pkg:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": pkg}))
    out, chosen = tr.instrument_command(command, tmp_path)
    assert chosen == parser and out.endswith(suffix)


FAKE_MOCHA_JS = """
const fail = process.argv.includes('--reporter') && process.env.FAIL === '1';
const report = {stats: {passes: 3, failures: 0, pending: 1}, failures: [], passes: [], pending: []};
console.log(JSON.stringify(report, null, 2));
"""


@pytest.mark.integration
@pytest.mark.timeout(300)
async def test_node_repo_default_runs_offline_with_mocha_parser(tmp_path: Path, test_runner_image: str) -> None:
    """B-AC-46: a Node repository with a `unit-test` script runs `npm run unit-test -- --reporter json` offline."""
    repo = _repo(tmp_path / "repo", {
        "package.json": json.dumps({"name": "x", "version": "1.0.0", "scripts": {"unit-test": "node mocha.js"}}),
        "mocha.js": FAKE_MOCHA_JS,
    })
    command, source = tr.resolve_test_command({}, [], repo)
    assert (command, source) == ("npm run unit-test -- --reporter json", "repo_default")
    cfg = tr.TestRunConfig(image=test_runner_image, cache_root=tmp_path / "cache", timeout_seconds=120)
    r = await tr.run_tests(repo, tmp_path / "reports", "node1", command, source, cfg)
    assert (r.parser, r.passed, r.skipped, r.failed) == ("mocha", 3, 1, 0)
    assert r.source == "repo_default" and r.isolation and r.isolation.network_mode == "none"


@pytest.mark.integration
@pytest.mark.timeout(300)
async def test_exit_code_fallback_in_container(tmp_path: Path, test_runner_image: str) -> None:
    """B-AC-46: a command without a reporter is judged by its exit code and output."""
    repo = _repo(tmp_path / "repo", {"check.sh": "echo checking\necho 'broken thing'\nexit 3\n"})
    cfg = tr.TestRunConfig(image=test_runner_image, cache_root=tmp_path / "cache", timeout_seconds=120)
    r = await tr.run_tests(repo, tmp_path / "reports", "exit1", "sh check.sh", "procedure", cfg)
    assert (r.parser, r.failed, r.exit_code, r.source) == ("exit_code", 1, 3, "procedure")
    assert "broken thing" in r.failing[0].output
