"""Build with Pi (spec B, B9; contract B.C6).

Steps are plain async functions; `run_build` runs them in order through a `BuildSteps` object, so the same
loop runs in-process (tests, CLI) and inside `BuildWorkflow` (each step an activity).

prepare_checkout → write_build_context → [run_pi → check_diff → run_tests → repair?]* → commit_and_push →
open_or_update_pr.

Safety (PROMPT 2, PRD 15): Pi runs only in Docker, gets one model key (passed by name, the value only in the
docker CLI's environment), the checkout and the context; never GitHub, Slack or Linear credentials. The push
uses a credential helper that reads GITHUB_TOKEN from the environment of that one git process; the token is
never in a command line or a remote URL. PRs go only to the effective push target.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from actron.flow import diff_check as dc
from actron.flow import test_runner as tr
from actron.flow.context_pack import ContextPack, ToolCaller, build_context_pack, empty_tools
from actron.logging import get_logger

log = get_logger(__name__)

BuildStatus = Literal["passed", "failed", "stopped"]
STOP_REASONS = ("missing_fork", "missing_branch", "missing_identity", "no_model_key", "tests_weakened",
                "scope_change", "token_budget")
FIRST_MESSAGE = "Follow /context/TASK.md exactly. Start with step 1."
EXPLORATION_REMINDER = ("Use the graph tools (get_code, file_outline, find_symbol, references, search_code) "
                        "instead of exploring the repository.")
GRAPH_FIRST_REMINDER = ("Before you change a function that other code calls, ask the graph for its callers "
                        "(callers, references or impact).")
PLAN_REMINDER = "Write a short plan at the top of /context/notes.md before you change any code."
EXPLORATION_REMINDER_AT = 3
EXPLORATION_STOP_AT = 10
PLAN_WITHIN_TOOL_EVENTS = 5
HEARTBEAT_SECONDS = 10.0
PUSH_REMOTE = "actron-push"


class EventSink(Protocol):
    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None: ...


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# ---------------------------------------------------------------------------
# B.C6 contract
# ---------------------------------------------------------------------------


class BuildInput(_Camel):
    """B.C6 `BuildInput` plus the effective repository values the build needs (spec A, A11 step 3)."""

    ws: str
    request_id: str
    build_id: str
    revision_hash: str
    revision: int = 1
    ticket: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)
    procedures: list[dict[str, Any]] = Field(default_factory=list)
    base_sha: str | None = None
    branch: str | None = None
    test_command: str | None = None
    max_repairs: int = 2
    timeout_seconds: int = 1800
    # Effective repository values.
    repository: str = ""
    repo_url: str | None = None
    push_target: str | None = None
    push_url: str | None = None
    upstream: str | None = None
    working_branch: str | None = None
    # Optional context.
    ticket_identifier: str | None = None
    existing_pr_number: int | None = None
    previous_build: dict[str, Any] | None = None
    max_tokens: int | None = None

    @property
    def build_branch(self) -> str:
        return self.branch or f"actron/{self.request_id}-r{self.revision}"

    @property
    def target_branch(self) -> str:
        return str(self.ticket.get("targetBranch") or self.working_branch or "main")


class Tokens(_Camel):
    input: int = 0
    output: int = 0


class BuildResult(_Camel):
    """B.C6 `BuildResult` plus what the Build tab and write-back need."""

    status: BuildStatus
    head_sha: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    failing: list[dict[str, Any]] = Field(default_factory=list)
    attempts: int = 0
    stop_reason: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    tokens: Tokens = Field(default_factory=Tokens)
    duration_ms: int = 0
    build_id: str = ""
    branch: str = ""
    base_sha: str = ""
    report: dict[str, Any] | None = None
    test_command: str | None = None
    test_command_source: str | None = None
    guards: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    diff_summary: str = ""


class BuildStop(Exception):
    """A documented reason to stop the build (B9): missing_fork, missing_branch, missing_identity, ..."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


class CheckoutInfo(_Camel):
    base_sha: str
    branch: str
    root: str
    repo_dir: str
    differing_files: list[str] = Field(default_factory=list)
    continued: bool = False
    test_command: str = ""
    test_command_source: str = "repo_default"


class ContextInfo(_Camel):
    pack_size: int
    pack_tier: str
    where_to_work: list[str]
    meta: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ConstraintProof(BaseModel):
    constraint: str
    how: str


class PiReport(BaseModel):
    """Schema of /context/REPORT.json (B9 work protocol step 10)."""

    model_config = ConfigDict(extra="forbid")
    filesChanged: list[str]
    testsAdded: list[str]
    testCommand: str
    testsPassed: bool
    constraintsPreserved: list[ConstraintProof]
    stopped: bool
    notes: str


class PiAttempt(_Camel):
    attempt: int
    exit_code: int | None = None
    timed_out: bool = False
    stopped_for_exploration: bool = False
    model_error: str | None = None
    tokens: Tokens = Field(default_factory=Tokens)
    tool_events: int = 0
    exploration_count: int = 0
    outside_reads: int = 0
    reminders: list[str] = Field(default_factory=list)
    graph_first_misses: list[str] = Field(default_factory=list)
    plan_ok: bool = False
    report_ok: bool = False
    report: dict[str, Any] | None = None
    report_errors: str = ""
    tests_after_last_edit: bool = False
    edited_files: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    stop_text: str = ""
    session_id: str = ""

    def missing_items(self) -> list[str]:
        out = []
        if not self.plan_ok:
            out.append("plan")
        if not self.report_ok:
            out.append("report")
        if not self.tests_after_last_edit:
            out.append("tests_after_last_edit")
        return out


class PrInfo(_Camel):
    number: int
    url: str
    head_sha: str
    action: Literal["opened", "updated"]


# ---------------------------------------------------------------------------
# Environment of the orchestrator
# ---------------------------------------------------------------------------

MODEL_PROVIDERS: dict[str, tuple[str, str]] = {
    # LiteLLM-style prefix -> (Pi provider name, key variable). Verified in the image with --list-models.
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "openrouter": ("openrouter", "OPENROUTER_API_KEY"),
    "gemini": ("google", "GEMINI_API_KEY"),
    "google": ("google", "GEMINI_API_KEY"),
    "groq": ("groq", "GROQ_API_KEY"),
    "deepseek": ("deepseek", "DEEPSEEK_API_KEY"),
}


@dataclass
class BuildEnv:
    host_dir: Path
    pi_image: str = "actron-pi:latest"
    test_image: str = "actron-test-runner:latest"
    network: str = "actron-build"
    mcp_url: str = "http://worker:8765/mcp"
    model_coding: str | None = None
    model_keys: dict[str, str] = field(default_factory=dict)
    bot_name: str | None = None
    bot_email: str | None = None
    github_api_url: str = "https://api.github.com"
    github_token: str | None = None
    github_fork: str | None = None
    github_upstream: str | None = None
    test_timeout_seconds: float = 900.0
    pack_limit: int = 60_000
    # Test-only: extra non-secret variables for the Pi container (the fake Pi's scenario).
    pi_extra_env: dict[str, str] = field(default_factory=dict)
    # Base of clone and push URLs when the input carries none (settings GITHUB_GIT_URL).
    git_base_url: str = "https://github.com"

    @classmethod
    def from_settings(cls) -> BuildEnv:
        from actron.config import get_settings

        s = get_settings()
        keys = {name: v for name in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
                                 "DEEPSEEK_API_KEY")
                if (v := getattr(s, name, None))}
        return cls(
            host_dir=Path(s.ACTRON_BUILD_HOST_DIR), pi_image=s.ACTRON_PI_IMAGE, test_image=s.ACTRON_TEST_RUNNER_IMAGE,
            mcp_url=s.ACTRON_MCP_URL, model_coding=s.MODEL_CODING, model_keys=keys, bot_name=s.ACTRON_BOT_NAME,
            bot_email=s.ACTRON_BOT_EMAIL, github_api_url=s.GITHUB_API_URL, github_token=s.GITHUB_TOKEN,
            github_fork=s.GITHUB_FORK, github_upstream=s.GITHUB_UPSTREAM,
            pi_extra_env={} if s.ACTRON_ENV == "prod" else dict(s.ACTRON_PI_EXTRA_ENV),
            git_base_url=s.GITHUB_GIT_URL,
        )

    def git_url(self, repo: str) -> str:
        return f"{self.git_base_url.rstrip('/')}/{repo}.git"

    def with_bot_identity(self, stored: dict[str, Any] | None) -> BuildEnv:
        """Copy using the workspace's stored bot identity first, then this env's (`.env`) values, per field."""
        stored = stored or {}
        name = str(stored.get("name") or "").strip() or self.bot_name
        email = str(stored.get("email") or "").strip() or self.bot_email
        return replace(self, bot_name=name, bot_email=email)

    def for_workspace(self, ws: str) -> BuildEnv:
        """The env for a build in workspace `ws`: Settings' bot identity (PUT /api/settings) over `.env`."""
        from actron.db import models as m
        from actron.db.session import session_scope

        try:
            with session_scope() as session:
                row = session.get(m.Workspace, ws)
                stored = dict((row.settings if row else None) or {}).get("botIdentity")
        except Exception:  # a settings read failure must not stop a build; `.env` still applies
            stored = None
        return self.with_bot_identity(stored)

    def model_choice(self) -> tuple[str, str]:
        """Return (Pi --model value, the ONE key variable to pass). Raises BuildStop('no_model_key')."""
        model = (self.model_coding or "").strip()
        if not model:
            raise BuildStop("no_model_key", "MODEL_CODING is not set.")
        prefix, _, rest = model.partition("/")
        if prefix in MODEL_PROVIDERS and rest:
            provider, key = MODEL_PROVIDERS[prefix]
            if key not in self.model_keys:
                raise BuildStop("no_model_key", f"{key} is not set for MODEL_CODING={model}.")
            return f"{provider}/{rest}", key
        for _, (provider, key) in MODEL_PROVIDERS.items():
            if key in self.model_keys:
                return f"{provider}/{model}", key
        raise BuildStop("no_model_key", "No model key is set for the coding model.")


