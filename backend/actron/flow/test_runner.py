"""Test step of the build (spec B, B9 step 5): command resolution, dependency preparation, offline run, parsers.

Two containers from the `actron-test-runner` image:
- prepare: has network, never has credentials; installs dependencies into a cache keyed by the lockfile hash.
- run: `--network none`; mounts the checkout, the dependency cache and a reports folder.
Each container is created, started, inspected and removed explicitly so the isolation evidence
(network mode and environment variable names) is recorded with the result.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shlex
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from actron.logging import get_logger

log = get_logger(__name__)

TestSource = Literal["ticket", "procedure", "repo_default"]
ParserName = Literal["junit", "mocha", "jest", "vitest", "exit_code"]

OUTPUT_TAIL_LINES = 200
FAILURE_OUTPUT_CHARS = 4000


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class FailingTest(_Camel):
    name: str
    output: str = ""


class Isolation(_Camel):
    """What `docker inspect` said about a container before it was removed."""

    container: str
    network_mode: str
    env_names: list[str] = Field(default_factory=list)


class TestResult(_Camel):
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failing: list[FailingTest] = Field(default_factory=list)
    exit_code: int = 0
    command: str = ""
    source: TestSource = "repo_default"
    parser: ParserName = "exit_code"
    output_tail: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    isolation: Isolation | None = None
    prepare_isolation: Isolation | None = None

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.exit_code == 0 and not self.timed_out

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


class NoTestCommand(RuntimeError):
    """No test command could be found for this repository."""


# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------


def _package_json(repo_dir: Path) -> dict[str, Any] | None:
    path = repo_dir / "package.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_python_repo(repo_dir: Path) -> bool:
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "requirements.txt")
    if any((repo_dir / m).exists() for m in markers):
        return True
    return any(repo_dir.glob("test*/**/*.py")) or any(repo_dir.glob("test_*.py"))


def repo_default_command(repo_dir: Path) -> str | None:
    """Repository default: Node `unit-test`/`test` script, then pytest, then the Clojure test alias."""
    pkg = _package_json(repo_dir)
    scripts = (pkg or {}).get("scripts") or {}
    if isinstance(scripts, dict):
        if scripts.get("unit-test"):
            return "npm run unit-test -- --reporter json"
        if scripts.get("test"):
            return "npm test"
    if _is_python_repo(repo_dir):
        return "pytest -q"
    if (repo_dir / "deps.edn").is_file():
        return "clojure -M:test"
    return None


def resolve_test_command(
    ticket: dict[str, Any], procedures: list[dict[str, Any]], repo_dir: Path
) -> tuple[str, TestSource]:
    """Order: the ticket's test plan → the area's procedure → the repository default."""
    commands: list[str] = []
    for item in ticket.get("testPlan") or []:
        cmd = str((item or {}).get("command") or "").strip()
        if cmd and cmd not in commands:
            commands.append(cmd)
    if commands:
        if len(commands) > 1 and all(c.split()[0] == "pytest" for c in commands):
            args: list[str] = []
            for c in commands:
                args.extend(a for a in shlex.split(c)[1:] if a not in args)
            return "pytest " + " ".join(shlex.quote(a) for a in args), "ticket"
        return commands[0], "ticket"
    for proc in procedures:
        cmd = str(proc.get("testCommand") or "").strip()
        if cmd:
            return cmd, "procedure"
    default = repo_default_command(repo_dir)
    if default:
        return default, "repo_default"
    raise NoTestCommand("No test command in the ticket, the procedure or the repository.")


def _npm_script_body(repo_dir: Path, command: str) -> str:
    pkg = _package_json(repo_dir) or {}
    scripts = pkg.get("scripts") or {}
    m = re.match(r"^\s*npm\s+(?:run\s+)?(?:run-script\s+)?([\w:-]+)", command)
    if not m or not isinstance(scripts, dict):
        return ""
    name = "test" if m.group(1) in ("test", "t") else m.group(1)
    return str(scripts.get(name) or "")


def instrument_command(command: str, repo_dir: Path) -> tuple[str, ParserName]:
    """Add a machine-readable reporter where the runner supports one."""
    words = shlex.split(command) if command.strip() else []
    head = " ".join(words[:3])
    if re.match(r"^(uv run |python3? -m )?pytest\b", head) and "--junitxml" not in command:
        return f"{command} --junitxml=/reports/junit.xml", "junit"
    if "--reporter json" in command or "--reporter=json" in command:
        if "vitest" in command or "vitest" in _npm_script_body(repo_dir, command):
            return command, "vitest"
        return command, "mocha"
    body = _npm_script_body(repo_dir, command) if words[:1] == ["npm"] else ""
    target = f"{command} {body}"
    sep = " -- " if words[:1] == ["npm"] and " -- " not in command else " "
    if "vitest" in target:
        return f"{command}{sep}--reporter=json --outputFile=/reports/vitest.json", "vitest"
    if "jest" in target:
        return f"{command}{sep}--json --outputFile=/reports/jest.json", "jest"
    if "mocha" in target:
        return f"{command}{sep}--reporter json", "mocha"
    return command, "exit_code"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _tail(text: str, lines: int = OUTPUT_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def parse_junit_xml(xml_text: str) -> TestResult:
    root = ET.fromstring(xml_text)
    result = TestResult(parser="junit")
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = f"{cls}::{case.get('name')}" if cls else str(case.get("name"))
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is not None:
            result.failed += 1
            text = (problem.get("message") or "") + "\n" + (problem.text or "")
            result.failing.append(FailingTest(name=name, output=text.strip()[:FAILURE_OUTPUT_CHARS]))
        elif case.find("skipped") is not None:
            result.skipped += 1
        else:
            result.passed += 1
    return result


def _first_json_object(text: str, required_key: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and required_key in obj:
            return obj
    return None


def parse_mocha_json(text: str) -> TestResult:
    data = _first_json_object(text, "stats")
    if data is None:
        raise ValueError("no mocha JSON report in the output")
    stats = data.get("stats") or {}
    result = TestResult(
        parser="mocha",
        passed=int(stats.get("passes", 0)),
        failed=int(stats.get("failures", 0)),
        skipped=int(stats.get("pending", 0)),
    )
    for f in data.get("failures") or []:
        err = f.get("err") or {}
        output = f"{err.get('message', '')}\n{err.get('stack', '')}".strip()
        result.failing.append(
            FailingTest(name=str(f.get("fullTitle") or f.get("title")), output=output[:FAILURE_OUTPUT_CHARS])
        )
    return result


def parse_jest_json(text: str, parser: Literal["jest", "vitest"] = "jest") -> TestResult:
    """Jest's `--json` report; Vitest's JSON reporter writes the same shape."""
    data = _first_json_object(text, "numTotalTests")
    if data is None:
        raise ValueError(f"no {parser} JSON report")
    result = TestResult(
        parser=parser,
        passed=int(data.get("numPassedTests", 0)),
        failed=int(data.get("numFailedTests", 0)),
        skipped=int(data.get("numPendingTests", 0)) + int(data.get("numTodoTests", 0)),
    )
    for suite in data.get("testResults") or []:
        for a in suite.get("assertionResults") or []:
            if a.get("status") == "failed":
                output = "\n".join(str(m) for m in a.get("failureMessages") or [])
                name = str(a.get("fullName") or a.get("title"))
                result.failing.append(FailingTest(name=name, output=output[:FAILURE_OUTPUT_CHARS]))
    return result


def parse_exit_code(exit_code: int, output: str, command: str) -> TestResult:
    """Fallback when no reporter is available: the exit code and the last 200 lines of output."""
    tail = _tail(output)
    if exit_code == 0:
        return TestResult(parser="exit_code", passed=1, exit_code=0)
    return TestResult(
        parser="exit_code", failed=1, exit_code=exit_code, failing=[FailingTest(name=command, output=tail)]
    )


def parse_results(
    parser: ParserName, *, exit_code: int, output: str, reports_dir: Path, command: str
) -> TestResult:
    try:
        if parser == "junit":
            path = reports_dir / "junit.xml"
            if path.is_file():
                res = parse_junit_xml(path.read_text(encoding="utf-8"))
                if res.total or exit_code == 0:
                    res.exit_code = exit_code
                    return res
        elif parser == "mocha":
            res = parse_mocha_json(output)
            res.exit_code = exit_code
            return res
        elif parser in ("jest", "vitest"):
            path = reports_dir / f"{parser}.json"
            text = path.read_text(encoding="utf-8") if path.is_file() else output
            res = parse_jest_json(text, parser)
            res.exit_code = exit_code
            return res
    except (ValueError, ET.ParseError, OSError) as exc:
        log.info("test report not parsed, using the exit code", extra={"parser": parser, "error": str(exc)})
    return parse_exit_code(exit_code, output, command)


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------


@dataclass
class ContainerRun:
    exit_code: int
    output: str
    timed_out: bool
    isolation: Isolation
    argv: list[str] = field(default_factory=list)


def docker_env() -> dict[str, str]:
    """Environment for the docker CLI itself: only what it needs to reach the daemon."""
    keep = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR")
    return {k: v for k, v in os.environ.items() if k in keep}


async def run_cmd(
    argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 120.0, cwd: Path | None = None
) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env if env is not None else docker_env(),
        cwd=str(cwd) if cwd else None,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        return 124, "timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def remove_container(name: str) -> None:
    await run_cmd(["docker", "rm", "-f", name], timeout=60)


async def container_exists(name: str) -> bool:
    code, _ = await run_cmd(["docker", "inspect", "--format", "{{.Id}}", name], timeout=30)
    return code == 0


def host_user() -> str:
    return f"{os.getuid()}:{os.getgid()}"


async def run_container(
    name: str, run_args: list[str], image: str, command: list[str], *, timeout: float
) -> ContainerRun:
    """docker create → inspect → start -a → remove. The container never outlives this call."""
    await remove_container(name)
    create = ["docker", "create", "--name", name, *run_args, image, *command]
    code, out = await run_cmd(create, timeout=120)
    if code != 0:
        raise RuntimeError(f"docker create failed: {out.strip()[-500:]}")
    try:
        code, raw = await run_cmd(
            ["docker", "inspect", "--format", "{{json .HostConfig.NetworkMode}}|{{json .Config.Env}}", name],
            timeout=30,
        )
        network, _, env_json = raw.strip().partition("|")
        env_names = [e.split("=", 1)[0] for e in (json.loads(env_json) if env_json else []) or []]
        isolation = Isolation(container=name, network_mode=json.loads(network or '""'), env_names=env_names)
        start_code, output = await run_cmd(["docker", "start", "-a", name], timeout=timeout)
        timed_out = start_code == 124 and output == "timed out"
        if timed_out:
            await run_cmd(["docker", "kill", name], timeout=30)
            return ContainerRun(124, "", True, isolation, create)
        code, state = await run_cmd(["docker", "inspect", "--format", "{{.State.ExitCode}}", name], timeout=30)
        exit_code = int(state.strip()) if code == 0 and state.strip().isdigit() else start_code
        return ContainerRun(exit_code, output, False, isolation, create)
    finally:
        await remove_container(name)


# ---------------------------------------------------------------------------
# Dependency preparation (networked, no credentials) and the offline run
# ---------------------------------------------------------------------------


@dataclass
class DepsPlan:
    kind: Literal["node", "python", "clojure", "none"]
    lockfile: str | None
    install: str
    cache_mounts: list[tuple[str, str]]  # (subdir in the cache, path in the container)
    run_env: dict[str, str] = field(default_factory=dict)


# Node 22.18+ strips TypeScript types natively by default, which bypasses ts-node and breaks projects that run
# their TypeScript tests through `ts-node/register` (Calva: "Cannot find module .../cursor-doc/model"). Turn it off
# so the tests run the way the project's own CI (Node 22.16) runs them.
NODE_RUN_ENV = {"NODE_OPTIONS": "--no-experimental-strip-types"}


def plan_dependencies(repo_dir: Path) -> list[DepsPlan]:
    plans: list[DepsPlan] = []
    if (repo_dir / "pnpm-lock.yaml").is_file():
        plans.append(DepsPlan("node", "pnpm-lock.yaml", "pnpm install --frozen-lockfile",
                              [("node_modules", "/work/node_modules")], NODE_RUN_ENV))
    elif (repo_dir / "package-lock.json").is_file():
        plans.append(DepsPlan("node", "package-lock.json", "npm ci --no-audit --no-fund",
                              [("node_modules", "/work/node_modules")], NODE_RUN_ENV))
    if (repo_dir / "deps.edn").is_file() or (repo_dir / "shadow-cljs.edn").is_file():
        lock = "deps.edn" if (repo_dir / "deps.edn").is_file() else "shadow-cljs.edn"
        install = "clojure -P" if lock == "deps.edn" else "npx --no-install shadow-cljs classpath >/dev/null"
        plans.append(DepsPlan("clojure", lock, install, [("m2", "/home/runner/.m2")]))
    if (repo_dir / "requirements.txt").is_file():
        plans.append(DepsPlan("python", "requirements.txt",
                              "pip install --no-cache-dir --target /deps -r requirements.txt",
                              [("py", "/deps")], {"PYTHONPATH": "/deps"}))
    elif (repo_dir / "uv.lock").is_file():
        plans.append(DepsPlan("python", "uv.lock",
                              "uv export --frozen --no-hashes -o /tmp/req.txt && "
                              "pip install --no-cache-dir --target /deps -r /tmp/req.txt",
                              [("py", "/deps")], {"PYTHONPATH": "/deps"}))
    return plans


def cache_dir_for(cache_root: Path, repo_dir: Path, plan: DepsPlan) -> Path:
    digest = "none"
    if plan.lockfile:
        digest = hashlib.sha256((repo_dir / plan.lockfile).read_bytes()).hexdigest()[:16]
    return cache_root / f"{plan.kind}-{digest}"


@dataclass
class TestRunConfig:
    image: str
    cache_root: Path
    timeout_seconds: float = 900.0
    prepare_timeout_seconds: float = 1200.0


CLJS_OUTPUT = "out/cljs-lib/cljs-lib.js"


def needs_cljs_build(repo_dir: Path) -> bool:
    """Calva-style projects: TypeScript imports a ClojureScript build that `npm run compile-cljs` makes."""
    package = repo_dir / "package.json"
    if not (repo_dir / "shadow-cljs.edn").is_file() or not package.is_file() or (repo_dir / CLJS_OUTPUT).is_file():
        return False
    try:
        scripts = json.loads(package.read_text()).get("scripts") or {}
    except ValueError:
        return False
    return "compile-cljs" in scripts


async def compile_cljs_if_needed(
    repo_dir: Path, build_id: str, prepared: list[tuple[Path, DepsPlan]], cfg: TestRunConfig
) -> Isolation | None:
    """Build the ClojureScript library once with the network on (it downloads Clojure dependencies), so the
    offline test run finds it. The tests can never build it themselves: they run with no network."""
    if not needs_cljs_build(repo_dir):
        return None
    mounts: list[str] = ["-v", f"{repo_dir}:/work"]
    for cache, plan in prepared:
        for sub, target in plan.cache_mounts:
            mounts += ["-v", f"{cache / sub}:{target}"]
        for k, v in plan.run_env.items():
            mounts += ["-e", f"{k}={v}"]
    if not any(plan.kind == "clojure" for _, plan in prepared):  # keep downloaded jars between builds
        m2 = cfg.cache_root / "m2-shared"
        m2.mkdir(parents=True, exist_ok=True)
        mounts += ["-v", f"{m2}:/home/runner/.m2"]
    run = await run_container(
        f"actron-test-cljs-{build_id}", ["--user", host_user(), "-w", "/work", *mounts], cfg.image,
        ["sh", "-c", "npm run compile-cljs"], timeout=cfg.prepare_timeout_seconds,
    )
    if run.exit_code != 0:
        raise RuntimeError(f"ClojureScript build failed (npm run compile-cljs): {_tail(run.output, 40)}")
    return run.isolation


async def prepare_dependencies(
    repo_dir: Path, build_id: str, cfg: TestRunConfig
) -> tuple[list[tuple[Path, DepsPlan]], Isolation | None]:
    """Install dependencies once per lockfile hash. Network on, credentials never passed."""
    prepared: list[tuple[Path, DepsPlan]] = []
    isolation: Isolation | None = None
    for plan in plan_dependencies(repo_dir):
        cache = cache_dir_for(cfg.cache_root, repo_dir, plan)
        ready = cache / ".ready"
        for sub, _ in plan.cache_mounts:
            (cache / sub).mkdir(parents=True, exist_ok=True)
        if not ready.exists():
            mounts: list[str] = ["-v", f"{repo_dir}:/work"]
            for sub, target in plan.cache_mounts:
                mounts += ["-v", f"{cache / sub}:{target}"]
            args = ["--user", host_user(), "-w", "/work", *mounts]
            run = await run_container(
                f"actron-test-prep-{build_id}-{plan.kind}", args, cfg.image,
                ["sh", "-c", plan.install], timeout=cfg.prepare_timeout_seconds,
            )
            isolation = run.isolation
            if run.exit_code != 0:
                raise RuntimeError(f"dependency install failed ({plan.install}): {_tail(run.output, 40)}")
            ready.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        prepared.append((cache, plan))
    built = await compile_cljs_if_needed(repo_dir, build_id, prepared, cfg)
    return prepared, built or isolation


async def run_tests(
    repo_dir: Path,
    reports_dir: Path,
    build_id: str,
    command: str,
    source: TestSource,
    cfg: TestRunConfig,
) -> TestResult:
    """Prepare dependencies (networked), then run the tests in a container with no network."""
    started = time.monotonic()
    prepared, prep_isolation = await prepare_dependencies(repo_dir, build_id, cfg)
    reports_dir.mkdir(parents=True, exist_ok=True)
    for old in reports_dir.glob("*"):
        old.unlink()
    instrumented, parser = instrument_command(command, repo_dir)
    args = ["--network", "none", "--user", host_user(), "-w", "/work",
            "-v", f"{repo_dir}:/work", "-v", f"{reports_dir}:/reports"]
    for cache, plan in prepared:
        for sub, target in plan.cache_mounts:
            args += ["-v", f"{cache / sub}:{target}"]
        for k, v in plan.run_env.items():
            args += ["-e", f"{k}={v}"]
    run = await run_container(
        f"actron-test-run-{build_id}", args, cfg.image, ["sh", "-c", instrumented], timeout=cfg.timeout_seconds
    )
    if run.timed_out:
        result = TestResult(parser="exit_code", failed=1, exit_code=124, timed_out=True,
                            failing=[FailingTest(name=command, output="The test run timed out.")])
    else:
        result = parse_results(parser, exit_code=run.exit_code, output=run.output,
                               reports_dir=reports_dir, command=command)
    result.command = command
    result.source = source
    result.output_tail = _tail(run.output)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    result.isolation = run.isolation
    result.prepare_isolation = prep_isolation
    return result
