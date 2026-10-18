"""Fixtures for the build tests (W8): the fake Pi image, a synthetic repository, a fake GitHub and graph tools.

- `fake_pi_image`: `actron-fake-pi:test`, built once per session from tests/fakes/fake_pi (a few seconds).
- `test_runner_image`: `actron-test-runner:latest` (built from infra/docker/test-runner.Dockerfile if missing).
- `synthetic_repo`: a tiny Python project (calc/ops.py with add and total, tests/test_ops.py) in a local bare
  repository standing in for the ingested repository, plus an empty bare repository standing in for the fork.
- `fake_github`: an httpx MockTransport implementing the pulls endpoints the build uses.
- `graph_tools`: B.C4-shaped answers for the synthetic repository, recording every call.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from actron.config import REPO_ROOT
from actron.flow.build import BuildEnv, BuildInput

FAKE_PI_DIR = Path(__file__).resolve().parents[2] / "fakes" / "fake_pi"
FAKE_PI_IMAGE = "actron-fake-pi:test"
TEST_RUNNER_IMAGE = "actron-test-runner:latest"
REPO = "acme/calc"
ADD_ID = "code:fn:acme/calc:calc/ops.py::add"
TOTAL_ID = "code:fn:acme/calc:calc/ops.py::total"
TEST_ADD_ID = "code:fn:acme/calc:tests/test_ops.py::test_add"
DECISION_ID = "actron:decision:add-signature"
MODEL_KEY = "sk-ant-test-0000000000000000000000"
GITHUB_TOKEN = "ghp_TESTTOKEN000000000000000000000000000"

OPS_PY = '''def add(a, b):
    return a + b


def total(items):
    result = 0
    for item in items:
        result = add(result, item)
    return result
'''
TEST_OPS_PY = '''from calc.ops import add, total


def test_add():
    assert add(2, 3) == 5


def test_total():
    assert total([1, 2, 3]) == 6
'''


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


@pytest.fixture(scope="session")
def docker_available() -> None:
    if not _docker_ok():
        pytest.skip("Docker is not available")


def _image_exists(tag: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0


@pytest.fixture(scope="session")
def fake_pi_image(docker_available: None) -> str:
    proc = subprocess.run(["docker", "build", "-q", "-t", FAKE_PI_IMAGE, str(FAKE_PI_DIR)],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        pytest.fail(f"could not build the fake Pi image: {proc.stderr[-800:]}")
    return FAKE_PI_IMAGE


@pytest.fixture(scope="session")
def test_runner_image(docker_available: None) -> str:
    if not _image_exists(TEST_RUNNER_IMAGE):
        proc = subprocess.run(
            ["docker", "build", "-q", "-f", "infra/docker/test-runner.Dockerfile", "-t", TEST_RUNNER_IMAGE, "."],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            pytest.fail(f"could not build the test-runner image: {proc.stderr[-800:]}")
    return TEST_RUNNER_IMAGE


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                         cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@dataclass
class SyntheticRepo:
    origin: Path
    fork: Path
    base_sha: str


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> SyntheticRepo:
    work = tmp_path / "src"
    (work / "calc").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "calc" / "__init__.py").write_text("")
    (work / "calc" / "ops.py").write_text(OPS_PY)
    (work / "calc" / "other.py").write_text('VERSION = "1"\n')
    (work / "tests" / "test_ops.py").write_text(TEST_OPS_PY)
    (work / "pyproject.toml").write_text('[project]\nname = "calc"\nversion = "0.1.0"\n\n'
                                         '[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (work / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "initial")
    git(work, "branch", "release-1")
    sha = git(work, "rev-parse", "HEAD")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(origin))
    fork = tmp_path / "fork.git"
    git(tmp_path, "init", "-q", "--bare", str(fork))
    return SyntheticRepo(origin=origin, fork=fork, base_sha=sha)


TICKET: dict[str, Any] = {
    "objective": "Add a subtract function to calc.ops.",
    "context": "Callers need subtraction next to add. add is used by total.",
    "acceptanceCriteria": ["Given 5 and 3 when subtract is called then it returns 2"],
    "constraintsToPreserve": [{"text": "add keeps its signature", "evidenceIds": [DECISION_ID]}],
    "affectedFunctions": [ADD_ID],
    "testPlan": [{"kind": "new", "target": "tests/test_ops.py", "command": "pytest -q"}],
    "outOfScope": ["Changing total"],
    "targetBranch": "main",
}
EVIDENCE: dict[str, Any] = {
    "decisions": [{"id": DECISION_ID, "statement": "add keeps its signature", "status": "approved",
                   "quote": "Let's never change add's arguments, plugins call it.",
                   "source": {"id": "slack:msg:C1:1.0", "type": "SlackMessage",
                              "url": "https://example.slack.com/archives/C1/p10"}}],
    "impact": {"callers": [{"id": TOTAL_ID, "depth": 1}], "tests": [{"id": TEST_ADD_ID}],
               "criticality": [{"id": ADD_ID, "percentile": 97.5}]},
}


@pytest.fixture
def make_input(synthetic_repo: SyntheticRepo) -> Callable[..., BuildInput]:
    counter = {"n": 0}

    def make(**overrides: Any) -> BuildInput:
        counter["n"] += 1
        data: dict[str, Any] = dict(
            ws="test", request_id="req_01TEST", build_id=f"b{counter['n']}x{id(counter) % 10000}",
            revision_hash="a" * 64, revision=1, ticket=json.loads(json.dumps(TICKET)),
            evidence=json.loads(json.dumps(EVIDENCE)), procedures=[], max_repairs=2, timeout_seconds=120,
            repository=REPO, repo_url=str(synthetic_repo.origin), push_target="acme/calc-fork",
            push_url=str(synthetic_repo.fork), upstream=REPO, working_branch="main", ticket_identifier="ENG-12",
        )
        data.update(overrides)
        return BuildInput(**data)

    return make


@pytest.fixture
def build_env_factory(tmp_path: Path, fake_pi_image: str, test_runner_image: str) -> Callable[..., BuildEnv]:
    def make(scenario: str = "success", **overrides: Any) -> BuildEnv:
        values: dict[str, Any] = dict(
            host_dir=tmp_path / "builds", pi_image=fake_pi_image, test_image=test_runner_image,
            network="actron-build", mcp_url="http://worker:8765/mcp", model_coding="anthropic/claude-sonnet-4-5",
            model_keys={"ANTHROPIC_API_KEY": MODEL_KEY}, bot_name="Actron Bot", bot_email="bot@actron.test",
            github_api_url="https://api.github.test", github_token=GITHUB_TOKEN, github_fork="acme/calc-fork",
            github_upstream=REPO, test_timeout_seconds=300, pi_extra_env={"FAKE_PI_SCENARIO": scenario},
        )
        values.update(overrides)
        return BuildEnv(**values)

    return make


@dataclass
class Events:
    items: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None:
        self.items.append((type, payload))

    def of(self, type: str) -> list[dict[str, Any]]:
        return [p for t, p in self.items if t == type]

    def steps(self, step: str) -> list[dict[str, Any]]:
        return [p for p in self.of("build.step") if p.get("step") == step]


@pytest.fixture
def events() -> Events:
    return Events()


@dataclass
class FakeGitHub:
    pulls: list[dict[str, Any]] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parts = request.url.path.strip("/").split("/")
        if parts[:1] != ["repos"] or len(parts) < 4 or parts[3] != "pulls":
            return httpx.Response(404, json={"message": "Not Found"})
        repo = f"{parts[1]}/{parts[2]}"
        if request.method == "GET":
            head = request.url.params.get("head", "")
            branch = head.split(":", 1)[-1]
            return httpx.Response(200, json=[p for p in self.pulls if p["repo"] == repo
                                             and p["head"]["ref"] == branch and p["state"] == "open"])
        if request.method == "POST":
            body = json.loads(request.content)
            pr = {"repo": repo, "number": len(self.pulls) + 1, "state": "open", "title": body["title"],
                  "body": body["body"], "base": {"ref": body["base"]}, "head": {"ref": body["head"], "sha": ""},
                  "html_url": f"https://github.test/{repo}/pull/{len(self.pulls) + 1}"}
            self.pulls.append(pr)
            return httpx.Response(201, json=pr)
        if request.method == "PATCH":
            number = int(parts[4])
            pr = next(p for p in self.pulls if p["number"] == number)
            pr.update(json.loads(request.content))
            return httpx.Response(200, json=pr)
        return httpx.Response(405)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def fake_github() -> FakeGitHub:
    return FakeGitHub()


@dataclass
class FakeGraphTools:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def __call__(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        fid = args.get("id") or args.get("functionId") or (args.get("ids") or [None])[0]
        if name == "get_code" and fid == ADD_ID:
            return {"id": ADD_ID, "path": "calc/ops.py", "startLine": 1, "endLine": 2, "language": "python",
                    "code": "def add(a, b):\n    return a + b", "snapshot": "base"}
        if name == "get_code" and fid == TEST_ADD_ID:
            return {"id": TEST_ADD_ID, "path": "tests/test_ops.py", "startLine": 4, "endLine": 5,
                    "language": "python", "code": "def test_add():\n    assert add(2, 3) == 5"}
        if name == "callers" and fid == ADD_ID:
            return [{"id": TOTAL_ID, "label": "total", "depth": 1, "callSiteLines": [8], "confidence": 1.0}]
        if name == "references" and fid == ADD_ID:
            return [{"callerId": TOTAL_ID, "callerQualifiedName": "total", "path": "calc/ops.py", "line": 8,
                     "snippet": "    result = 0\n    for item in items:\n        result = add(result, item)\n"
                                "    return result"}]
        if name == "callees":
            return []
        if name == "tests_for" and fid == ADD_ID:
            return [{"testId": TEST_ADD_ID, "label": "test_add", "method": "name", "confidence": 0.9}]
        if name == "decisions_for" and fid == ADD_ID:
            return [{"decisionId": DECISION_ID, "statement": "add keeps its signature", "status": "approved",
                     "quote": "Let's never change add's arguments, plugins call it.",
                     "source": {"type": "SlackMessage", "url": "https://example.slack.com/archives/C1/p10"},
                     "constrains": [ADD_ID]}]
        if name == "file_outline":
            return {"path": args.get("path"), "language": "python", "classes": [], "imports": [],
                    "functions": [{"id": ADD_ID, "qualifiedName": "add", "signature": "def add(a, b)",
                                   "startLine": 1, "endLine": 2},
                                  {"id": TOTAL_ID, "qualifiedName": "total", "signature": "def total(items)",
                                   "startLine": 5, "endLine": 9}]}
        if name == "procedures_for":
            return [{"procedureId": "actron:procedure:calc", "title": "calc changes", "testCommand": "pytest -q",
                     "coChangedPaths": ["calc/ops.py", "tests/test_ops.py"], "steps": []}]
        return {"error": {"code": "not_found", "message": f"{name} has no answer"}}


@pytest.fixture
def graph_tools() -> FakeGraphTools:
    return FakeGraphTools()


async def scope_high(ticket: dict[str, Any], diff: str, outside: list[str]) -> tuple[float, bool]:
    return 0.9, False


async def scope_low(ticket: dict[str, Any], diff: str, outside: list[str]) -> tuple[float, bool]:
    return 0.1, False


def container_names(prefix: str) -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
    return [n for n in out.stdout.split() if n.startswith(prefix)]