@dataclass
class BuildPaths:
    root: Path

    @classmethod
    def for_build(cls, host_dir: Path, build_id: str) -> BuildPaths:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", build_id):
            raise ValueError(f"unsafe build id {build_id!r}")
        return cls(host_dir / build_id)

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def context(self) -> Path:
        return self.root / "context"

    @property
    def session(self) -> Path:
        return self.root / "session"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def credential_helper(self) -> Path:
        return self.root / "git-credential-actron"

    def pi_log(self, attempt: int) -> Path:
        return self.root / f"pi-attempt-{attempt}.jsonl"


# ---------------------------------------------------------------------------
# Command running (recorded, so tests can inspect every argv and environment)
# ---------------------------------------------------------------------------


@dataclass
class CommandRecord:
    argv: list[str]
    env: dict[str, str]


@dataclass
class Runner:
    records: list[CommandRecord] = field(default_factory=list)

    async def git(self, repo: Path | None, *args: str, token: str | None = None,
                  helper: Path | None = None, timeout: float = 300.0) -> tuple[int, str]:
        argv = ["git"]
        if helper is not None:
            # Reset inherited helpers, then use ours; it reads GITHUB_TOKEN from this process's environment.
            argv += ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]
        if repo is not None:
            argv += ["-C", str(repo)]
        argv += list(args)
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
        if token:
            env["GITHUB_TOKEN"] = token
        self.records.append(CommandRecord(argv, env))
        return await tr.run_cmd(argv, env=env, timeout=timeout)


CREDENTIAL_HELPER = """#!/bin/sh
# Actron git credential helper: answers only "get", reads the token from this process's environment.
[ "$1" = "get" ] || exit 0
[ -n "$GITHUB_TOKEN" ] || exit 0
echo "username=x-access-token"
echo "password=$GITHUB_TOKEN"
"""


def write_credential_helper(paths: BuildPaths) -> Path:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.credential_helper.write_text(CREDENTIAL_HELPER)
    paths.credential_helper.chmod(0o700)
    return paths.credential_helper


# ---------------------------------------------------------------------------
# Step 1: checkout
# ---------------------------------------------------------------------------


def preflight(inp: BuildInput, env: BuildEnv) -> tuple[str, str]:
    """Checks that must pass before any container runs (B-AC-44). Returns (push_target, push_url)."""
    push_target = (inp.push_target or env.github_fork or "").strip()
    upstream = (inp.upstream or env.github_upstream or "").strip()
    if not push_target or (upstream and push_target.lower() == upstream.lower()):
        raise BuildStop("missing_fork", "There is no fork to push to, or the fork is the upstream repository.")
    if not (env.bot_name or "").strip() or not (env.bot_email or "").strip():
        raise BuildStop("missing_identity", "ACTRON_BOT_NAME and ACTRON_BOT_EMAIL must be set to commit.")
    env.model_choice()
    push_url = inp.push_url or env.git_url(push_target)
    if "@" in push_url.split("://", 1)[-1].split("/", 1)[0]:
        raise BuildStop("missing_fork", "The push URL must not contain credentials.")
    return push_target, push_url


