"""Build with the labelled fake Pi through the real docker path (spec B, B9)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from actron.flow.build import BuildEnv, BuildInput, BuildPaths, LocalBuildSteps, run_build
from tests.integration.build.conftest import (
    Events,
    FakeGitHub,
    FakeGraphTools,
    SyntheticRepo,
    container_names,
    scope_high,
    scope_low,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.timeout(600)]


async def _run(env: BuildEnv, inp: BuildInput, events: Events, github: FakeGitHub,
               tools: FakeGraphTools | None = None, scope: Any = scope_low) -> Any:
    steps = LocalBuildSteps(env, emit=events, tools=tools, scope_judge=scope,
                            github_transport=github.transport)
    result = await run_build(inp, steps)
    return result, steps


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


async def test_success_build_commits_pushes_and_opens_pr(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools, synthetic_repo: SyntheticRepo,
) -> None:
    """B-AC-39: fake Pi applies a known patch; steps, tests, build.passed, bot commit, push, PR on fake GitHub."""
    env = build_env_factory("success")
    inp = make_input()
    result, _ = await _run(env, inp, events, fake_github, graph_tools)
    assert result.status == "passed", result
    assert result.tests_failed == 0 and result.tests_passed == 3
    assert set(result.files_changed) == {"calc/ops.py", "tests/test_ops.py"}
    types = [t for t, _ in events.items]
    for t in ("build.started", "build.step", "tests.result", "build.passed", "pr.opened"):
        assert t in types
    assert types.index("build.started") < types.index("tests.result") < types.index("build.passed")
    texts = [p["text"] for p in events.of("build.step")]
    assert any(t.startswith("Editing calc/ops.py") for t in texts)
    assert any(t.startswith("Asking the graph: callers") for t in texts)
    # Pushed to the fork as the bot.
    branch = f"actron/{inp.request_id}-r1"
    head = _git(synthetic_repo.fork, "rev-parse", branch)
    assert head == result.head_sha
    author = _git(synthetic_repo.fork, "log", "-1", "--format=%an <%ae>%n%s%n%b", branch)
    assert author.startswith("Actron Bot <bot@actron.test>")
    assert "Actron request req_01TEST, ticket revision 1 (aaaaaaaa)" in author
    assert _git(synthetic_repo.fork, "show", f"{branch}:calc/ops.py").count("def subtract") == 1
    # PR on the fork, against the target branch, with the bot's token.
    assert len(fake_github.pulls) == 1
    pr = fake_github.pulls[0]
    assert pr["repo"] == "acme/calc-fork" and pr["base"]["ref"] == "main" and pr["head"]["ref"] == branch
    assert result.pr_number == 1 and result.pr_url.endswith("/pull/1")
    assert fake_github.requests[-1].headers["authorization"].startswith("Bearer ghp_")
    # No container left behind.
    assert container_names(f"actron-pi-{inp.build_id}") == []


async def test_pr_body_contains_report_and_template(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-76: REPORT.json is validated and its contents appear in the PR body (and the result for the Build tab)."""
    result, _ = await _run(build_env_factory("success"), make_input(), events, fake_github, graph_tools)
    assert result.status == "passed"
    assert result.report and result.report["testsAdded"] == ["tests/test_ops.py::test_subtract"]
    # Build.report in the request view's shape (frontend/lib/build-report.ts).
    report = result.report
    assert report["tests"] == [{"name": "tests/test_ops.py::test_subtract", "status": "pass"}]
    assert report["constraints"][0]["text"] == "add keeps its signature"
    assert report["constraints"][0]["status"] == "holds"
    assert report["constraints"][0]["proof"]["kind"] == "test"
    changed = {f["path"]: f for f in report["filesChanged"]}
    assert changed["calc/ops.py"]["additions"] > 0 and changed["calc/ops.py"]["deletions"] == 0
    assert report["procedures"] == [] and report["pi"]["testCommand"]
    body = fake_github.pulls[0]["body"]
    for heading in ("## What and why", "## Evidence from the team's history", "## Constraints preserved",
                    "## Tests", "## Graph impact", "## Build report"):
        assert heading in body
    assert "(Actron request req_01TEST, ticket ENG-12 v1)" in body
    assert "Let's never change add's arguments" in body
    assert "- [x] add keeps its signature — proved by test_add still passes" in body
    assert f"3/3 passed on {result.head_sha[:7]}. Command: `pytest -q`" in body
    assert "1 callers checked; criticality of changed functions: add 97.5th percentile" in body
    assert '"testsAdded": [' in body and "Added subtract next to add" in body


