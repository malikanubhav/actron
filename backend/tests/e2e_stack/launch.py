"""Start the e2e stack in the foreground (PROMPT 9.6). Stop it with Ctrl-C or SIGTERM.

    cd backend && uv run python -m tests.e2e_stack.launch [--build-frontend] [--no-frontend]

What runs (all on 127.0.0.1, separate from the compose stack and its `dev` data):
- fake GitHub :18101 (git-backed, see github_git.py), fake Slack :18102, fake Linear :18103
- control API :18100 (recorded calls, error injection; used by the Playwright specs)
- backend :18080 and worker (Temporal namespace `actron-e2e`, PostgreSQL database `actron_e2e`, Redis db 8,
  FalkorDB graph `actrone2e_e2e` without unique constraints, dev workspace `e2e`)
- frontend :3300 (`next start` of a build in frontend/.next-e2e whose proxy points at :18080)
The shared stores (FalkorDB, PostgreSQL, Redis, Temporal) come from `make up-deps`; nothing here restarts them.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from actron.config import REPO_ROOT
from tests.e2e_stack import world
from tests.e2e_stack.github_git import GitFakeGithub
from tests.fakes.linear import FakeLinear
from tests.fakes.slack import FakeSlack

ROOT = REPO_ROOT / ".actron" / "e2e"
PORTS = {"control": 18100, "github": 18101, "slack": 18102, "linear": 18103, "jev": 18104, "backend": 18080,
         "frontend": 3300, "mcp": 18765}
WS = "e2e"
DB_NAME = "actron_e2e"
REDIS_DB = 8
GRAPH_PREFIX = "actrone2e"
NAMESPACE = "actron-e2e"
SIGNING_SECRET = "e2e-signing-secret-not-a-real-one"
STORE_HOST = "127.0.0.1"


def backend_env(root: Path) -> dict[str, str]:
    """Environment for the e2e backend and worker. Blank values override anything in the developer's .env."""
    git_root = root / "git"
    env = dict(os.environ)
    env.update({
        "ACTRON_ENV": "dev", "ACTRON_DEV_WORKSPACE": WS, "ACTRON_LOG_LEVEL": "INFO",
        "ACTRON_PUBLIC_URL": f"http://127.0.0.1:{PORTS['frontend']}",
        "DATABASE_URL": f"postgresql+psycopg://actron:actron@{STORE_HOST}:5433/{DB_NAME}",
        "REDIS_URL": f"redis://{STORE_HOST}:6380/{REDIS_DB}",
        "FALKORDB_URL": f"redis://{STORE_HOST}:6389", "FALKORDB_GRAPH_PREFIX": GRAPH_PREFIX,
        "FALKORDB_UNIQUE_CONSTRAINTS": "false",
        "TEMPORAL_ADDRESS": f"{STORE_HOST}:7233", "TEMPORAL_NAMESPACE": NAMESPACE,
        "GITHUB_API_URL": f"http://127.0.0.1:{PORTS['github']}", "GITHUB_GIT_URL": f"file://{git_root}",
        "GITHUB_TOKEN": world.GITHUB_TOKEN, "GITHUB_REPOSITORY": "", "GITHUB_FORK": "", "GITHUB_UPSTREAM": "",
        "GITHUB_WEBHOOK_SECRET": "e2e-webhook-secret",
        "SLACK_API_URL": f"http://127.0.0.1:{PORTS['slack']}/api/", "SLACK_SIGNING_SECRET": SIGNING_SECRET,
        "SLACK_BOT_TOKEN": "", "SLACK_APP_TOKEN": "", "SLACK_CLIENT_ID": "", "SLACK_CLIENT_SECRET": "",
        "SLACK_CHANNELS": "",
        "LINEAR_API_URL": f"http://127.0.0.1:{PORTS['linear']}/graphql", "LINEAR_API_KEY": "", "LINEAR_TEAM_ID": "",
        "LINEAR_TIMEOUT_SECONDS": "3",
        # Jev is the scripted fake (jev_answer): stub answers, except review feedback.
        "TYPESAFE_API_KEY": "jev-e2e-placeholder-not-a-key",
        "JEV_API_URL": f"http://127.0.0.1:{PORTS['jev']}/v1/systemone", "OPENROUTER_API_KEY": "", "GEMINI_API_KEY": "", "GROQ_API_KEY": "",
        "MODEL_DECISION": "", "MODEL_WRITING": "", "MODEL_AGENT": "", "LITELLM_FALLBACKS": "",
        # The fake Pi needs a coding model and a key name to pass; the value is a placeholder, never sent anywhere.
        "MODEL_CODING": "anthropic/e2e-fake-coding-model", "ANTHROPIC_API_KEY": "sk-ant-e2e-placeholder-not-a-key",
        "ACTRON_BOT_NAME": "Actron E2E Bot", "ACTRON_BOT_EMAIL": "bot@actron.e2e.test",
        "ACTRON_PI_IMAGE": "actron-fake-pi:test",
        "ACTRON_PI_EXTRA_ENV": json.dumps({"FAKE_PI_SCENARIO": "fail_then_repair"}),
        "ACTRON_BUILD_HOST_DIR": str(root / "builds"), "ACTRON_CLONE_DIR": str(root / "clones"),
        "ACTRON_MCP_PORT": str(PORTS["mcp"]), "ACTRON_MCP_URL": f"http://127.0.0.1:{PORTS['mcp']}/mcp",
        "ACTRON_MAX_REPAIRS": "2", "ACTRON_BUILD_TIMEOUT_SECONDS": "600", "ACTRON_BACKFILL_DAYS": "90",
        "API_INTERNAL_URL": f"http://127.0.0.1:{PORTS['backend']}", "NEXT_PUBLIC_ACTRON_DEV_FIXTURES": "0",
        "PYTHONUNBUFFERED": "1",
    })
    return env


