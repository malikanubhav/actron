"""Activities of `BuildWorkflow` (task queue `build`). Each wraps one step of `actron.flow.build`.

Arguments and results are plain JSON dicts (camelCase, B.C6), so the workflow works with Temporal's default
data converter. A `BuildStop` inside an activity becomes a non-retryable `ApplicationError` of type
`BuildStop` whose first detail is the reason; the workflow turns it back into `BuildStop`.

The queue (B-AC-47) is a Redis sorted set of waiting builds plus a sorted set of running builds, changed by
one Lua script so two workers never take the same slot. Position = builds running + builds ahead in line.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from actron.flow import build as b
from actron.flow import diff_check as dc
from actron.flow.context_pack import ContextPackUnavailable, ToolCaller, graph_tool_caller
from actron.logging import get_logger

log = get_logger(__name__)

QUEUE_KEY = "actron:build:queue"
RUNNING_KEY = "actron:build:running"
STALE_MS = 6 * 3600 * 1000

# KEYS[1]=queue KEYS[2]=running; ARGV: build_id, slots, now_ms, stale_ms. Returns 0 when the slot is taken,
# else the number of builds ahead (running + earlier in line).
_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', tonumber(ARGV[3]) - tonumber(ARGV[4]))
if redis.call('ZSCORE', KEYS[2], ARGV[1]) then return 0 end
local rank = redis.call('ZRANK', KEYS[1], ARGV[1])
if not rank then return -1 end
local running = redis.call('ZCARD', KEYS[2])
if rank == 0 and running < tonumber(ARGV[2]) then
  redis.call('ZREM', KEYS[1], ARGV[1])
  redis.call('ZADD', KEYS[2], ARGV[3], ARGV[1])
  return 0
end
return running + rank
"""

EmitFactory = Callable[[str, str], b.EventSink]
ToolsFactory = Callable[[b.BuildInput, b.CheckoutInfo, b.EventSink], ToolCaller | None]


def service_emit(ws: str, request_id: str) -> b.EventSink:
    """W6's `actron.flow.events.emit` (stores, publishes and notifies)."""

    async def emit(type: str, payload: dict[str, Any], *, actor: str = "actron", surface: str = "system") -> None:
        from actron.flow.events import emit as store_event

        await store_event(ws, request_id, type, payload, actor=actor, surface=surface)

    return emit


def default_tools(inp: b.BuildInput, checkout: b.CheckoutInfo, emit: b.EventSink) -> ToolCaller | None:
    try:
        return graph_tool_caller(inp.ws, emit=emit, snapshot_sha=checkout.base_sha,
                                 differing_paths=checkout.differing_files, repo_dir=Path(checkout.repo_dir))
    except ContextPackUnavailable as exc:
        log.warning("graph tools unavailable for the context pack", extra={"error": str(exc)})
        return None


def _budget_status(ws: str) -> dict[str, Any]:
    from actron.db.session import session_scope
    from actron.flow import budget

    with session_scope() as session:
        return budget.status(session, ws)


async def default_budget(ws: str) -> dict[str, Any]:
    """W6's `actron.flow.budget.status(session, ws)` → {capUsd, spentTodayUsd, reached}."""
    value = await asyncio.to_thread(_budget_status, ws)
    return {"reached": bool(value.get("reached")), "spentUsd": value.get("spentTodayUsd"),
            "capUsd": value.get("capUsd")}


def _stop(exc: b.BuildStop) -> ApplicationError:
    return ApplicationError(exc.message, exc.reason, type="BuildStop", non_retryable=True)