async def test_fail_then_repair(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-40 and B-AC-71: one build.repair, final passed; the repair continues the same Pi session."""
    env = build_env_factory("fail_then_repair")
    inp = make_input()
    result, _ = await _run(env, inp, events, fake_github, graph_tools)
    assert result.status == "passed", result
    assert len(events.of("build.repair")) == 1
    assert events.of("build.repair")[0]["attempt"] == 1
    results = events.of("tests.result")
    assert results[0]["failed"] >= 1 and results[-1]["failed"] == 0
    assert result.attempts == 2
    notes = [p["text"] for p in events.steps("pi.note")]
    assert "New session" in notes[0]
    assert any(n.startswith("Resumed session with") for n in notes[1:])
    failures = (BuildPaths.for_build(env.host_dir, inp.build_id).context / "failures.md").read_text()
    assert "## Failing tests" in failures and "test_subtract" in failures


async def test_previous_build_is_given_after_review_feedback(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-71: a revision after review feedback receives previous-build.md."""
    env = build_env_factory("success")
    inp = make_input(previous_build={"notes": "Changed add.", "diffSummary": "calc/ops.py | 2 +-",
                                     "testResults": {"passed": 3, "failed": 0},
                                     "feedback": "Please also handle floats."})
    result, _ = await _run(env, inp, events, fake_github)
    assert result.status == "passed"
    text = (BuildPaths.for_build(env.host_dir, inp.build_id).context / "previous-build.md").read_text()
    assert "Please also handle floats." in text and "Changed add." in text and "calc/ops.py | 2 +-" in text


async def test_previous_build_loaded_from_its_folder(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-71: with only `{buildId, feedback}` (as RequestWorkflow sends), the earlier build's notes, diff
    summary and test results are read from its folder; the new build continues the same branch."""
    env = build_env_factory("success")
    first = make_input()
    r1, _ = await _run(env, first, events, fake_github)
    assert r1.status == "passed"
    second = make_input(previous_build={"buildId": first.build_id, "feedback": "Please also handle floats."})
    r2, steps = await _run(env, second, events, fake_github)
    text = (BuildPaths.for_build(env.host_dir, second.build_id).context / "previous-build.md").read_text()
    assert "Please also handle floats." in text
    assert "Changed calc/ops.py; ran pytest -q." in text  # the first build's notes
    assert "calc/ops.py" in text.split("## What it changed", 1)[1]
    assert '"passed": 3' in text
    assert any("FETCH_HEAD" in r.argv for r in steps.runner.records)  # continued the pushed branch
    assert r2.status == "passed" and events.of("pr.updated")


@pytest.mark.parametrize("scenario", ["weakened_delete", "weakened_skip"])
async def test_weakened_tests_stop_the_build(
    scenario: str, build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput],
    events: Events, fake_github: FakeGitHub, synthetic_repo: SyntheticRepo,
) -> None:
    """B-AC-41: deleting a test or adding pytest.skip stops the build with tests_weakened."""
    result, _ = await _run(build_env_factory(scenario), make_input(), events, fake_github)
    assert result.status == "stopped" and result.stop_reason == "tests_weakened"
    assert events.of("build.failed")[-1]["reason"] == "tests_weakened"
    assert not fake_github.pulls
    assert _git(synthetic_repo.fork, "branch", "--list") == ""


async def test_scope_change_stops_with_j9(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-42: a file outside the ticket's files and J9 >= 0.7 stops the build with scope_change."""
    result, _ = await _run(build_env_factory("scope_change"), make_input(), events, fake_github, scope=scope_high)
    assert result.status == "stopped" and result.stop_reason == "scope_change"
    diff = events.steps("guard.diff")[-1]["detail"]
    assert diff["outsideFiles"] == ["calc/other.py"] and diff["scopeProbability"] == 0.9
    assert not fake_github.pulls


async def test_scope_low_probability_continues(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-42 (other side): J9 below 0.7 lets the build continue."""
    result, _ = await _run(build_env_factory("scope_change"), make_input(), events, fake_github, scope=scope_low)
    assert result.status == "passed"


async def test_stop_md_stops_with_scope_change(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-42: Pi writing STOP.md stops the build with scope_change and the reason is reported."""
    result, _ = await _run(build_env_factory("stop_md"), make_input(), events, fake_github)
    assert result.status == "stopped" and result.stop_reason == "scope_change"
    assert "money rounding" in events.steps("guard.stop_md")[0]["detail"]["stop"]


async def test_timeout_kills_and_removes_container(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-43: a hanging Pi is killed at the timeout; status failed with reason timeout; container removed."""
    inp = make_input(timeout_seconds=8)
    result, _ = await _run(build_env_factory("timeout"), inp, events, fake_github)
    assert result.status == "failed" and result.stop_reason == "timeout"
    assert container_names(f"actron-pi-{inp.build_id}") == []
    assert events.of("build.failed")[-1]["reason"] == "timeout"


@pytest.mark.parametrize(("change", "reason"), [
    ({"push_target": None}, "missing_fork"),
    ({"push_target": "acme/calc"}, "missing_fork"),
    ({}, "missing_identity"),
])
async def test_missing_fork_or_identity_stops_before_any_container(
    change: dict[str, Any], reason: str, build_env_factory: Callable[..., BuildEnv],
    make_input: Callable[..., BuildInput], events: Events, fake_github: FakeGitHub,
) -> None:
    """B-AC-44: missing fork (or fork == upstream) or bot identity stops with the reason before any container."""
    overrides: dict[str, Any] = {"github_fork": None}
    if reason == "missing_identity":
        overrides.update(bot_name="", github_fork="acme/calc-fork")
    env = build_env_factory("success", **overrides)
    inp = make_input(**change)
    steps = LocalBuildSteps(env, emit=events, github_transport=fake_github.transport)
    result = await run_build(inp, steps)
    assert result.status == "stopped" and result.stop_reason == reason
    assert not any(r.argv[:2] == ["docker", "run"] for r in steps.runner.records)
    assert not any(r.argv[:2] == ["git", "clone"] or "clone" in r.argv for r in steps.runner.records)
    assert "build.started" not in [t for t, _ in events.items]


async def test_missing_branch(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub,
) -> None:
    """B-AC-44 (and B-AC-81 at the build level): a target branch that no longer exists stops with missing_branch."""
    inp = make_input(ticket={**make_input().ticket, "targetBranch": "gone"})
    steps = LocalBuildSteps(build_env_factory("success"), emit=events, github_transport=fake_github.transport)
    result = await run_build(inp, steps)
    assert result.status == "stopped" and result.stop_reason == "missing_branch"
    assert not any(r.argv[:2] == ["docker", "run"] for r in steps.runner.records)


async def test_non_default_target_branch(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, synthetic_repo: SyntheticRepo,
) -> None:
    """B-AC-80 (build level): the build checks out the target branch head and opens the PR against it."""
    inp = make_input(ticket={**make_input().ticket, "targetBranch": "release-1"})
    result, _ = await _run(build_env_factory("success"), inp, events, fake_github)
    assert result.status == "passed"
    assert result.base_sha == synthetic_repo.base_sha
    assert fake_github.pulls[0]["base"]["ref"] == "release-1"


async def test_success_reads_nothing_outside_the_pack(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-72: with the context pack covering the task, direct file reads outside edited files are zero."""
    result, _ = await _run(build_env_factory("success"), make_input(), events, fake_github, graph_tools)
    assert result.status == "passed"
    assert [a["outsideReads"] for a in result.guards["attempts"]] == [0]
    assert result.guards["exploration"] == [0]


async def test_explorer_is_reminded_then_stopped_and_retried(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-73: reminder after 3 exploration events, stop and retry after 10, counts reported."""
    env = build_env_factory("explorer")
    inp = make_input()
    result, _ = await _run(env, inp, events, fake_github, graph_tools)
    assert len(events.steps("guard.exploration_reminder")) >= 1
    assert events.steps("guard.exploration_reminder")[0]["detail"]["exploration"] == 3
    stop = events.steps("guard.exploration_stop")
    assert len(stop) == 1 and stop[0]["detail"]["exploration"] == 10
    assert len(events.steps("guard.exploration_retry")) == 1
    task = (BuildPaths.for_build(env.host_dir, inp.build_id).context / "TASK.md").read_text()
    assert task.startswith("## Reminder from the last attempt")
    assert "Use the graph tools" in task.splitlines()[1]
    assert result.status == "passed" and result.attempts == 2
    assert result.guards["exploration"][0] == 10
    explored = [p["detail"].get("exploration") for p in events.steps("pi.tool") if "exploration" in p["detail"]]
    assert explored[:3] == [1, 2, 3]


async def test_light_explorer_gets_reminder_and_finishes(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-73: 4 exploration events record one reminder and the attempt is not stopped."""
    result, _ = await _run(build_env_factory("explorer_light"), make_input(), events, fake_github, graph_tools)
    assert result.status == "passed" and result.attempts == 1
    assert len(events.steps("guard.exploration_reminder")) == 1
    assert not events.steps("guard.exploration_stop")
    assert "Use the graph tools" in " ".join(result.guards["reminders"])


@pytest.mark.parametrize(("scenario", "missing", "first_line"), [
    ("no_plan", "plan", "There was no plan at the top of /context/notes.md"),
    ("no_report", "report", "/context/REPORT.json was missing"),
    ("no_tests_after_edit", "tests_after_last_edit", "The test command was not run after the last edit"),
])
async def test_missing_required_output_fails_the_attempt(
    scenario: str, missing: str, first_line: str, build_env_factory: Callable[..., BuildEnv],
    make_input: Callable[..., BuildInput], events: Events, fake_github: FakeGitHub,
) -> None:
    """B-AC-74: missing plan, REPORT.json or final test run is a failed attempt; the repair names it first."""
    env = build_env_factory(scenario)
    inp = make_input()
    result, _ = await _run(env, inp, events, fake_github)
    assert events.of("build.repair")[0]["reason"] == f"missing: {missing}"
    failures = (BuildPaths.for_build(env.host_dir, inp.build_id).context / "failures.md").read_text()
    lines = failures.splitlines()
    assert lines[1] == "## Missing from the work protocol (fix these first)"
    assert lines[2].startswith(f"- {first_line}")
    assert result.status == "passed" and result.attempts == 2


async def test_edit_without_callers_gets_graph_first_reminder(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-75: editing a function with callers, without asking the graph and without callers in code.md."""
    # A tiny pack limit forces the cut tier, so the callers are not in code.md.
    env = build_env_factory("edits_without_callers", pack_limit=400)
    result, _ = await _run(env, make_input(), events, fake_github, graph_tools)
    reminders = events.steps("guard.graph_first")
    assert len(reminders) == 1
    assert reminders[0]["file"] == "calc/ops.py"
    assert result.guards["graphFirstMisses"] == 1


async def test_callers_in_pack_satisfy_graph_first(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, graph_tools: FakeGraphTools,
) -> None:
    """B-AC-75 (other side): with callers already in code.md, no graph-first reminder."""
    env = build_env_factory("edits_without_callers")
    result, _ = await _run(env, make_input(), events, fake_github, graph_tools)
    assert result.status == "passed"
    assert events.steps("guard.graph_first") == []
    meta = json.loads((BuildPaths.for_build(env.host_dir, result.build_id).root / "pack-meta.json").read_text())
    assert meta["functions"]["code:fn:acme/calc:calc/ops.py::add"]["callersInPack"] is True