# Preparation (idempotent; every start begins from an empty e2e world)
def reset_postgres(env: dict[str, str]) -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(f"postgresql+psycopg://actron:actron@{STORE_HOST}:5433/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    admin.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "-c", "actron/db/alembic.ini", "upgrade", "head"],
                   cwd=REPO_ROOT / "backend", env=env, check=True, capture_output=True)


def reset_redis() -> None:
    import redis

    client = redis.Redis(host=STORE_HOST, port=6380, db=REDIS_DB)
    client.flushdb()
    client.close()


def reset_graph() -> None:
    """Drop the e2e graphs. They never get unique constraints (FALKORDB_UNIQUE_CONSTRAINTS=false); a graph that
    has one anyway is emptied instead of dropped (docs/falkordb.md, limitation 12)."""
    import redis

    client = redis.Redis(host=STORE_HOST, port=6389, decode_responses=True)
    try:
        for name in client.execute_command("GRAPH.LIST") or []:
            if not str(name).startswith(f"{GRAPH_PREFIX}_"):
                continue
            rows = client.execute_command("GRAPH.RO_QUERY", name, "CALL db.constraints()")
            if rows and len(rows) > 1 and rows[1]:
                while True:
                    res = client.execute_command("GRAPH.QUERY", name,
                                                 "MATCH (n) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*)")
                    if not res[1] or not res[1][0] or not res[1][0][0]:
                        break
            else:
                client.execute_command("GRAPH.DELETE", name)
    finally:
        client.close()


async def reset_temporal() -> None:
    from google.protobuf.duration_pb2 import Duration
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, RegisterNamespaceRequest
    from temporalio.client import Client
    from temporalio.service import RPCError

    base = await Client.connect(f"{STORE_HOST}:7233")
    try:
        await base.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=NAMESPACE))
    except RPCError:
        await base.workflow_service.register_namespace(RegisterNamespaceRequest(
            namespace=NAMESPACE, workflow_execution_retention_period=Duration(seconds=24 * 3600)))
    client = None
    for _ in range(60):
        try:
            client = await Client.connect(f"{STORE_HOST}:7233", namespace=NAMESPACE)
            await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=NAMESPACE))
            break
        except RPCError:
            await asyncio.sleep(1)
    assert client is not None
    # A new namespace reaches every Temporal service a few seconds after it is registered.
    for attempt in range(60):
        try:
            async for sched in await client.list_schedules():
                with contextlib.suppress(RPCError):
                    await client.get_schedule_handle(sched.id).delete()
            async for wf in client.list_workflows("ExecutionStatus='Running'"):
                with contextlib.suppress(RPCError):
                    await client.get_workflow_handle(wf.id, run_id=wf.run_id).terminate("e2e stack restart")
            return
        except RPCError:
            if attempt == 59:
                raise
            await asyncio.sleep(1)