class BuildActivities:
    """Holds the dependencies; tests build their own instance with fakes."""

    def __init__(
        self,
        env: b.BuildEnv | None = None,
        *,
        emit_factory: EmitFactory = service_emit,
        tools_factory: ToolsFactory = default_tools,
        scope_judge: dc.ScopeJudge | None = None,
        github_transport: httpx.AsyncBaseTransport | None = None,
        budget_check: Callable[[str], Any] = default_budget,
        redis_url: str | None = None,
        max_slots: int | None = None,
        run_token: str | None = None,
    ) -> None:
        self._env = env
        self.emit_factory = emit_factory
        self.tools_factory = tools_factory
        self.scope_judge = scope_judge
        self.github_transport = github_transport
        self.budget_check = budget_check
        self._redis_url = redis_url
        self._max_slots = max_slots
        self.run_token = run_token

    @property
    def env(self) -> b.BuildEnv:
        if self._env is None:
            self._env = b.BuildEnv.from_settings()
        return self._env

    def _redis(self) -> Any:
        import redis.asyncio as aioredis

        from actron.config import get_settings

        return aioredis.Redis.from_url(self._redis_url or get_settings().REDIS_URL, decode_responses=True)

    def _slots(self) -> int:
        if self._max_slots is not None:
            return self._max_slots
        from actron.config import get_settings

        return get_settings().ACTRON_MAX_CONCURRENT_BUILDS

    # Steps ----------------------------------------------------------------
    @activity.defn(name="build_prepare_checkout")
    async def prepare_checkout(self, inp: dict[str, Any]) -> dict[str, Any]:
        try:
            model = b.BuildInput.model_validate(inp)
            return (await b.prepare_checkout(model, self.env.for_workspace(model.ws))).wire()
        except b.BuildStop as exc:
            raise _stop(exc) from None

    @activity.defn(name="build_write_context")
    async def write_context(self, inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
        model = b.BuildInput.model_validate(inp)
        co = b.CheckoutInfo.model_validate(checkout)
        tools = self.tools_factory(model, co, self.emit_factory(model.ws, model.request_id))
        info = await b.write_build_context(model, co, self.env, tools=tools)
        return info.wire()

    @activity.defn(name="build_run_pi")
    async def run_pi(self, inp: dict[str, Any], attempt: int) -> dict[str, Any]:
        model = b.BuildInput.model_validate(inp)

        def beat(details: dict[str, Any]) -> None:
            activity.heartbeat(details)

        try:
            result = await b.run_pi(model, self.env, attempt=attempt,
                                    emit=self.emit_factory(model.ws, model.request_id),
                                    heartbeat=beat, run_token=self.run_token)
        except b.BuildStop as exc:
            raise _stop(exc) from None
        return result.wire()

    @activity.defn(name="build_check_diff")
    async def check_diff(self, inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
        result = await b.check_build_diff(b.BuildInput.model_validate(inp), b.CheckoutInfo.model_validate(checkout),
                                          scope_judge=self.scope_judge)
        return result.wire()

    @activity.defn(name="build_run_tests")
    async def run_tests(self, inp: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
        result = await b.run_build_tests(b.BuildInput.model_validate(inp), b.CheckoutInfo.model_validate(checkout),
                                         self.env)
        return result.wire()

    @activity.defn(name="build_write_failures")
    async def write_failures(self, inp: dict[str, Any], checkout: dict[str, Any], text: str,
                             reminders: list[str]) -> None:
        model = b.BuildInput.model_validate(inp)
        b.write_failures(model, self.env, text)
        if reminders:
            b.rewrite_task_with_reminders(model, b.CheckoutInfo.model_validate(checkout), self.env,
                                          list(dict.fromkeys(reminders)))

    @activity.defn(name="build_commit_and_push")
    async def commit_and_push(self, inp: dict[str, Any], checkout: dict[str, Any]) -> str:
        try:
            model = b.BuildInput.model_validate(inp)
            return await b.commit_and_push(model, b.CheckoutInfo.model_validate(checkout),
                                           self.env.for_workspace(model.ws))
        except b.BuildStop as exc:
            raise _stop(exc) from None

    @activity.defn(name="build_open_pr")
    async def open_pr(self, inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        pr = await b.open_or_update_pr(b.BuildInput.model_validate(inp), b.BuildResult.model_validate(result),
                                       self.env, transport=self.github_transport)
        return pr.wire()

    @activity.defn(name="build_read_notes")
    async def read_notes(self, inp: dict[str, Any]) -> str:
        return b.read_notes(b.BuildInput.model_validate(inp), self.env)

    @activity.defn(name="build_emit")
    async def emit(self, ws: str, request_id: str, type: str, payload: dict[str, Any]) -> None:
        await self.emit_factory(ws, request_id)(type, payload)

    # Budget and queue -----------------------------------------------------
    @activity.defn(name="build_check_budget")
    async def check_budget(self, ws: str) -> dict[str, Any]:
        value = self.budget_check(ws)
        if inspect.isawaitable(value):
            value = await value
        return dict(value)

    @activity.defn(name="build_queue_enter")
    async def queue_enter(self, build_id: str, enqueued_ms: int) -> None:
        r = self._redis()
        try:
            await r.zadd(QUEUE_KEY, {build_id: enqueued_ms}, nx=True)
        finally:
            await r.aclose()

    @activity.defn(name="build_queue_try_acquire")
    async def queue_try_acquire(self, build_id: str) -> int:
        r = self._redis()
        try:
            value = await r.eval(_ACQUIRE, 2, QUEUE_KEY, RUNNING_KEY, build_id, self._slots(),
                                 int(time.time() * 1000), STALE_MS)
        finally:
            await r.aclose()
        position = int(value)
        if position < 0:  # not in line (expired); enter again at the back
            await self.queue_enter(build_id, int(time.time() * 1000))
            return await self.queue_try_acquire(build_id)
        return position

    @activity.defn(name="build_queue_release")
    async def queue_release(self, build_id: str) -> None:
        r = self._redis()
        try:
            await r.zrem(QUEUE_KEY, build_id)
            await r.zrem(RUNNING_KEY, build_id)
        finally:
            await r.aclose()

    def all(self) -> list[Callable[..., Any]]:
        return [self.prepare_checkout, self.write_context, self.run_pi, self.check_diff, self.run_tests,
                self.write_failures, self.commit_and_push, self.open_pr, self.read_notes, self.emit,
                self.check_budget, self.queue_enter, self.queue_try_acquire, self.queue_release]


_default = BuildActivities()
ACTIVITIES: list[Callable[..., Any]] = _default.all()
