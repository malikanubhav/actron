# ruff: noqa: F811  (fixtures imported from tests/integration/build/conftest.py are used as parameters)
"""BuildWorkflow on Temporal (time-skipping test server): full run, queue, cancellation, budget wait.

Spec B, B9 and B12a; B-AC-39 (through Temporal), B-AC-47, B-AC-11 (build level), B-AC-85 (build level).
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from actron.activities.build import QUEUE_KEY, RUNNING_KEY, BuildActivities
from actron.flow.build import BuildEnv, BuildInput
from actron.workflows.build import BuildWorkflow
from tests.integration.build.conftest import (  # noqa: F401  (fixtures)
    Events,
    FakeGitHub,
    build_env_factory,
    container_names,
    docker_available,
    fake_github,
    fake_pi_image,
    make_input,
    scope_low,
    synthetic_repo,
    test_runner_image,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]


@pytest.fixture
async def env() -> Any:
    environment = await WorkflowEnvironment.start_time_skipping()
    try:
        yield environment
    finally:
        await environment.shutdown()


@pytest.fixture
def clean_queue(redis_client: Any) -> Any:
    redis_client.delete(QUEUE_KEY, RUNNING_KEY)
    yield redis_client
    redis_client.delete(QUEUE_KEY, RUNNING_KEY)


async def no_budget_cap(ws: str) -> dict[str, Any]:
    return {"reached": False, "spentUsd": 0.0, "capUsd": 20.0}


def _activities(build_env: BuildEnv, events: Events, github: FakeGitHub, redis_url: str,
                **kw: Any) -> BuildActivities:
    return BuildActivities(build_env, emit_factory=lambda ws, rid: events, tools_factory=lambda *a: None,
                           scope_judge=scope_low, github_transport=github.transport, redis_url=redis_url,
                           max_slots=1, run_token="test-run-token", budget_check=no_budget_cap, **kw)


async def test_full_build_through_temporal(
    env: Any, build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput],
    fake_github: FakeGitHub, redis_url: str, clean_queue: Any,
) -> None:
    """B-AC-39 through BuildWorkflow: every step as an activity; result passed with a PR."""
    events = Events()
    acts = _activities(build_env_factory("success"), events, fake_github, redis_url)
    queue = f"build-{uuid.uuid4().hex[:8]}"
    inp = make_input()
    async with Worker(env.client, task_queue=queue, workflows=[BuildWorkflow], activities=acts.all()):
        result = await env.client.execute_workflow(BuildWorkflow.run, inp.wire(), id=f"build:{inp.build_id}",
                                                   task_queue=queue)
    assert result["status"] == "passed", result
    assert result["prNumber"] == 1 and result["headSha"]
    types = [t for t, _ in events.items]
    assert types[0] == "build.queued" and events.of("build.queued")[0]["position"] == 0
    for t in ("build.started", "tests.result", "build.passed", "pr.opened"):
        assert t in types
    assert clean_queue.zcard(QUEUE_KEY) == 0 and clean_queue.zcard(RUNNING_KEY) == 0


# --- Mocked steps for queue and budget tests ------------------------------------------------------------


class MockSteps:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.started: list[str] = []
        self.budget_calls = 0
        self.budget_reached_times = 0

    def gate(self, build_id: str) -> asyncio.Event:
        return self.gates.setdefault(build_id, asyncio.Event())

    def all(self) -> list[Callable[..., Any]]:
        @activity.defn(name="build_prepare_checkout")
        async def prepare(inp: dict[str, Any]) -> dict[str, Any]:
            self.started.append(inp["buildId"])
            return {"baseSha": "base", "branch": "actron/x", "root": "/r", "repoDir": "/r/repo",
                    "testCommand": "pytest -q", "testCommandSource": "repo_default"}

        @activity.defn(name="build_write_context")
        async def write_context(inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
            return {"packSize": 10, "packTier": "full", "whereToWork": []}

        @activity.defn(name="build_run_pi")
        async def run_pi(inp: dict[str, Any], attempt: int) -> dict[str, Any]:
            gate = self.gates.get(inp["buildId"])
            if gate is not None:
                while not gate.is_set():
                    activity.heartbeat()
                    await asyncio.sleep(0.1)
            return {"attempt": attempt, "planOk": True, "reportOk": True, "testsAfterLastEdit": True,
                    "report": {"filesChanged": ["a.py"]}}

        @activity.defn(name="build_check_diff")
        async def check_diff(inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
            return {"status": "ok", "filesChanged": ["a.py"]}

        @activity.defn(name="build_run_tests")
        async def run_tests(inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
            return {"passed": 1, "failed": 0, "command": "pytest -q", "source": "repo_default"}

        @activity.defn(name="build_write_failures")
        async def write_failures(inp: dict[str, Any], c: dict[str, Any], text: str, r: list[str]) -> None:
            return None

        @activity.defn(name="build_commit_and_push")
        async def commit(inp: dict[str, Any], checkout: dict[str, Any]) -> str:
            return "head" + inp["buildId"]

        @activity.defn(name="build_open_pr")
        async def open_pr(inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
            return {"number": 7, "url": "https://github.test/pr/7", "headSha": result["headSha"], "action": "opened"}

        @activity.defn(name="build_read_notes")
        async def read_notes(inp: dict[str, Any]) -> str:
            return ""

        @activity.defn(name="build_emit")
        async def emit(ws: str, rid: str, type: str, payload: dict[str, Any]) -> None:
            self.events.append((type, payload))

        @activity.defn(name="build_check_budget")
        async def check_budget(ws: str) -> dict[str, Any]:
            self.budget_calls += 1
            reached = self.budget_calls <= self.budget_reached_times
            return {"reached": reached, "spentUsd": 21.0 if reached else 5.0, "capUsd": 20.0}

        return [prepare, write_context, run_pi, check_diff, run_tests, write_failures, commit, open_pr,
                read_notes, emit, check_budget]

    def of(self, type: str, build_id: str | None = None) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == type and (build_id is None or p.get("buildId") == build_id)]


def _queue_activities(redis_url: str) -> list[Callable[..., Any]]:
    real = BuildActivities(BuildEnv(host_dir=__import__("pathlib").Path("/tmp")), redis_url=redis_url, max_slots=1)
    return [real.queue_enter, real.queue_try_acquire, real.queue_release]


def _input(build_id: str) -> dict[str, Any]:
    return BuildInput(ws="test", request_id=f"req_{build_id}", build_id=build_id, revision_hash="h" * 64,
                      ticket={"objective": "x", "targetBranch": "main"}, max_repairs=0).wire()


async def _wait_for(cond: Callable[[], bool], seconds: float = 30.0) -> None:
    for _ in range(int(seconds * 10)):
        if cond():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition not met in time")


async def test_queue_position_with_one_slot(env: Any, redis_url: str, clean_queue: Any) -> None:
    """B-AC-47: with one build slot, a second build shows build.queued {position: 1} and starts after the first."""
    mock = MockSteps()
    mock.gate("q1")
    queue = f"build-{uuid.uuid4().hex[:8]}"
    async with Worker(env.client, task_queue=queue, workflows=[BuildWorkflow],
                      activities=mock.all() + _queue_activities(redis_url)):
        h1 = await env.client.start_workflow(BuildWorkflow.run, _input("q1"), id=f"b-q1-{queue}", task_queue=queue)
        await _wait_for(lambda: "q1" in mock.started)
        h2 = await env.client.start_workflow(BuildWorkflow.run, _input("q2"), id=f"b-q2-{queue}", task_queue=queue)
        await _wait_for(lambda: bool(mock.of("build.queued", "q2")))
        assert mock.of("build.queued", "q1")[0]["position"] == 0
        assert mock.of("build.queued", "q2")[0]["position"] == 1
        assert (await h2.query(BuildWorkflow.status))["queuePosition"] == 1
        assert "q2" not in mock.started
        mock.gates["q1"].set()
        r1 = await h1.result()
        r2 = await h2.result()
    assert r1["status"] == "passed" and r2["status"] == "passed"
    assert mock.started == ["q1", "q2"]
    assert [p["position"] for p in mock.of("build.queued", "q2")][-1] == 0
    assert clean_queue.zcard(QUEUE_KEY) == 0 and clean_queue.zcard(RUNNING_KEY) == 0


async def test_budget_wait_resumes_on_signal(env: Any, redis_url: str, clean_queue: Any) -> None:
    """B-AC-85 (build level): a reached cap makes the build wait; `budget_raised` resumes it."""
    mock = MockSteps()
    mock.budget_reached_times = 1
    queue = f"build-{uuid.uuid4().hex[:8]}"
    async with Worker(env.client, task_queue=queue, workflows=[BuildWorkflow],
                      activities=mock.all() + _queue_activities(redis_url)):
        h = await env.client.start_workflow(BuildWorkflow.run, _input("bud1"), id=f"b-bud1-{queue}", task_queue=queue)
        await _wait_for(lambda: bool([p for t, p in mock.events if p.get("step") == "budget.wait"]))
        assert (await h.query(BuildWorkflow.status))["status"] == "waiting_budget"
        assert mock.started == []
        await h.signal(BuildWorkflow.budget_raised, {"capUsd": 40})
        result = await h.result()
    assert result["status"] == "passed"
    steps = [p.get("step") for t, p in mock.events if t == "build.step"]
    assert steps.index("budget.wait") < steps.index("budget.resumed")


async def test_budget_wait_until_next_day(env: Any, redis_url: str, clean_queue: Any) -> None:
    """B-AC-85 (build level): without a signal the durable timer resumes the build the next UTC day."""
    mock = MockSteps()
    mock.budget_reached_times = 1
    queue = f"build-{uuid.uuid4().hex[:8]}"
    before = await env.get_current_time()
    async with Worker(env.client, task_queue=queue, workflows=[BuildWorkflow],
                      activities=mock.all() + _queue_activities(redis_url)):
        result = await env.client.execute_workflow(BuildWorkflow.run, _input("bud2"), id=f"b-bud2-{queue}",
                                                   task_queue=queue)
    after = await env.get_current_time()
    assert result["status"] == "passed"
    assert after.date() > before.date()
    assert mock.budget_calls == 2


async def test_cancel_kills_pi_container(
    env: Any, build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput],
    fake_github: FakeGitHub, redis_url: str, clean_queue: Any,
) -> None:
    """B-AC-11 at the build level: cancelling the build cancels the Pi activity, which removes its container."""
    events = Events()
    acts = _activities(build_env_factory("timeout"), events, fake_github, redis_url)
    queue = f"build-{uuid.uuid4().hex[:8]}"
    inp = make_input(timeout_seconds=300)
    name = f"actron-pi-{inp.build_id}"
    async with Worker(env.client, task_queue=queue, workflows=[BuildWorkflow], activities=acts.all()):
        h = await env.client.start_workflow(BuildWorkflow.run, inp.wire(), id=f"build:{inp.build_id}",
                                            task_queue=queue)
        await _wait_for(lambda: container_names(name) == [name], seconds=60)
        await h.cancel()
        with pytest.raises(WorkflowFailureError):
            await h.result()
    await _wait_for(lambda: container_names(name) == [], seconds=30)
    assert subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0
    assert clean_queue.zcard(RUNNING_KEY) == 0