async def prepare_checkout(inp: BuildInput, env: BuildEnv, runner: Runner | None = None) -> CheckoutInfo:
    runner = runner or Runner()
    _, push_url = preflight(inp, env)
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    helper = write_credential_helper(paths)
    token = env.github_token
    clone_url = inp.repo_url or env.git_url(inp.repository)
    if (paths.repo / ".git").is_dir():
        code, out = await runner.git(paths.repo, "fetch", "--prune", "origin", token=token, helper=helper)
    else:
        paths.repo.parent.mkdir(parents=True, exist_ok=True)
        code, out = await runner.git(None, "clone", "--quiet", clone_url, str(paths.repo), token=token,
                                     helper=helper, timeout=1800)
    if code != 0:
        raise RuntimeError(f"could not clone or fetch the repository: {out.strip()[-400:]}")
    target = inp.target_branch
    code, head = await runner.git(paths.repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{target}")
    if code != 0:
        raise BuildStop("missing_branch", f"The target branch {target} no longer exists.")
    head = head.strip()
    base = head
    if inp.base_sha:
        code, _ = await runner.git(paths.repo, "cat-file", "-e", f"{inp.base_sha}^{{commit}}")
        if code == 0:
            base = inp.base_sha
    await runner.git(paths.repo, "remote", "remove", PUSH_REMOTE)
    code, out = await runner.git(paths.repo, "remote", "add", PUSH_REMOTE, push_url)
    if code != 0:
        raise RuntimeError(f"could not add the push remote: {out.strip()[-200:]}")
    branch = inp.build_branch
    continued = False
    code, _ = await runner.git(paths.repo, "fetch", "--quiet", PUSH_REMOTE, f"refs/heads/{branch}",
                               token=token, helper=helper)
    if code == 0:
        code, out = await runner.git(paths.repo, "checkout", "--quiet", "-B", branch, "FETCH_HEAD")
        continued = code == 0
    if not continued:
        code, out = await runner.git(paths.repo, "checkout", "--quiet", "-B", branch, base)
        if code != 0:
            raise RuntimeError(f"could not create the build branch: {out.strip()[-300:]}")
    differing: list[str] = []
    working = inp.working_branch
    if working and working != target:
        code, out = await runner.git(paths.repo, "diff", "--name-only", f"refs/remotes/origin/{working}...{base}")
        if code == 0:
            differing = [line.strip() for line in out.splitlines() if line.strip()]
    if inp.test_command:
        command, source = inp.test_command, "ticket"
    else:
        try:
            command, source = tr.resolve_test_command(inp.ticket, inp.procedures, paths.repo)
        except tr.NoTestCommand:
            command, source = "", "repo_default"
    return CheckoutInfo(base_sha=base, branch=branch, root=str(paths.root), repo_dir=str(paths.repo),
                        differing_files=differing, continued=continued, test_command=command,
                        test_command_source=source)


# ---------------------------------------------------------------------------
# Step 2: context folder and TASK.md
# ---------------------------------------------------------------------------

WORK_PROTOCOL = """## Work protocol (follow every step, in order)
1. Read /context/code.md completely. It already contains the exact source of the code you must change (from the team's graph, every line as it is at the base commit), its callers and callees, the tests that cover it, the outlines of the files involved, the decisions you must preserve and how changes are tested here.
2. Read /context/notes.md (and /context/previous-build.md and /context/failures.md if they exist). Continue from them; do not redo work already recorded.
3. Write a short plan at the top of /context/notes.md: which functions you will change, which tests you will add or update, and which constraint each change must preserve.
4. If you need code that is not in code.md, ask the graph through the MCP tools. Do not list directories, grep the repository or open files to look around.
   - Exact code of a function, class or file: get_code
   - A range of lines: get_code_range
   - What a file contains: file_outline
   - Where something is defined: find_symbol
   - Who calls it, with the call lines: references, callers
   - What a change could break: impact
   - Which tests cover it: tests_for
   - Which decisions constrain it: decisions_for
   - Text search over the code: search_code
   The graph shows the code before your edits. After you edit a file, re-read only that file from disk to see your change.
5. Make the smallest change that meets every acceptance criterion. Open a file directly only to edit it.
6. Add or update tests for the new behaviour. Never delete a test, never remove or loosen an assertion, never add skip, xfail or only markers.
7. Run the test command from "How changes are validated here". If tests fail, fix your change, not the tests.
   Your container has no project dependencies installed. If the command fails before any test runs (a missing module, a missing tool, a build error), that is not your change and not yours to fix: do not install, download or build anything. Run it once, note the error in /context/notes.md and move on. Actron runs the real tests, with dependencies, after you finish and will send you any real failures.
8. If the work needs anything outside the acceptance criteria or the files listed in "Where to work", stop: write the reason in /context/STOP.md and finish without making that change.
9. Update /context/notes.md: what you changed and why, the tests you ran and their result, what remains.
10. Finish by writing /context/REPORT.json exactly in this shape:
    {"filesChanged": ["path", ...], "testsAdded": ["test id", ...], "testCommand": "...", "testsPassed": true|false,
     "constraintsPreserved": [{"constraint": "...", "how": "..."}], "stopped": false, "notes": "one paragraph"}
## Rules (non-negotiable)
- Do not delete or weaken existing tests.
- Stay within the acceptance criteria and the listed files.
- Read code through the graph tools, not by exploring the file tree.
- Use callers, impact and tests_for before changing any function that other code calls.
- Run the tests before finishing. Always write REPORT.json.
- Never install packages or toolchains, never download files, never change build or dependency files (package.json, lock files, deps.edn, shadow-cljs.edn). Use only what is in the container.
- Stop after two runs of the test command that fail the same way, and finish with the report.
- Write the plan in /context/notes.md as your very first action after reading, before any other tool call.
"""


def _evidence_for(evidence: dict[str, Any], evidence_ids: list[str]) -> list[tuple[str, str]]:
    out = []
    pool = [*(evidence.get("decisions") or []), *(evidence.get("evidence") or [])]
    for eid in evidence_ids:
        for item in pool:
            if eid in (item.get("id"), item.get("evidenceId"), item.get("nodeId")):
                src = item.get("source") or {}
                where = src.get("url") or src.get("type") or src.get("id") or ""
                out.append((str(item.get("quote") or item.get("statement") or ""), str(where)))
                break
    return out


def render_task_md(
    ticket: dict[str, Any],
    evidence: dict[str, Any],
    procedures: list[dict[str, Any]],
    *,
    where_to_work: list[str],
    test_command: str,
    reminders: list[str] | None = None,
) -> str:
    lines: list[str] = []
    if reminders:
        lines += ["## Reminder from the last attempt (read this first)", *[f"- {r}" for r in reminders], ""]
    lines += ["# Task", str(ticket.get("objective") or "").strip(), "## Acceptance criteria"]
    lines += [f"- {c}" for c in ticket.get("acceptanceCriteria") or []] or ["- (none given)"]
    lines.append("## Constraints you must preserve (each with its evidence)")
    constraints = ticket.get("constraintsToPreserve") or []
    if not constraints:
        lines.append("- None recorded.")
    for c in constraints:
        text = c.get("text") if isinstance(c, dict) else str(c)
        found = _evidence_for(evidence, list(c.get("evidenceIds") or [])) if isinstance(c, dict) else []
        if found:
            for quote, source in found:
                lines.append(f"- {text} — evidence: {quote} ({source})")
        else:
            lines.append(f"- {text} — evidence: none recorded")
    lines.append("## Where to work")
    lines += where_to_work or ["- (no affected functions listed)"]
    lines.append("## How changes are validated here")
    lines.append(f"Test command: `{test_command}`" if test_command else "Test command: (none found)")
    co_changed = sorted({str(p) for proc in procedures for p in proc.get("coChangedPaths") or []})
    if co_changed:
        lines.append("Files that usually change together: " + ", ".join(f"`{p}`" for p in co_changed))
    return "\n".join(lines) + "\n" + WORK_PROTOCOL


async def _load_previous_build(env: BuildEnv, previous: dict[str, Any]) -> dict[str, Any]:
    """Fill notes, diff summary and the last test results from the earlier build's folder when only its id
    is given (RequestWorkflow passes `{buildId, feedback}`)."""
    build_id = str(previous.get("buildId") or "")
    if not build_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", build_id):
        return previous
    old = BuildPaths.for_build(env.host_dir, build_id)
    if not old.root.is_dir():
        return previous
    out = dict(previous)
    notes = old.context / "notes.md"
    if not out.get("notes") and notes.is_file():
        out["notes"] = notes.read_text(errors="replace")[:20000]
    meta_path = old.root / "pack-meta.json"
    if not out.get("diffSummary") and meta_path.is_file() and (old.repo / ".git").is_dir():
        base = str(json.loads(meta_path.read_text()).get("snapshot") or "")
        if base:
            code, stat = await Runner().git(old.repo, "diff", "--stat", base)
            if code == 0:
                out["diffSummary"] = stat.strip()[-4000:]
    junit = old.reports / "junit.xml"
    if not out.get("testResults") and junit.is_file():
        with contextlib.suppress(Exception):
            res = tr.parse_junit_xml(junit.read_text())
            out["testResults"] = {"passed": res.passed, "failed": res.failed,
                                  "failing": [f.name for f in res.failing]}
    return out


def render_previous_build(previous: dict[str, Any]) -> str:
    parts = ["# Previous build of this request"]
    if previous.get("feedback"):
        parts += ["## Reviewer feedback", str(previous["feedback"])]
    if previous.get("diffSummary"):
        parts += ["## What it changed", "```", str(previous["diffSummary"]), "```"]
    if previous.get("testResults"):
        parts += ["## Test results", "```json", json.dumps(previous["testResults"], indent=2), "```"]
    if previous.get("notes"):
        parts += ["## Its notes", str(previous["notes"])]
    return "\n".join(parts) + "\n"


async def write_build_context(
    inp: BuildInput,
    checkout: CheckoutInfo,
    env: BuildEnv,
    *,
    tools: ToolCaller | None = None,
) -> ContextInfo:
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    ctx = paths.context
    ctx.mkdir(parents=True, exist_ok=True)
    paths.session.mkdir(parents=True, exist_ok=True)
    pack: ContextPack = await build_context_pack(
        inp.ticket, inp.evidence, inp.procedures, tools=tools or empty_tools,
        test_command=checkout.test_command, differing_files=checkout.differing_files,
        target_branch=inp.target_branch, repo_dir=Path(checkout.repo_dir), snapshot=checkout.base_sha,
        limit=env.pack_limit,
    )
    (ctx / "ticket.json").write_text(json.dumps(inp.ticket, indent=2, ensure_ascii=False))
    (ctx / "evidence.json").write_text(json.dumps(inp.evidence, indent=2, ensure_ascii=False))
    (ctx / "procedures.json").write_text(json.dumps(inp.procedures, indent=2, ensure_ascii=False))
    (ctx / "code.md").write_text(pack.markdown)
    where = pack.where_to_work()
    (ctx / "TASK.md").write_text(render_task_md(inp.ticket, inp.evidence, inp.procedures, where_to_work=where,
                                                test_command=checkout.test_command))
    meta = {"whereToWork": [s.path for s in pack.symbols], "functions": pack.meta,
            "testCommand": checkout.test_command, "snapshot": checkout.base_sha,
            "differingFiles": checkout.differing_files}
    (paths.root / "pack-meta.json").write_text(json.dumps(meta, indent=2))
    notes = ctx / "notes.md"
    if not notes.exists():
        notes.write_text("")
    for name in ("REPORT.json", "STOP.md"):
        (ctx / name).write_text("")
    if inp.previous_build:
        previous = await _load_previous_build(env, dict(inp.previous_build))
        (ctx / "previous-build.md").write_text(render_previous_build(previous))
    for f in (ctx / "failures.md",):
        if f.exists():
            f.unlink()
    return ContextInfo(pack_size=pack.size, pack_tier=pack.tier, where_to_work=where, meta=pack.meta)


def rewrite_task_with_reminders(inp: BuildInput, checkout: CheckoutInfo, env: BuildEnv,
                                reminders: list[str]) -> None:
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    meta = json.loads((paths.root / "pack-meta.json").read_text())
    where = [line for line in _where_lines(paths)] or [f"- `{p}`" for p in meta.get("whereToWork", [])]
    (paths.context / "TASK.md").write_text(render_task_md(
        inp.ticket, inp.evidence, inp.procedures, where_to_work=where,
        test_command=checkout.test_command, reminders=reminders))


def _where_lines(paths: BuildPaths) -> list[str]:
    text = (paths.context / "TASK.md").read_text() if (paths.context / "TASK.md").exists() else ""
    m = re.search(r"## Where to work\n(.*?)\n## How changes", text, re.S)
    return [line for line in m.group(1).splitlines() if line.strip()] if m else []


# ---------------------------------------------------------------------------
# Step 3: Pi
# ---------------------------------------------------------------------------


@dataclass
class DockerCommand:
    argv: list[str]
    env: dict[str, str]
    container: str


def pi_docker_command(inp: BuildInput, env: BuildEnv, *, attempt: int, run_token: str) -> DockerCommand:
    """The exact docker command for one Pi attempt. Secrets are passed by name; values only in `env`."""
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    model, key_name = env.model_choice()
    container = f"actron-pi-{inp.build_id}"
    ctx = paths.context
    prompt = FIRST_MESSAGE if attempt == 1 else (
        f"This is attempt {attempt}. Read /context/failures.md first, then continue with /context/TASK.md.")
    argv = [
        "docker", "run", "--rm", "--name", container, "--network", env.network,
        "--cpus", "2", "--memory", "4g", "--pids-limit", "512", "--read-only", "--tmpfs", "/tmp",
        "--user", tr.host_user(), "-w", "/work",
        "-v", f"{paths.repo}:/work",
        "-v", f"{ctx}:/context:ro",
        "-v", f"{ctx / 'notes.md'}:/context/notes.md",
        "-v", f"{ctx / 'REPORT.json'}:/context/REPORT.json",
        "-v", f"{ctx / 'STOP.md'}:/context/STOP.md",
        "-v", f"{paths.session}:/session",
        "-e", key_name,
        "-e", f"ACTRON_MCP_URL={env.mcp_url}",
        "-e", "ACTRON_RUN_TOKEN",
    ]
    for k, v in env.pi_extra_env.items():
        argv += ["-e", f"{k}={v}"]
    argv += [
        env.pi_image,
        "--mode", "json", "--no-approve",
        "--model", model,
        "--session-dir", "/session", "--session-id", f"actron-{inp.build_id}",
        "--append-system-prompt", "/context/TASK.md",
        prompt,
    ]
    proc_env = tr.docker_env()
    proc_env[key_name] = env.model_keys[key_name]
    proc_env["ACTRON_RUN_TOKEN"] = run_token
    return DockerCommand(argv=argv, env=proc_env, container=container)


@dataclass
class StepEvent:
    step: str
    text: str
    file: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


_EXPLORE_CMD = re.compile(r"^\s*(ls|find|grep|egrep|rg|ag|fd|tree|cat|head|tail|less|more|git\s+(ls-files|grep))\b")
_TEST_HINT = re.compile(r"\b(pytest|npm\s+(run\s+)?(test|unit-test)|npx\s+(mocha|jest|vitest)|mocha|jest|vitest|"
                        r"clojure\s+-M:test|lein\s+test|yarn\s+test|pnpm\s+test)\b")


def _norm(path: str) -> str:
    path = path.strip()
    if path.startswith("/work/"):
        return path[len("/work/"):]
    return path[2:] if path.startswith("./") else path


class PiWatcher:
    """Reads Pi's JSON events and enforces the work protocol (B9 'Making Pi follow the instructions')."""

    def __init__(self, *, attempt: int, where_to_work: list[str], functions: dict[str, dict[str, Any]],
                 test_command: str) -> None:
        self.attempt = attempt
        self.where = {_norm(p) for p in where_to_work}
        self.functions = functions
        self.test_command = test_command
        self.tool_events = 0
        self.exploration = 0
        self.outside_reads = 0
        self.reminders: list[str] = []
        self.graph_first_misses: list[str] = []
        self.consulted: set[str] = set()
        self.edited: list[str] = []
        self.commands: list[str] = []
        self.plan_written_at: int | None = None
        self.plan_reminded = False
        self.last_edit_at = -1
        self.last_test_at = -1
        self.stop_requested = False
        self.tokens = Tokens()
        self.errors: list[str] = []
        self.successful_turns = 0

    # Classification -----------------------------------------------------
    def _is_exploration(self, tool: str, args: dict[str, Any]) -> tuple[bool, bool]:
        """(exploration, outside read)."""
        if tool in ("ls", "find", "grep"):
            return True, False
        if tool == "read":
            path = _norm(str(args.get("path") or args.get("file_path") or ""))
            if path.startswith("/context/") or path in self.where or path in self.edited:
                return False, False
            return True, True
        if tool == "bash":
            cmd = str(args.get("command") or "")
            if _EXPLORE_CMD.match(cmd):
                words = cmd.split()
                if words[0] in ("cat", "head", "tail") and all(
                    _norm(w) in self.where or _norm(w) in self.edited or w.startswith("/context/")
                    for w in words[1:] if not w.startswith("-")
                ):
                    return False, False
                return True, words[0] in ("cat", "head", "tail", "less", "more")
        return False, False

    def _mcp_name(self, tool: str) -> str | None:
        if tool.startswith("mcp__"):
            return tool.split("__", 2)[-1]
        return None

    def _step_text(self, tool: str, args: dict[str, Any]) -> tuple[str, str | None]:
        path = args.get("path") or args.get("file_path")
        file = _norm(str(path)) if path else None
        mcp = self._mcp_name(tool)
        if mcp:
            target = args.get("id") or args.get("functionId") or args.get("path") or args.get("name") or \
                args.get("query") or ",".join(str(i) for i in args.get("ids") or [])
            return f"Asking the graph: {mcp}({str(target)[:80]})", None
        if tool == "read":
            return f"Reading {file}", file
        if tool == "edit":
            return f"Editing {file}", file
        if tool == "write":
            return f"Writing {file}", file
        if tool == "bash":
            return f"Running `{str(args.get('command') or '')[:100]}`", None
        if tool in ("ls", "find", "grep"):
            return f"Looking through {file or args.get('pattern') or 'the repository'}", file
        return f"Using {tool}", file

    # Feeding ------------------------------------------------------------
    def feed(self, event: dict[str, Any]) -> list[StepEvent]:
        etype = event.get("type")
        out: list[StepEvent] = []
        if etype == "tool_execution_start":
            out += self._on_tool(str(event.get("toolName") or ""), dict(event.get("args") or {}))
        elif etype == "tool_execution_end" and event.get("isError"):
            text = json.dumps(event.get("result"))[:200]
            out.append(StepEvent("pi.tool_error", f"A {event.get('toolName')} step failed",
                                 detail={"attempt": self.attempt, "error": text}))
        elif etype == "message_end":
            msg = event.get("message") or {}
            if msg.get("role") == "assistant":
                usage = msg.get("usage") or {}
                self.tokens.input += int(usage.get("input") or 0)
                self.tokens.output += int(usage.get("output") or 0)
                if msg.get("stopReason") == "error":
                    self.errors.append(str(msg.get("errorMessage") or "model error"))
                else:
                    self.successful_turns += 1
                    text = " ".join(c.get("text", "") for c in msg.get("content") or []
                                    if isinstance(c, dict) and c.get("type") == "text").strip()
                    if text:
                        out.append(StepEvent("pi.note", text[:240], detail={"attempt": self.attempt}))
        return out

    def _on_tool(self, tool: str, args: dict[str, Any]) -> list[StepEvent]:
        self.tool_events += 1
        idx = self.tool_events
        out: list[StepEvent] = []
        text, file = self._step_text(tool, args)
        explore, outside = self._is_exploration(tool, args)
        mcp = self._mcp_name(tool)
        if mcp in ("callers", "references", "impact"):
            blob = json.dumps(args)
            for fid, info in self.functions.items():
                if fid in blob or (info.get("path") and str(info["path"]) in blob):
                    self.consulted.add(fid)
        path = _norm(str(args.get("path") or args.get("file_path") or ""))
        if tool in ("edit", "write") and path:
            if path == "/context/notes.md":
                if self.plan_written_at is None:
                    self.plan_written_at = idx
            elif not path.startswith("/context/"):
                out += self._graph_first(path)
                if path not in self.edited:
                    self.edited.append(path)
                self.last_edit_at = idx
        if tool == "bash":
            cmd = str(args.get("command") or "")
            self.commands.append(cmd)
            if "/context/notes.md" in cmd and ">" in cmd and self.plan_written_at is None:
                self.plan_written_at = idx
            if (self.test_command and self.test_command.split()[0] in cmd and
                    any(w in cmd for w in self.test_command.split()[:2])) or _TEST_HINT.search(cmd):
                self.last_test_at = idx
        detail: dict[str, Any] = {"attempt": self.attempt, "tool": tool, "toolEvents": idx}
        if explore:
            self.exploration += 1
            if outside:
                self.outside_reads += 1
            detail["exploration"] = self.exploration
        out.insert(0, StepEvent("pi.tool", text, file, detail))
        if explore and self.exploration == EXPLORATION_REMINDER_AT:
            self.reminders.append(EXPLORATION_REMINDER)
            out.append(StepEvent("guard.exploration_reminder", "Reminder recorded: " + EXPLORATION_REMINDER,
                                 detail={"attempt": self.attempt, "exploration": self.exploration}))
        if explore and self.exploration >= EXPLORATION_STOP_AT and not self.stop_requested:
            self.stop_requested = True
            out.append(StepEvent("guard.exploration_stop",
                                 f"Pi explored the repository {self.exploration} times; stopping this attempt.",
                                 detail={"attempt": self.attempt, "exploration": self.exploration}))
        if idx == PLAN_WITHIN_TOOL_EVENTS and self.plan_written_at is None and not self.plan_reminded:
            self.plan_reminded = True
            self.reminders.append(PLAN_REMINDER)
            out.append(StepEvent("guard.plan_reminder", "Reminder recorded: " + PLAN_REMINDER,
                                 detail={"attempt": self.attempt}))
        return out

    def _graph_first(self, path: str) -> list[StepEvent]:
        out = []
        for fid, info in self.functions.items():
            if info.get("path") != path or not info.get("hasCallers") or info.get("callersInPack"):
                continue
            if fid in self.consulted or fid in self.graph_first_misses:
                continue
            self.graph_first_misses.append(fid)
            if GRAPH_FIRST_REMINDER not in self.reminders:
                self.reminders.append(GRAPH_FIRST_REMINDER)
            out.append(StepEvent("guard.graph_first", "Reminder recorded: " + GRAPH_FIRST_REMINDER, path,
                                 {"attempt": self.attempt, "functionId": fid,
                                  "misses": len(self.graph_first_misses)}))
        return out

    @property
    def plan_ok(self) -> bool:
        return self.plan_written_at is not None and self.plan_written_at <= PLAN_WITHIN_TOOL_EVENTS

    @property
    def tests_after_last_edit(self) -> bool:
        return self.last_test_at > self.last_edit_at and self.last_test_at > 0


def validate_report(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.strip():
        return None, "REPORT.json is missing."
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"REPORT.json is not valid JSON: {exc}"
    try:
        PiReport.model_validate(data)
    except ValidationError as exc:
        return data if isinstance(data, dict) else None, (
            "REPORT.json does not match the required shape: " +
            "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]))
    return data, ""


async def issue_run_token(ws: str, request_id: str, ttl_seconds: int, *, snapshot_sha: str | None = None,
                          differing_paths: list[str] | None = None) -> str:
    """A per-run token for Pi's MCP calls (W5's `register_run_token`, stored in Redis with a TTL)."""
    try:
        from actron.mcp_graph.server import register_run_token
    except ImportError:
        log.warning("register_run_token is not available; the MCP server will refuse Pi's calls")
        return f"run_{secrets.token_urlsafe(24)}"
    return await register_run_token(ws, ttl_seconds, request_id=request_id, snapshot_sha=snapshot_sha,
                                    differing_paths=differing_paths or [], by="pi")


async def _docker_kill(container: str) -> None:
    """Kill and remove; waits until the daemon no longer lists it (`--rm` removal is asynchronous)."""
    await tr.run_cmd(["docker", "kill", container], timeout=30)
    for _ in range(40):
        await tr.remove_container(container)
        if not await tr.container_exists(container):
            return
        await asyncio.sleep(0.25)
    log.warning("container still listed after removal", extra={"container": container})


async def run_pi(
    inp: BuildInput,
    env: BuildEnv,
    *,
    attempt: int,
    emit: EventSink,
    heartbeat: Callable[[dict[str, Any]], None] | None = None,
    run_token: str | None = None,
    timeout_seconds: float | None = None,
    runner: Runner | None = None,
) -> PiAttempt:
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    meta = json.loads((paths.root / "pack-meta.json").read_text())
    for name in ("REPORT.json", "STOP.md"):
        (paths.context / name).write_text("")
    token = run_token or await issue_run_token(
        inp.ws, inp.request_id, inp.timeout_seconds + 600, snapshot_sha=meta.get("snapshot"),
        differing_paths=list(meta.get("differingFiles") or []))
    cmd = pi_docker_command(inp, env, attempt=attempt, run_token=token)
    if runner is not None:
        runner.records.append(CommandRecord(cmd.argv, cmd.env))
    await _ensure_network(env.network)
    await tr.remove_container(cmd.container)
    watcher = PiWatcher(attempt=attempt, where_to_work=list(meta.get("whereToWork") or []),
                        functions=dict(meta.get("functions") or {}), test_command=str(meta.get("testCommand") or ""))
    result = PiAttempt(attempt=attempt, session_id=f"actron-{inp.build_id}")
    log_path = paths.pi_log(attempt)
    proc = await asyncio.create_subprocess_exec(
        *cmd.argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=cmd.env,
        limit=32 * 1024 * 1024,
    )
    assert proc.stdout is not None and proc.stderr is not None
    stderr_chunks: list[bytes] = []

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while chunk := await proc.stderr.read(65536):
            stderr_chunks.append(chunk)

    async def beat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if heartbeat:
                heartbeat({"attempt": attempt, "toolEvents": watcher.tool_events})

    async def pump() -> None:
        assert proc.stdout is not None
        with log_path.open("ab") as fh:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                fh.write(line)
                text = line.decode("utf-8", "replace").rstrip("\r\n")
                if not text.startswith("{"):
                    continue
                try:
                    event = json.loads(text)
                except ValueError:
                    continue
                for step in watcher.feed(event):
                    payload: dict[str, Any] = {"buildId": inp.build_id, "step": step.step, "text": step.text,
                                               "detail": step.detail}
                    if step.file:
                        payload["file"] = step.file
                    await emit("build.step", payload)
                if heartbeat:
                    heartbeat({"attempt": attempt, "toolEvents": watcher.tool_events})
                if watcher.stop_requested:
                    await _docker_kill(cmd.container)
                    break
        await proc.wait()

    stderr_task = asyncio.create_task(drain_stderr())
    beat_task = asyncio.create_task(beat())
    limit = timeout_seconds if timeout_seconds is not None else float(inp.timeout_seconds)
    try:
        await asyncio.wait_for(pump(), timeout=limit)
    except TimeoutError:
        result.timed_out = True
    finally:
        beat_task.cancel()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        # Shielded so a cancelled activity still removes its container.
        await asyncio.shield(_docker_kill(cmd.container))
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=30)
        stderr_task.cancel()
    (paths.root / f"pi-attempt-{attempt}.stderr").write_bytes(b"".join(stderr_chunks)[-200_000:])
    result.exit_code = proc.returncode
    result.stopped_for_exploration = watcher.stop_requested
    result.tokens = watcher.tokens
    result.tool_events = watcher.tool_events
    result.exploration_count = watcher.exploration
    result.outside_reads = watcher.outside_reads
    result.reminders = watcher.reminders
    result.graph_first_misses = watcher.graph_first_misses
    result.plan_ok = watcher.plan_ok
    result.tests_after_last_edit = watcher.tests_after_last_edit
    result.edited_files = watcher.edited
    result.commands = watcher.commands[-20:]
    if watcher.errors and watcher.successful_turns == 0 and watcher.tool_events == 0:
        result.model_error = watcher.errors[-1][:500]
    report_text = (paths.context / "REPORT.json").read_text(errors="replace")
    result.report, result.report_errors = validate_report(report_text)
    result.report_ok = not result.report_errors
    result.stop_text = (paths.context / "STOP.md").read_text(errors="replace").strip()[:4000]
    await emit("build.step", {
        "buildId": inp.build_id, "step": "pi.attempt_done",
        "text": f"Pi finished attempt {attempt}" + (" (timed out)" if result.timed_out else ""),
        "detail": {"attempt": attempt, "toolEvents": result.tool_events, "exploration": result.exploration_count,
                   "outsideReads": result.outside_reads, "reminders": result.reminders,
                   "graphFirstMisses": len(result.graph_first_misses), "planOk": result.plan_ok,
                   "reportOk": result.report_ok, "testsAfterLastEdit": result.tests_after_last_edit,
                   "tokens": result.tokens.wire()},
    })
    return result


async def _ensure_network(name: str) -> None:
    code, _ = await tr.run_cmd(["docker", "network", "inspect", name], timeout=30)
    if code != 0:
        await tr.run_cmd(["docker", "network", "create", name], timeout=30)


# ---------------------------------------------------------------------------
# Step 6 helper: failures.md
# ---------------------------------------------------------------------------

MISSING_TEXT = {
    "plan": "There was no plan at the top of /context/notes.md within the first 5 steps. Write it first.",
    "report": "/context/REPORT.json was missing or did not match the required shape.",
    "tests_after_last_edit": "The test command was not run after the last edit. Run it before finishing.",
    "no_changes": "No files were changed.",
}


def render_failures(attempt: PiAttempt, tests: tr.TestResult | None, extra: list[str] | None = None) -> str:
    lines = [f"# What went wrong in attempt {attempt.attempt}"]
    missing = attempt.missing_items()
    if missing or extra:
        lines.append("## Missing from the work protocol (fix these first)")
        for item in missing:
            line = MISSING_TEXT[item]
            if item == "report" and attempt.report_errors:
                line += f" ({attempt.report_errors})"
            lines.append(f"- {line}")
        lines += [f"- {e}" for e in extra or []]
    if tests is not None and not tests.ok:
        lines += ["## Failing tests", f"Command: `{tests.command}`"]
        for f in tests.failing[:10]:
            lines += [f"### {f.name}", "```", f.output[:3000], "```"]
        if not tests.failing:
            lines += ["```", tests.output_tail[-3000:], "```"]
    if attempt.reminders:
        lines.append("## Reminders")
        lines += [f"- {r}" for r in dict.fromkeys(attempt.reminders)]
    lines += ["## Summary of the previous attempt",
              f"- Files changed: {', '.join(attempt.edited_files) or 'none'}",
              f"- Commands run: {'; '.join(c[:120] for c in attempt.commands[-8:]) or 'none'}"]
    return "\n".join(lines) + "\n"


def write_failures(inp: BuildInput, env: BuildEnv, text: str) -> None:
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    (paths.context / "failures.md").write_text(text)


# ---------------------------------------------------------------------------
# Steps 4 and 5 wrappers
# ---------------------------------------------------------------------------


async def check_build_diff(inp: BuildInput, checkout: CheckoutInfo, *,
                           scope_judge: dc.ScopeJudge | None = None) -> dc.DiffCheck:
    return await dc.check_diff(Path(checkout.repo_dir), checkout.base_sha, inp.ticket, inp.evidence,
                               inp.procedures, scope_judge=scope_judge)


async def run_build_tests(inp: BuildInput, checkout: CheckoutInfo, env: BuildEnv) -> tr.TestResult:
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    if not checkout.test_command:
        return tr.TestResult(failed=1, exit_code=1, command="", source="repo_default",
                             failing=[tr.FailingTest(name="test command", output="No test command was found.")])
    cfg = tr.TestRunConfig(image=env.test_image, cache_root=env.host_dir / "_deps-cache",
                           timeout_seconds=env.test_timeout_seconds)
    source: tr.TestSource = checkout.test_command_source  # type: ignore[assignment]
    return await tr.run_tests(paths.repo, paths.reports, inp.build_id, checkout.test_command, source, cfg)


# ---------------------------------------------------------------------------
# Step 7: commit and push
# ---------------------------------------------------------------------------


def commit_message(inp: BuildInput) -> str:
    objective = str(inp.ticket.get("objective") or "Actron change").strip().splitlines()[0][:72]
    return (f"{objective}\n\nActron request {inp.request_id}, ticket revision {inp.revision} "
            f"({inp.revision_hash[:8]})")


async def commit_and_push(inp: BuildInput, checkout: CheckoutInfo, env: BuildEnv,
                          runner: Runner | None = None) -> str:
    runner = runner or Runner()
    if not (env.bot_name or "").strip() or not (env.bot_email or "").strip():
        raise BuildStop("missing_identity", "ACTRON_BOT_NAME and ACTRON_BOT_EMAIL must be set to commit.")
    paths = BuildPaths.for_build(env.host_dir, inp.build_id)
    repo = Path(checkout.repo_dir)
    await runner.git(repo, "add", "-A")
    code, out = await runner.git(repo, "-c", f"user.name={env.bot_name}", "-c", f"user.email={env.bot_email}",
                                 "commit", "--quiet", "--no-verify", "-m", commit_message(inp))
    if code != 0 and "nothing to commit" not in out:
        raise RuntimeError(f"commit failed: {out.strip()[-300:]}")
    helper = write_credential_helper(paths)
    code, out = await runner.git(repo, "push", "--quiet", PUSH_REMOTE, f"+HEAD:refs/heads/{checkout.branch}",
                                 token=env.github_token, helper=helper, timeout=600)
    if code != 0:
        raise RuntimeError(f"push failed: {_scrub(out, env.github_token)[-400:]}")
    code, head = await runner.git(repo, "rev-parse", "HEAD")
    return head.strip()


def _scrub(text: str, secret: str | None) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


# ---------------------------------------------------------------------------
# Step 8: pull request
# ---------------------------------------------------------------------------


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


def render_pr_body(inp: BuildInput, result: BuildResult, report: dict[str, Any] | None) -> str:
    ticket = inp.ticket
    ident = inp.ticket_identifier or "not in Linear"
    lines = ["## What and why",
             f"{ticket.get('objective', '')} (Actron request {inp.request_id}, ticket {ident} v{inp.revision})",
             "## Evidence from the team's history"]
    quotes = [d for d in inp.evidence.get("decisions") or [] if d.get("quote")]
    if quotes:
        for d in quotes[:10]:
            src = d.get("source") or {}
            lines.append(f"- {d['quote']} — {src.get('url') or src.get('type') or src.get('id') or ''}")
    else:
        lines.append("- No earlier decisions were found for this change.")
    lines.append("## Constraints preserved")
    proofs = {str(c.get("constraint")): str(c.get("how")) for c in (report or {}).get("constraintsPreserved") or []}
    constraints = ticket.get("constraintsToPreserve") or []
    if not constraints:
        lines.append("- None recorded.")
    for c in constraints:
        text = c.get("text") if isinstance(c, dict) else str(c)
        how = proofs.get(str(text)) or next((v for k, v in proofs.items() if k and k in str(text)), None)
        lines.append(f"- [x] {text} — proved by {how or 'the test run below'}")
    total = result.tests_passed + result.tests_failed
    lines += ["## Tests",
              f"{result.tests_passed}/{total} passed on {(result.head_sha or '')[:7]}. Command: `{result.test_command}`",
              "## Graph impact"]
    impact = inp.evidence.get("impact") or {}
    callers = len(impact.get("callers") or [])
    affected = set(ticket.get("affectedFunctions") or [])
    crit = [f"{str(c.get('id')).split('::')[-1]} {c.get('percentile')}th percentile"
            for c in impact.get("criticality") or [] if c.get("id") in affected]
    lines.append(f"{callers} callers checked; criticality of changed functions: {', '.join(crit) or 'not recorded'}")
    lines.append("## Build report")
    if report:
        lines.append(f"Files changed: {', '.join(report.get('filesChanged') or []) or 'none'}")
        lines.append(f"Tests added: {', '.join(report.get('testsAdded') or []) or 'none'}")
        if report.get("notes"):
            lines.append(f"Notes: {report['notes']}")
        lines += ["<details><summary>REPORT.json</summary>", "", "```json",
                  json.dumps(report, indent=2, ensure_ascii=False), "```", "</details>"]
    else:
        lines.append("Pi did not write a report.")
    return "\n".join(lines) + "\n"


async def _gh(client: httpx.AsyncClient, method: str, url: str, **kw: Any) -> httpx.Response:
    delay = 0.5
    for attempt in range(4):
        try:
            resp = await client.request(method, url, **kw)
        except httpx.TransportError as exc:
            if attempt == 3:
                raise GitHubError(0, str(exc)) from exc
        else:
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            if attempt == 3:
                return resp
        await asyncio.sleep(delay)
        delay *= 2
    raise GitHubError(0, "unreachable")


async def open_or_update_pr(
    inp: BuildInput,
    result: BuildResult,
    env: BuildEnv,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PrInfo:
    fork = (inp.push_target or env.github_fork or "").strip()
    if not fork:
        raise BuildStop("missing_fork")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "actron"}
    if env.github_token:
        headers["Authorization"] = f"Bearer {env.github_token}"
    title = str(inp.ticket.get("objective") or "Actron change").splitlines()[0][:200]
    body = render_pr_body(inp, result, result.report)
    base_url = env.github_api_url.rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0, transport=transport) as client:
        number = inp.existing_pr_number
        if number is None:
            owner = fork.split("/")[0]
            resp = await _gh(client, "GET", f"/repos/{fork}/pulls",
                             params={"head": f"{owner}:{result.branch}", "state": "open"})
            if resp.status_code == 200 and resp.json():
                number = int(resp.json()[0]["number"])
        if number is not None:
            resp = await _gh(client, "PATCH", f"/repos/{fork}/pulls/{number}", json={"title": title, "body": body})
            action: Literal["opened", "updated"] = "updated"
        else:
            resp = await _gh(client, "POST", f"/repos/{fork}/pulls", json={
                "title": title, "head": result.branch, "base": inp.target_branch, "body": body,
                "maintainer_can_modify": False})
            action = "opened"
        if resp.status_code >= 300:
            raise GitHubError(resp.status_code, resp.text[:300])
        data = resp.json()
    return PrInfo(number=int(data["number"]), url=str(data.get("html_url") or data.get("url") or ""),
                  head_sha=str((data.get("head") or {}).get("sha") or result.head_sha or ""), action=action)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class BuildSteps(Protocol):
    async def prepare_checkout(self, inp: BuildInput) -> CheckoutInfo: ...
    async def write_context(self, inp: BuildInput, checkout: CheckoutInfo) -> ContextInfo: ...
    async def run_pi(self, inp: BuildInput, attempt: int) -> PiAttempt: ...
    async def check_diff(self, inp: BuildInput, checkout: CheckoutInfo) -> dc.DiffCheck: ...
    async def run_tests(self, inp: BuildInput, checkout: CheckoutInfo) -> tr.TestResult: ...
    async def write_failures(self, inp: BuildInput, checkout: CheckoutInfo, text: str,
                             reminders: list[str]) -> None: ...
    async def commit_and_push(self, inp: BuildInput, checkout: CheckoutInfo) -> str: ...
    async def open_pr(self, inp: BuildInput, result: BuildResult) -> PrInfo: ...
    async def read_notes(self, inp: BuildInput) -> str: ...
    async def emit(self, type: str, payload: dict[str, Any]) -> None: ...
    def now_ms(self) -> int: ...


def _same_constraint(a: str, b: str) -> bool:
    a, b = a.strip().lower().rstrip("."), b.strip().lower().rstrip(".")
    return bool(a and b) and (a == b or a in b or b in a)


def build_ui_report(inp: BuildInput, result: BuildResult, pi_report: dict[str, Any] | None,
                    tests: tr.TestResult | None, line_counts: dict[str, list[int]]) -> dict[str, Any]:
    """`Build.report` as the request view reads it (frontend/lib/build-report.ts): tests, constraints,
    filesChanged and procedures, plus Pi's own REPORT.json under `pi` and its testsAdded and notes."""
    pi = pi_report or {}
    failing = {f.name: f.output for f in (tests.failing if tests else [])}
    test_rows: list[dict[str, Any]] = [{"name": n, "status": "fail", "output": o[-2000:]} for n, o in failing.items()]
    added = [str(t) for t in pi.get("testsAdded") or []]
    if tests is not None:
        test_rows += [{"name": t, "status": "pass"} for t in added if t not in failing]
    proofs = [(str(c.get("constraint") or ""), str(c.get("how") or ""))
              for c in pi.get("constraintsPreserved") or [] if isinstance(c, dict)]
    texts = [str(c.get("text") if isinstance(c, dict) else c) for c in inp.ticket.get("constraintsToPreserve") or []]
    texts += [c for c, _ in proofs if c and not any(_same_constraint(c, t) for t in texts)]
    passed = result.status == "passed" and (tests is None or tests.ok)
    constraints: list[dict[str, Any]] = []
    for text in texts:
        how = next((h for c, h in proofs if _same_constraint(c, text) and h), None)
        proof = ({"kind": "test" if re.search(r"\btest", how, re.I) else "evidence", "label": how} if how else None)
        broken = bool(how) and any(name in (how or "") for name in failing)
        status = "broken" if broken else "holds" if passed and how else "unverified"
        constraints.append({"text": text, "status": status, "proof": proof})
    files = [{"path": p, "additions": (line_counts.get(p) or [0, 0])[0], "deletions": (line_counts.get(p) or [0, 0])[1]}
             for p in (result.files_changed or [str(f) for f in pi.get("filesChanged") or []])]
    procedures = [{"title": str(p.get("title") or p.get("name") or p.get("id") or "Procedure"),
                   "testCommand": str(p.get("testCommand") or "")} for p in inp.procedures if isinstance(p, dict)]
    return {"tests": test_rows, "constraints": constraints, "filesChanged": files, "procedures": procedures,
            "testsAdded": added, "notes": str(pi.get("notes") or ""), "pi": pi_report}


async def run_build(inp: BuildInput, steps: BuildSteps) -> BuildResult:
    """The B9 loop. Deterministic given the step results, so it also runs inside a Temporal workflow."""
    started = steps.now_ms()
    result = BuildResult(status="failed", build_id=inp.build_id, branch=inp.build_branch)
    guards: dict[str, Any] = {"reminders": [], "exploration": [], "graphFirstMisses": 0, "attempts": []}
    result.guards = guards
    # What the request view's report needs from the last attempt (see build_ui_report).
    last: dict[str, Any] = {"tests": None, "lines": {}}

    async def finish(status: BuildStatus, reason: str | None = None, message: str = "") -> BuildResult:
        result.status = status
        result.stop_reason = reason
        result.duration_ms = steps.now_ms() - started
        result.report = build_ui_report(inp, result, result.report, last["tests"], last["lines"])
        with contextlib.suppress(Exception):
            result.notes = await steps.read_notes(inp)
        if status == "passed":
            return result
        await steps.emit("build.failed", {"buildId": inp.build_id, "reason": reason or "failed",
                                          **({"message": message} if message else {})})
        return result

    try:
        checkout = await steps.prepare_checkout(inp)
    except BuildStop as stop:
        return await finish("stopped", stop.reason, stop.message)
    result.base_sha, result.branch = checkout.base_sha, checkout.branch
    result.test_command, result.test_command_source = checkout.test_command, checkout.test_command_source
    await steps.emit("build.started", {"buildId": inp.build_id, "branch": checkout.branch,
                                       "baseSha": checkout.base_sha})
    ctx = await steps.write_context(inp, checkout)
    await steps.emit("build.step", {"buildId": inp.build_id, "step": "context",
                                    "text": f"Context pack written ({ctx.pack_size:,} characters, {ctx.pack_tier})",
                                    "file": "/context/code.md",
                                    "detail": {"testCommand": checkout.test_command,
                                               "testCommandSource": checkout.test_command_source,
                                               "whereToWork": ctx.where_to_work}})
    attempt = 0
    repairs = 0
    exploration_retry_used = False
    tests: tr.TestResult | None = None
    while True:
        attempt += 1
        result.attempts = attempt
        pi = await steps.run_pi(inp, attempt)
        result.tokens.input += pi.tokens.input
        result.tokens.output += pi.tokens.output
        guards["reminders"] += pi.reminders
        guards["exploration"].append(pi.exploration_count)
        guards["graphFirstMisses"] += len(pi.graph_first_misses)
        guards["attempts"].append({"attempt": attempt, "planOk": pi.plan_ok, "reportOk": pi.report_ok,
                                   "testsAfterLastEdit": pi.tests_after_last_edit,
                                   "exploration": pi.exploration_count, "outsideReads": pi.outside_reads})
        if pi.report is not None:
            result.report = pi.report
        if pi.timed_out:
            return await finish("failed", "timeout", "Pi did not finish within the time limit.")
        if pi.model_error:
            return await finish("failed", "model_error", pi.model_error)
        if inp.max_tokens and result.tokens.input + result.tokens.output > inp.max_tokens:
            return await finish("stopped", "token_budget", "The build used more tokens than its budget.")
        if pi.stopped_for_exploration:
            if not exploration_retry_used:
                exploration_retry_used = True
                await steps.write_failures(inp, checkout, render_failures(pi, None, [EXPLORATION_REMINDER]),
                                           [EXPLORATION_REMINDER])
                await steps.emit("build.step", {"buildId": inp.build_id, "step": "guard.exploration_retry",
                                                "text": "Retrying with the graph reminder at the top of TASK.md",
                                                "detail": {"attempt": attempt}})
                continue
            return await finish("failed", "exploration", "Pi kept exploring the repository after the reminder.")
        if pi.stop_text or (pi.report or {}).get("stopped") is True:
            await steps.emit("build.step", {"buildId": inp.build_id, "step": "guard.stop_md",
                                            "text": "Pi stopped: the work needs a change outside the ticket",
                                            "detail": {"stop": pi.stop_text[:1000]}})
            return await finish("stopped", "scope_change", pi.stop_text[:500])
        diff = await steps.check_diff(inp, checkout)
        result.files_changed = diff.files_changed
        result.diff_summary = diff.diff_summary
        last["lines"] = diff.line_counts
        guards["diff"] = diff.wire()
        await steps.emit("build.step", {
            "buildId": inp.build_id, "step": "guard.diff",
            "text": {"ok": f"Diff check passed ({len(diff.files_changed)} files)",
                     "tests_weakened": "Diff check failed: existing tests were weakened",
                     "scope_change": "Diff check stopped the build: changes outside the ticket"}[diff.status],
            "detail": {"weakened": [w.wire() for w in diff.weakened], "outsideFiles": diff.outside_files,
                       "scopeProbability": diff.scope_probability, "provider": "stub" if diff.scope_stub else "jev"},
        })
        if diff.status == "tests_weakened":
            return await finish("stopped", "tests_weakened", "; ".join(w.detail for w in diff.weakened)[:500])
        if diff.status == "scope_change":
            return await finish("stopped", "scope_change", ", ".join(diff.outside_files)[:500])
        extra: list[str] = []
        if not diff.files_changed:
            extra.append(MISSING_TEXT["no_changes"])
            tests = None
            last["tests"] = None
        else:
            tests = await steps.run_tests(inp, checkout)
            last["tests"] = tests
            result.tests_passed, result.tests_failed = tests.passed, tests.failed
            result.failing = [f.wire() for f in tests.failing]
            await steps.emit("tests.result", {
                "buildId": inp.build_id, "passed": tests.passed, "failed": tests.failed,
                "skipped": tests.skipped, "failing": [f.wire() for f in tests.failing][:20],
                "command": tests.command, "source": tests.source, "parser": tests.parser,
                "network": (tests.isolation.network_mode if tests.isolation else None)})
        missing = pi.missing_items()
        if tests is not None and tests.ok and not missing and not extra:
            break
        reason = "tests_failed" if tests is not None and not tests.ok else "protocol_incomplete"
        if repairs >= inp.max_repairs:
            return await finish("failed", reason, ", ".join(missing + extra))
        repairs += 1
        await steps.emit("build.repair", {"buildId": inp.build_id, "attempt": repairs,
                                          "reason": reason if not missing else f"missing: {', '.join(missing)}"})
        await steps.write_failures(inp, checkout, render_failures(pi, tests, extra), pi.reminders)

    try:
        head = await steps.commit_and_push(inp, checkout)
    except BuildStop as stop:
        return await finish("stopped", stop.reason, stop.message)
    result.head_sha = head
    await steps.emit("build.passed", {"buildId": inp.build_id, "headSha": head})
    pr = await steps.open_pr(inp, result)
    result.pr_number, result.pr_url = pr.number, pr.url
    if pr.action == "opened":
        await steps.emit("pr.opened", {"number": pr.number, "url": pr.url, "headSha": head})
    else:
        await steps.emit("pr.updated", {"number": pr.number, "headSha": head})
    return await finish("passed")


class LocalBuildSteps:
    """Runs every step in this process (tests, CLI). The workflow uses activities instead."""

    def __init__(
        self,
        env: BuildEnv,
        *,
        emit: EventSink,
        tools: ToolCaller | None = None,
        scope_judge: dc.ScopeJudge | None = None,
        github_transport: httpx.AsyncBaseTransport | None = None,
        runner: Runner | None = None,
        heartbeat: Callable[[dict[str, Any]], None] | None = None,
        run_token: str | None = None,
    ) -> None:
        self.env = env
        self._emit = emit
        self.tools = tools
        self.scope_judge = scope_judge
        self.github_transport = github_transport
        self.runner = runner or Runner()
        self.heartbeat = heartbeat
        self.run_token = run_token
        self._checkout: CheckoutInfo | None = None

    async def prepare_checkout(self, inp: BuildInput) -> CheckoutInfo:
        self._checkout = await prepare_checkout(inp, self.env, self.runner)
        return self._checkout

    async def write_context(self, inp: BuildInput, checkout: CheckoutInfo) -> ContextInfo:
        return await write_build_context(inp, checkout, self.env, tools=self.tools)

    async def run_pi(self, inp: BuildInput, attempt: int) -> PiAttempt:
        return await run_pi(inp, self.env, attempt=attempt, emit=self._emit, heartbeat=self.heartbeat,
                            run_token=self.run_token or "test-run-token", runner=self.runner)

    async def check_diff(self, inp: BuildInput, checkout: CheckoutInfo) -> dc.DiffCheck:
        return await check_build_diff(inp, checkout, scope_judge=self.scope_judge)

    async def run_tests(self, inp: BuildInput, checkout: CheckoutInfo) -> tr.TestResult:
        return await run_build_tests(inp, checkout, self.env)

    async def write_failures(self, inp: BuildInput, checkout: CheckoutInfo, text: str,
                             reminders: list[str]) -> None:
        write_failures(inp, self.env, text)
        if reminders:
            rewrite_task_with_reminders(inp, checkout, self.env, list(dict.fromkeys(reminders)))

    async def commit_and_push(self, inp: BuildInput, checkout: CheckoutInfo) -> str:
        return await commit_and_push(inp, checkout, self.env, self.runner)

    async def open_pr(self, inp: BuildInput, result: BuildResult) -> PrInfo:
        return await open_or_update_pr(inp, result, self.env, transport=self.github_transport)

    async def read_notes(self, inp: BuildInput) -> str:
        return read_notes(inp, self.env)

    async def emit(self, type: str, payload: dict[str, Any]) -> None:
        await self._emit(type, payload)

    def now_ms(self) -> int:
        return int(time.time() * 1000)


def read_notes(inp: BuildInput, env: BuildEnv) -> str:
    path = BuildPaths.for_build(env.host_dir, inp.build_id).context / "notes.md"
    return path.read_text(errors="replace")[:20000] if path.exists() else ""