# Fakes and the control API
class Fakes:
    def __init__(self, root: Path) -> None:
        self.github = GitFakeGithub(root / "git", public_base="https://github.example.test")
        self.slack = FakeSlack()
        self.linear = FakeLinear(api_key=world.LINEAR_KEY)
        self.linear_delay: dict[str, float] = {}
        self.supervisor: Supervisor | None = None
        world.fill_github(self.github)
        world.fill_slack(self.slack)
        world.fill_linear(self.linear)
        self._wrap_linear()

    def _wrap_linear(self) -> None:
        """Delay chosen Linear operations (to show the timeout state); the base fake has no delay."""
        inner = self.linear._handle

        async def handle(request: Request) -> Any:
            body = await request.json()
            op = body.get("operationName") or ""
            delay = self.linear_delay.get(op) or self.linear_delay.get("*")
            if delay:
                await asyncio.sleep(delay)
            return await inner(request)

        self.linear.app = Starlette(routes=[Route("/graphql", handle, methods=["POST"])])

    def control_app(self) -> Starlette:
        async def health(_: Request) -> JSONResponse:
            return JSONResponse({"ok": True, "ports": PORTS, "workspace": WS, "slackTeam": world.SLACK_TEAM,
                                 "slackChannel": world.SLACK_CHANNEL, "requester": world.REQUESTER,
                                 "approver": world.APPROVER, "signingSecret": SIGNING_SECRET,
                                 "githubToken": world.GITHUB_TOKEN, "linearKey": world.LINEAR_KEY,
                                 "slackBotToken": world.SLACK_BOT_TOKEN, "repo": world.REPO, "fork": world.FORK})

        async def slack_calls(request: Request) -> JSONResponse:
            method = request.query_params.get("method")
            calls = [{"method": m, "params": p} for m, p in self.slack.calls if not method or m == method]
            return JSONResponse({"calls": calls})

        async def slack_fail(request: Request) -> JSONResponse:
            b = await request.json()
            self.slack.fail(b["method"], b.get("error", "internal_error"), int(b.get("times", 1)))
            return JSONResponse({"ok": True})

        async def github_inject(request: Request) -> JSONResponse:
            b = await request.json()
            self.github.inject(b["match"], int(b.get("status", 500)), body=b.get("body"), times=int(b.get("times", 1)))
            return JSONResponse({"ok": True})

        async def github_pulls(_: Request) -> JSONResponse:
            return JSONResponse({"pulls": self.github.summary()})

        async def github_requests(request: Request) -> JSONResponse:
            pattern = request.query_params.get("match", "")
            return JSONResponse({"count": self.github.count(pattern) if pattern else len(self.github.requests)})

        async def linear_inject(request: Request) -> JSONResponse:
            b = await request.json()
            self.linear.inject(b["operation"], status=int(b.get("status", 500)), body=b.get("body"),
                               times=int(b.get("times", 1)))
            return JSONResponse({"ok": True})

        async def linear_delay(request: Request) -> JSONResponse:
            b = await request.json()
            op, seconds = str(b.get("operation", "*")), float(b.get("seconds", 0))
            if seconds <= 0:
                self.linear_delay.pop(op, None)
            else:
                self.linear_delay[op] = seconds
            return JSONResponse({"ok": True, "delays": self.linear_delay})

        async def linear_issues(_: Request) -> JSONResponse:
            return JSONResponse({"issues": list(self.linear.issues.values()),
                                 "calls": [op for op, _, _ in self.linear.requests]})

        async def github_delay(request: Request) -> JSONResponse:
            b = await request.json()
            pattern, seconds = str(b["match"]), float(b.get("seconds", 0))
            if seconds <= 0:
                self.github.delays.pop(pattern, None)
            else:
                self.github.delays[pattern] = seconds
            return JSONResponse({"ok": True, "delays": self.github.delays})

        async def backend_down(_: Request) -> JSONResponse:
            assert self.supervisor is not None
            await asyncio.to_thread(self.supervisor.stop, "backend")
            return JSONResponse({"ok": True})

        async def backend_up(_: Request) -> JSONResponse:
            assert self.supervisor is not None
            self.supervisor.start("backend")
            await wait_http(BACKEND_HEALTH, 120, ok=(200, 503))
            return JSONResponse({"ok": True})

        async def clear(_: Request) -> JSONResponse:
            self.github.injected.clear()
            self.github.delays.clear()
            self.linear.injected.clear()
            self.slack.injected.clear()
            self.linear_delay.clear()
            return JSONResponse({"ok": True})

        async def respond(_: Request) -> JSONResponse:  # Slack response_url
            return JSONResponse({"ok": True})

        return Starlette(routes=[
            Route("/github/delay", github_delay, methods=["POST"]),
            Route("/backend/down", backend_down, methods=["POST"]), Route("/backend/up", backend_up, methods=["POST"]),
            Route("/slack/respond", respond, methods=["POST"]),
            Route("/health", health), Route("/slack/calls", slack_calls), Route("/slack/fail", slack_fail, methods=["POST"]),
            Route("/github/inject", github_inject, methods=["POST"]), Route("/github/pulls", github_pulls),
            Route("/github/requests", github_requests),
            Route("/linear/inject", linear_inject, methods=["POST"]), Route("/linear/delay", linear_delay, methods=["POST"]),
            Route("/linear/issues", linear_issues), Route("/clear", clear, methods=["POST"]),
        ])


