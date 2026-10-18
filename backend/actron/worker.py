"""Worker process (`python -m actron.worker`): one Temporal client and a worker per task queue, the MCP graph
server for Pi, Slack Socket Mode when an app-level token exists, and the signal reconciler (spec B, B1, B4, B11).

Task queues and modules are fixed in specs/WORKSTREAMS.md:
ingest (source_sync + activities.ingest), link (linking + activities.link),
request (request + writeback + activities.request), build (build + activities.build; at most
ACTRON_MAX_CONCURRENT_BUILDS activities at once).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import inspect
import signal
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from actron.config import get_settings
from actron.logging import get_logger

log = get_logger(__name__)

QUEUES: dict[str, tuple[list[str], list[str]]] = {
    "ingest": (["actron.workflows.source_sync"], ["actron.activities.ingest"]),
    "link": (["actron.workflows.linking"], ["actron.activities.link"]),
    "request": (["actron.workflows.request", "actron.workflows.writeback"], ["actron.activities.request"]),
    "build": (["actron.workflows.build"], ["actron.activities.build"]),
}


def _workflows(module: Any) -> list[type]:
    found = getattr(module, "WORKFLOWS", None)
    if found:
        return list(found)
    return [obj for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and hasattr(obj, "__temporal_workflow_definition")]


def load_queue(queue: str) -> tuple[list[type], list[Callable[..., Any]]]:
    """Import the workflow classes and ACTIVITIES of one task queue. A module that is missing is skipped."""
    wf_mods, act_mods = QUEUES[queue]
    workflows: list[type] = []
    activities: list[Callable[..., Any]] = []
    for name in wf_mods:
        try:
            workflows += _workflows(importlib.import_module(name))
        except ImportError as exc:
            log.warning("workflow module missing", extra={"module": name, "error": str(exc)[:200]})
    for name in act_mods:
        try:
            activities += list(importlib.import_module(name).ACTIVITIES)
        except (ImportError, AttributeError) as exc:
            log.warning("activity module missing", extra={"module": name, "error": str(exc)[:200]})
    return workflows, activities


async def connect() -> Any:
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    s = get_settings()
    return await Client.connect(s.TEMPORAL_ADDRESS, namespace=s.TEMPORAL_NAMESPACE,
                                data_converter=pydantic_data_converter)


def build_workers(client: Any, queues: Sequence[str], executor: ThreadPoolExecutor) -> list[Any]:
    from temporalio.worker import Worker

    settings = get_settings()
    workers = []
    for queue in queues:
        workflows, activities = load_queue(queue)
        if not workflows and not activities:
            log.warning("nothing to run on task queue", extra={"queue": queue})
            continue
        kwargs: dict[str, Any] = {}
        if queue == "build":
            kwargs["max_concurrent_activities"] = settings.ACTRON_MAX_CONCURRENT_BUILDS
        try:
            workers.append(Worker(client, task_queue=queue, workflows=workflows, activities=activities,
                                  activity_executor=executor, **kwargs))
            log.info("worker ready", extra={"queue": queue, "workflows": len(workflows),
                                            "activities": len(activities)})
        except Exception as exc:
            log.error("worker could not start", extra={"queue": queue, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return workers


def slack_app_token_present() -> bool:
    if get_settings().SLACK_APP_TOKEN:
        return True
    try:
        from sqlalchemy import select

        from actron.db import models as m
        from actron.db.crypto import decrypt_secret
        from actron.db.session import session_scope

        with session_scope() as s:
            for blob in s.scalars(select(m.Connection.secret_encrypted).where(
                    m.Connection.provider == "slack", m.Connection.status == "connected")):
                if blob and decrypt_secret(bytes(blob)).get("app_token"):
                    return True
    except Exception as exc:
        log.warning("could not read Slack connections", extra={"error": type(exc).__name__})
    return False


async def run(queues: Sequence[str], *, mcp: bool = True, slack: bool = True, reconciler: bool = True) -> None:
    from actron.flow import service

    client = await connect()
    service.set_gateway(service.TemporalGateway(fixed_client=client))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)
    executor = ThreadPoolExecutor(max_workers=32)
    tasks: list[asyncio.Task[Any]] = []
    for w in build_workers(client, queues, executor):
        tasks.append(asyncio.create_task(w.run(), name=f"worker:{w.task_queue}"))
    if mcp:
        try:
            from actron.mcp_graph.server import serve_http

            tasks.append(asyncio.create_task(serve_http(port=get_settings().ACTRON_MCP_PORT), name="mcp"))
        except ImportError as exc:
            log.warning("MCP server not available", extra={"error": str(exc)[:200]})
    if slack and slack_app_token_present():
        try:
            from actron.integrations.slack_bot import run_socket_mode

            tasks.append(asyncio.create_task(run_socket_mode(), name="slack-socket-mode"))
        except ImportError as exc:
            log.warning("Slack Socket Mode not available", extra={"error": str(exc)[:200]})
    if reconciler:
        tasks.append(asyncio.create_task(service.reconciler_loop(30.0, stop), name="reconciler"))
    log.info("worker running", extra={"queues": list(queues), "tasks": [t.get_name() for t in tasks]})
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait([waiter, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        if t is not waiter and t.exception() is not None:
            log.error("worker task failed", extra={"task": t.get_name(), "error": repr(t.exception())[:300]})
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    executor.shutdown(wait=False, cancel_futures=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="actron-worker", description="Run Actron's Temporal workers.")
    parser.add_argument("--queues", default=",".join(QUEUES), help="comma list of task queues")
    parser.add_argument("--no-mcp", action="store_true")
    parser.add_argument("--no-slack", action="store_true")
    parser.add_argument("--no-reconciler", action="store_true")
    args = parser.parse_args(argv)
    queues = [q for q in args.queues.split(",") if q in QUEUES]
    asyncio.run(run(queues, mcp=not args.no_mcp, slack=not args.no_slack, reconciler=not args.no_reconciler))


if __name__ == "__main__":
    main()