def jev_answer(qid: str, question: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Scripted Jev for the e2e stack: the stub's answer for every job (models/stubs.py), except that review
    feedback asking for a change is classified as a code change within scope (the stub never acts on feedback),
    so "Request changes" starts a new build as it does with a real model."""
    from actron.models.stubs import STUB_ANSWERS
    from tests.fakes.jev import choice_answer, noul_answer, score_answer

    keys = set(state)
    if question["type"] == "choice":
        options = list(question["criteria"])
        if "feedback" in keys:
            text = str(state.get("feedback", "")).lower()
            pick = "approval" if "looks good" in text else (
                "code_change_within_scope" if any(w in text for w in ("rename", "change", "add", "make")) else "question")
        elif "decision" in options or "chatter" in options:
            pick = str(STUB_ANSWERS["classify_message"][0])
        elif "feature" in options:
            pick = str(STUB_ANSWERS["classify_request"][0])
        else:
            pick = "unrelated" if "unrelated" in options else options[0]
        return choice_answer(pick if pick in options else options[0], options, 0.8)
    if question["type"] == "score":
        return score_answer(list(question["criteria"]), 0.0)
    job = ("needs_question" if "findings_summary" in keys
           else "is_scope_change" if "files_outside_affected_list" in keys
           else "check_link" if {"quote", "claim"} <= keys
           else "is_approval" if "reply" in keys
           else "judge_link")
    return noul_answer(STUB_ANSWERS[job][1])


def jev_app() -> Starlette:
    from tests.fakes.jev import FakeJev

    fake = FakeJev(answer_fn=jev_answer)

    async def handle(request: Request) -> Response:
        req = httpx.Request("POST", str(request.url), headers=request.headers.raw, content=await request.body())
        resp = fake.handle(req)
        return Response(resp.content, status_code=resp.status_code, media_type="application/json",
                        headers={k: v for k, v in resp.headers.items() if k.lower() == "retry-after"})

    return Starlette(routes=[Route("/v1/systemone", handle, methods=["POST"])])


def frontend_dir() -> Path:
    return REPO_ROOT / "frontend"


def build_frontend(env: dict[str, str], log_dir: Path) -> None:
    # Turbopack (Next 16.4.2) fails on a cold Google-fonts download here ("next/font/google queries have exactly
    # one entry"); starting from another build's cache avoids the download.
    import shutil

    cache = frontend_dir() / ".next-e2e" / "cache"
    if not cache.exists():
        for other in (".next", ".next-fixtures"):
            src = frontend_dir() / other / "cache"
            if src.is_dir():
                shutil.copytree(src, cache)
                break
    fe_env = dict(env, NEXT_DIST_DIR=".next-e2e", NEXT_TELEMETRY_DISABLED="1")
    with open(log_dir / "frontend-build.log", "w") as out:
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir(), env=fe_env, stdout=out, stderr=subprocess.STDOUT,
                       check=True)


async def wait_http(url: str, timeout: float, ok: tuple[int, ...] = (200,)) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5) as c:
        while time.monotonic() < deadline:
            with contextlib.suppress(httpx.HTTPError):
                if (await c.get(url)).status_code in ok:
                    return
            await asyncio.sleep(0.5)
    raise TimeoutError(f"{url} did not answer within {timeout:.0f} s")


async def main(args: argparse.Namespace) -> None:
    root: Path = args.root
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (root / "builds").mkdir(parents=True, exist_ok=True)
    pidfile = root / "launch.pid"
    pidfile.write_text(str(os.getpid()))
    env = backend_env(root)
    world.build_git(root)
    reset_postgres(env)
    reset_redis()
    reset_graph()
    await reset_temporal()
    fakes = Fakes(root)
    servers = [uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORTS[name], log_level="warning",
                                             lifespan="off"))
               for name, app in (("github", fakes.github.app), ("slack", fakes.slack.app),
                                 ("linear", fakes.linear.app), ("jev", jev_app()), ("control", fakes.control_app()))]
    serving = [asyncio.create_task(s.serve()) for s in servers]
    sup = Supervisor(env, log_dir)
    fakes.supervisor = sup
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        sup.add("backend", [sys.executable, "-m", "uvicorn", "actron.api.app:app", "--host", "127.0.0.1",
                            "--port", str(PORTS["backend"])], REPO_ROOT / "backend")
        sup.add("worker", [sys.executable, "-m", "actron.worker"], REPO_ROOT / "backend")
        if not args.no_frontend:
            dist = frontend_dir() / ".next-e2e"
            if args.build_frontend or not (dist / "BUILD_ID").exists():
                await asyncio.to_thread(build_frontend, env, log_dir)
            sup.add("frontend", ["npx", "next", "start", "--port", str(PORTS["frontend"]), "--hostname", "127.0.0.1"],
                    frontend_dir(), {"NEXT_DIST_DIR": ".next-e2e", "NEXT_TELEMETRY_DISABLED": "1"})
        await wait_http(BACKEND_HEALTH, 120, ok=(200, 503))
        if not args.no_frontend:
            await wait_http(f"http://127.0.0.1:{PORTS['frontend']}/app/signin", 120)
        print(f"E2E STACK READY frontend=http://127.0.0.1:{PORTS['frontend']} "
              f"backend=http://127.0.0.1:{PORTS['backend']} control=http://127.0.0.1:{PORTS['control']}", flush=True)
        while not stop.is_set():
            dead = sup.unexpected_exit()
            if dead:
                print(f"a child process exited: {dead}", flush=True)
                stop.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), 2)
    finally:
        sup.stop_all()
        for s in servers:
            s.should_exit = True
        await asyncio.gather(*serving, return_exceptions=True)
        pidfile.unlink(missing_ok=True)


BACKEND_HEALTH = f"http://127.0.0.1:{PORTS['backend']}/api/health"


class Supervisor:
    """The stack's child processes. The control API can stop and start the backend (the backend-down state)."""

    def __init__(self, env: dict[str, str], log_dir: Path) -> None:
        self.env, self.log_dir = env, log_dir
        self.specs: dict[str, tuple[list[str], Path, dict[str, str]]] = {}
        self.procs: dict[str, subprocess.Popen[bytes]] = {}
        self.down: set[str] = set()

    def add(self, name: str, cmd: list[str], cwd: Path, extra: dict[str, str] | None = None) -> None:
        self.specs[name] = (cmd, cwd, extra or {})
        self.start(name)

    def start(self, name: str) -> None:
        cmd, cwd, extra = self.specs[name]
        out = open(self.log_dir / f"{name}.log", "ab")  # noqa: SIM115 - kept open for the child's lifetime
        self.procs[name] = subprocess.Popen(cmd, cwd=cwd, env=dict(self.env, **extra), stdout=out,
                                            stderr=subprocess.STDOUT, start_new_session=True)
        self.down.discard(name)

    def stop(self, name: str) -> None:
        self.down.add(name)
        p = self.procs.get(name)
        if p is None or p.poll() is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=5)

    def unexpected_exit(self) -> str | None:
        for name, p in self.procs.items():
            if name not in self.down and p.poll() is not None:
                return f"{name} ({p.returncode})"
        return None

    def stop_all(self) -> None:
        for name in list(self.procs):
            self.stop(name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--build-frontend", action="store_true", help="rebuild frontend/.next-e2e first")
    parser.add_argument("--no-frontend", action="store_true")
    asyncio.run(main(parser.parse_args()))
