"""Request service: the only way to change a request (spec B, B1).

The service records the user's action; the workflow decides the outcome. Each action:
idempotency check (Redis `SET NX EX`, PostgreSQL `idempotency_keys` as fallback) -> membership and approver
checks (B12a) -> quick pre-check against the workflow's `state()` query -> one transaction writing the action event
with `signal_status = 'pending'` -> signal -> `signal_status = 'sent'` -> publish. Approvals and ticket edits wait up
to 3 seconds for the workflow's outcome. A reconciler re-sends signals that stayed pending.

`get_request_view` is the single read model (B.C7 RequestDetail) for the API and Slack.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from ulid import ULID

from actron.config import get_settings
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import approvals as approvals_mod
from actron.flow import budget as budget_mod
from actron.flow.events import (
    Event,
    emit,
    insert_event,
    iso,
    mark_signal_sent,
    publish,
    redis_client,
)
from actron.flow.states import (
    FINAL_STATES,
    NEEDS_YOU,
    PIPELINE_STEP,
    State,
    allowed_signals,
    signal_valid,
)
from actron.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "ActionResult", "Actor", "Conflict", "Forbidden", "Invalid", "NotFound", "ServiceError", "SlackRef",
    "TemporalGateway", "WorkflowGateway", "answer", "approve", "cancel", "close_pr", "create_request",
    "edit_ticket", "emit", "feedback", "get_gateway", "get_request_view", "list_requests", "raise_budget",
    "reconcile_once", "retry", "set_gateway",
]

IDEM_TTL_S = 86400
OUTCOME_WAIT_S = 3.0
PRECHECK_TIMEOUT_S = 1.0
REQUEST_TASK_QUEUE = "request"
ActionResult = dict[str, Any]


# Errors (mapped to HTTP by the API and to plain messages by Slack)
class ServiceError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFound(ServiceError):
    status = 404
    code = "not_found"


class Forbidden(ServiceError):
    status = 403
    code = "forbidden"


class Conflict(ServiceError):
    status = 409
    code = "conflict"


class Invalid(ServiceError):
    status = 422
    code = "invalid"


@dataclass(frozen=True)
class Actor:
    """Who acts. Slack actors carry `slack_user_id`; UI actors carry the Actron `user_id`."""

    user_id: str | None = None
    slack_user_id: str | None = None
    surface: Literal["slack", "ui"] = "ui"
    name: str | None = None
    team_id: str | None = None

    def payload(self, user_id: uuid.UUID | None = None, name: str | None = None) -> dict[str, Any]:
        return {
            "userId": str(user_id) if user_id else self.user_id,
            "slackUserId": self.slack_user_id,
            "surface": self.surface,
            "name": name or self.name,
        }


@dataclass(frozen=True)
class SlackRef:
    channel: str
    thread_ts: str
    permalink: str | None = None


# Workflow gateway (Temporal in production; a fake in tests)
class WorkflowGateway(Protocol):
    async def start_request(self, ws: str, request_id: str, inp: dict[str, Any]) -> None: ...
    async def signal(self, request_id: str, name: str, payload: dict[str, Any]) -> None: ...
    async def query_state(self, request_id: str) -> dict[str, Any] | None: ...
    async def start_source_sync(self, ws: str, source: str, mode: str) -> str: ...
    async def ensure_schedule(self, ws: str, source: str) -> None: ...
    async def trigger_schedule(self, ws: str, source: str) -> None: ...
    async def pause_schedule(self, ws: str, source: str) -> None: ...
    async def delete_schedule(self, ws: str, source: str) -> None: ...


SYNC_INTERVALS = {"code": timedelta(minutes=15), "github": timedelta(minutes=5), "linear": timedelta(minutes=5),
                  "slack": timedelta(minutes=10)}


@dataclass
class TemporalGateway:
    """Talks to Temporal with one client per event loop."""

    _clients: dict[int, Any] = field(default_factory=dict)
    fixed_client: Any = None

    async def client(self) -> Any:
        if self.fixed_client is not None:
            return self.fixed_client
        from temporalio.client import Client
        from temporalio.contrib.pydantic import pydantic_data_converter

        loop_id = id(asyncio.get_running_loop())
        cl = self._clients.get(loop_id)
        if cl is None:
            s = get_settings()
            cl = await asyncio.wait_for(
                Client.connect(s.TEMPORAL_ADDRESS, namespace=s.TEMPORAL_NAMESPACE, data_converter=pydantic_data_converter),
                timeout=5,
            )
            self._clients = {loop_id: cl}
        return cl

    async def start_request(self, ws: str, request_id: str, inp: dict[str, Any]) -> None:
        cl = await self.client()
        await cl.start_workflow("RequestWorkflow", inp, id=f"request:{request_id}", task_queue=REQUEST_TASK_QUEUE)

    async def signal(self, request_id: str, name: str, payload: dict[str, Any]) -> None:
        cl = await self.client()
        await cl.get_workflow_handle(f"request:{request_id}").signal(name, payload)

    async def query_state(self, request_id: str) -> dict[str, Any] | None:
        cl = await self.client()
        result = await cl.get_workflow_handle(f"request:{request_id}").query("state")
        return dict(result) if isinstance(result, dict) else None

    async def start_source_sync(self, ws: str, source: str, mode: str) -> str:
        cl = await self.client()
        wf_id = f"sync:{ws}:{source}:{mode}:{ULID()}"
        await cl.start_workflow("SourceSyncWorkflow", args=[ws, source, mode], id=wf_id, task_queue="ingest")
        return wf_id

    async def ensure_schedule(self, ws: str, source: str) -> None:
        from actron.workflows.schedules import ensure_schedule

        if source not in SYNC_INTERVALS:
            return
        cl = await self.client()
        await ensure_schedule(cl, ws, source, SYNC_INTERVALS[source], "SourceSyncWorkflow",
                              [ws, source, "incremental"], task_queue="ingest")

    async def trigger_schedule(self, ws: str, source: str) -> None:
        from actron.workflows.schedules import schedule_id, trigger_schedule

        cl = await self.client()
        await trigger_schedule(cl, schedule_id(ws, source))

    async def pause_schedule(self, ws: str, source: str) -> None:
        from actron.workflows.schedules import pause_schedule, schedule_id

        cl = await self.client()
        await pause_schedule(cl, schedule_id(ws, source), note="source disconnected")

    async def delete_schedule(self, ws: str, source: str) -> None:
        from actron.workflows.schedules import delete_schedule, schedule_id

        cl = await self.client()
        await delete_schedule(cl, schedule_id(ws, source))


_gateway: WorkflowGateway | None = None


def get_gateway() -> WorkflowGateway:
    global _gateway
    if _gateway is None:
        _gateway = TemporalGateway()
    return _gateway


def set_gateway(gateway: WorkflowGateway | None) -> None:
    global _gateway
    _gateway = gateway


# Idempotency
_PENDING = "__pending__"


def _pg_idem_get(key: str) -> dict[str, Any] | None:
    with session_scope() as s:
        row = s.get(m.IdempotencyKey, key)
        return dict(row.response) if row is not None and row.response is not None else None


def _pg_idem_put(key: str, response: dict[str, Any]) -> None:
    with session_scope() as s:
        s.execute(
            pg_insert(m.IdempotencyKey).values(key=key, response=response)
            .on_conflict_do_update(index_elements=["key"], set_={"response": response})
        )


async def idempotent(ws: str, key: str | None, fn: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Run `fn` once per key. A repeat returns the stored result (or raises the stored error)."""
    if not key:
        return await fn()
    k = f"idem:{ws}:{key}"
    use_redis = True
    try:
        client = redis_client()
        got = await client.set(k, _PENDING, nx=True, ex=IDEM_TTL_S)
    except Exception as exc:
        log.warning("redis unavailable for idempotency; using postgres", extra={"error": type(exc).__name__})
        use_redis = False
        got = None
    if use_redis and not got:
        stored = await _wait_stored(client, k)
        return _replay(stored)
    if not use_redis:
        prior = await asyncio.to_thread(_pg_idem_get, k)
        if prior is not None:
            return _replay(prior)
    try:
        result = await fn()
        stored_value: dict[str, Any] = {"ok": result}
    except ServiceError as exc:
        stored_value = {"error": {"status": exc.status, "code": exc.code, "message": exc.message, "details": exc.details}}
        await _store_idem(k, stored_value, use_redis)
        raise
    except BaseException:
        if use_redis:
            with contextlib.suppress(Exception):
                await client.delete(k)
        raise
    await _store_idem(k, stored_value, use_redis)
    return result


async def _store_idem(k: str, value: dict[str, Any], use_redis: bool) -> None:
    if use_redis:
        with contextlib.suppress(Exception):
            await redis_client().set(k, json.dumps(value), ex=IDEM_TTL_S)
    try:
        await asyncio.to_thread(_pg_idem_put, k, value)
    except Exception as exc:
        log.warning("idempotency backup write failed", extra={"error": type(exc).__name__})


async def _wait_stored(client: Any, k: str, timeout_s: float = 10.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        raw = await client.get(k)
        if raw and raw != _PENDING:
            out: dict[str, Any] = json.loads(raw)
            return out
        if raw is None:
            prior = await asyncio.to_thread(_pg_idem_get, k)
            if prior is not None:
                return prior
        if asyncio.get_running_loop().time() > deadline:
            raise Conflict("The same action is still being processed.", code="in_progress")
        await asyncio.sleep(0.05)


def _replay(stored: dict[str, Any]) -> dict[str, Any]:
    if "error" in stored:
        err = stored["error"]
        cls = {403: Forbidden, 404: NotFound, 409: Conflict, 422: Invalid}.get(int(err.get("status", 400)), ServiceError)
        raise cls(err.get("message", ""), code=err.get("code"), details=err.get("details"))
    out: dict[str, Any] = stored.get("ok", stored)
    return out


# Actors and members
def resolve_actor(session: Session, ws: str, actor: Actor) -> m.User:
    """Find the acting user; Slack users are created on first contact and join the workspace (B11)."""
    wsrow = session.get(m.Workspace, ws)
    if wsrow is None:
        raise NotFound(f"Workspace {ws} does not exist.", code="workspace_not_found")
    user: m.User | None = None
    if actor.user_id:
        try:
            user = session.get(m.User, uuid.UUID(actor.user_id))
        except ValueError:
            user = None
    elif actor.slack_user_id:
        # First contact from Slack and UI at the same time: insert-or-ignore, then read.
        session.execute(pg_insert(m.User).values(id=uuid.uuid4(), slack_user_id=actor.slack_user_id,
                                                 name=actor.name or actor.slack_user_id)
                        .on_conflict_do_nothing(index_elements=["slack_user_id"]))
        user = session.scalar(select(m.User).where(m.User.slack_user_id == actor.slack_user_id))
        team_ok = actor.team_id is None or wsrow.slack_team_id in (None, actor.team_id)
        if team_ok and user is not None:
            session.execute(pg_insert(m.Membership).values(user_id=user.id, workspace_id=ws, role="member")
                            .on_conflict_do_nothing())
    if user is None or not approvals_mod.is_member(session, ws, user.id):
        raise Forbidden("You are not a member of this workspace.", code="not_a_member")
    return user


def _load_request(session: Session, ws: str, request_id: str, *, lock: bool = False) -> m.Request:
    q = select(m.Request).where(m.Request.id == request_id, m.Request.workspace_id == ws)
    if lock:
        q = q.with_for_update()
    req = session.scalar(q)
    if req is None:
        raise NotFound(f"Request {request_id} was not found.")
    return req


# Create
def _title(text_: str) -> str:
    first = re.split(r"(?<=[.!?])\s|\n", text_.strip(), maxsplit=1)[0].strip()
    return (first[:77] + "...") if len(first) > 80 else first


async def _classify(text_: str, ws: str, request_id: str) -> str:
    try:
        from actron.models import classify_request
    except Exception:
        return "feature"
    try:
        j = await asyncio.wait_for(classify_request(text_, ws=ws, request_id=request_id), timeout=15)
        answer_ = str(getattr(j, "answer", "feature"))
        return answer_ if answer_ in ("feature", "bug", "question") else "feature"
    except Exception as exc:
        log.warning("classify_request failed; using feature", extra={"error": type(exc).__name__})
        return "feature"


def _insert_request(ws: str, request_id: str, kind: str, title: str, text_: str, actor: Actor, source: str,
                    slack: SlackRef | None) -> Event:
    with session_scope() as s:
        user = resolve_actor(s, ws, actor)
        req = m.Request(
            id=request_id, workspace_id=ws, kind=kind, title=title, text=text_, state=State.INVESTIGATING.value,
            source=source, requester_user_id=user.id, slack_channel=slack.channel if slack else None,
            slack_thread_ts=slack.thread_ts if slack else None,
            temporal_workflow_id=f"request:{request_id}",
            data={"workflowStarted": False, "slackPermalink": slack.permalink if slack else None},
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        s.add(req)
        s.flush()
        payload: dict[str, Any] = {
            "kind": kind, "title": title, "text": text_,
            "requester": {"personId": None, "userId": str(user.id), "name": user.name},
            "source": source,
        }
        if slack:
            payload["slack"] = {"channel": slack.channel, "threadTs": slack.thread_ts}
        actor_kind = "slack" if source == "slack" else "person"
        return insert_event(s, ws, request_id, "request.created", payload, actor=actor_kind,
                            surface="slack" if source == "slack" else "ui")


def mirror_request_node(ws: str, request_id: str) -> None:
    """Write the thin `Request` node (and REQUESTED_BY when the person is known). Best effort."""
    from actron.graph import ids
    from actron.graph.store import store_for

    try:
        with session_scope() as s:
            req = s.get(m.Request, request_id)
            if req is None:
                return
            row = {"id": ids.request(req.id), "kind": req.kind, "title": req.title, "text": req.text,
                   "state": req.state, "outcome": req.outcome, "createdAt": req.created_at, "closedAt": req.closed_at}
        store_for(ws).upsert_nodes("Request", [row], source="actron")
    except Exception as exc:
        log.warning("request graph mirror failed", extra={"request_id": request_id, "error": type(exc).__name__})


async def create_request(
    ws: str,
    *,
    text: str,
    actor: Actor,
    source: Literal["slack", "ui"],
    slack: SlackRef | None = None,
    kind_hint: str | None = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    if not 3 <= len(text) <= 4000:
        raise Invalid("The request text must be between 3 and 4,000 characters.", code="invalid_text")
    request_id = f"req_{ULID()}"
    kind = kind_hint if kind_hint in ("feature", "bug", "question") else await _classify(text, ws, request_id)
    ev = await asyncio.to_thread(_insert_request, ws, request_id, kind, _title(text), text, actor, source, slack)
    await publish(ev)
    from actron.flow.events import notify_slack

    await notify_slack(ws, ev)
    await asyncio.to_thread(mirror_request_node, ws, request_id)
    await _start_workflow(ws, request_id)
    return await get_request_view(ws, request_id)


def workflow_input(req: m.Request) -> dict[str, Any]:
    return {"ws": req.workspace_id, "requestId": req.id, "kind": req.kind, "title": req.title, "text": req.text,
            "source": req.source}


async def _start_workflow(ws: str, request_id: str) -> bool:
    def load() -> dict[str, Any]:
        with session_scope() as s:
            return workflow_input(_load_request(s, ws, request_id))

    inp = await asyncio.to_thread(load)
    try:
        await get_gateway().start_request(ws, request_id, inp)
    except Exception as exc:
        if "already" not in str(exc).lower():
            log.warning("workflow start failed; reconciler will retry", extra={"request_id": request_id,
                                                                                 "error": type(exc).__name__})
            return False
    await asyncio.to_thread(_set_data, request_id, {"workflowStarted": True})
    return True


def _set_data(request_id: str, values: dict[str, Any]) -> None:
    with session_scope() as s:
        req = s.get(m.Request, request_id)
        if req is not None:
            req.data = {**(req.data or {}), **values}


# Actions
@dataclass
class _Prepared:
    state: str
    user_id: uuid.UUID
    name: str
    refused: str | None = None
    refused_event_id: int | None = None


def _prepare(ws: str, request_id: str, actor: Actor, approval: tuple[str, str] | None) -> _Prepared:
    with session_scope() as s:
        user = resolve_actor(s, ws, actor)
        req = _load_request(s, ws, request_id)
        prep = _Prepared(state=req.state, user_id=user.id, name=user.name)
        if approval is not None and not approvals_mod.is_approver(s, ws, req, user.id, actor.slack_user_id):
            kind, target = approval
            approvals_mod.record(s, request_id, kind=kind, target=target, status="refused", reason="not_an_approver",
                                 actor=actor.payload(user.id, user.name))
            ev = insert_event(s, ws, request_id, "approval.refused", {
                "kind": kind, "target": target, "reason": "not_an_approver",
                "by": {"personId": None, "userId": str(user.id), "name": user.name}, "surface": actor.surface,
            }, actor="person" if actor.surface == "ui" else "slack", surface=actor.surface)
            prep.refused = "not_an_approver"
            prep.refused_event_id = ev.id
        return prep


def _insert_action(ws: str, request_id: str, event_type: str, payload: dict[str, Any], actor: Actor,
                   key: str) -> Event:
    with session_scope() as s:
        _load_request(s, ws, request_id, lock=True)
        return insert_event(s, ws, request_id, event_type, payload,
                            actor="person" if actor.surface == "ui" else "slack", surface=actor.surface,
                            signal_status="pending", idempotency_key=key)


async def _current_state(request_id: str, mirror: str) -> str:
    """Pre-check uses the workflow's state() query; the PostgreSQL mirror is the fallback."""
    try:
        view = await asyncio.wait_for(get_gateway().query_state(request_id), timeout=PRECHECK_TIMEOUT_S)
        if view and view.get("state"):
            return str(view["state"])
    except Exception:
        pass
    return mirror


def _result(status: str, reason: str | None, event_id: int | None, state: str, **extra: Any) -> ActionResult:
    return {"status": status, "reason": reason, "eventId": event_id, "state": state, **extra}


async def _act(
    ws: str,
    request_id: str,
    *,
    signal: str,
    event_type: str,
    payload: dict[str, Any],
    actor: Actor,
    key: str | None,
    approval: tuple[str, str] | None = None,
    wait: bool = False,
) -> ActionResult:
    idem = key or str(uuid.uuid4())

    async def run() -> ActionResult:
        prep = await asyncio.to_thread(_prepare, ws, request_id, actor, approval)
        if prep.refused:
            if prep.refused_event_id:
                from actron.flow.events import publish_stored

                await publish_stored(ws, [prep.refused_event_id])
            raise Forbidden("You are not allowed to approve this request.", code=prep.refused)
        state = await _current_state(request_id, prep.state)
        if not signal_valid(signal, state):
            raise Conflict(f"This action is not available while the request is {state}.", code="invalid_transition",
                           details={"state": state, "action": signal})
        actor_payload = actor.payload(prep.user_id, prep.name)
        signal_payload = {**payload, "actor": actor_payload, "idempotencyKey": idem}
        ev_payload = {**payload, "by": {"personId": None, "userId": str(prep.user_id), "name": prep.name},
                      "surface": actor.surface, "idempotencyKey": idem, "signal": signal,
                      "signalPayload": signal_payload}
        ev = await asyncio.to_thread(_insert_action, ws, request_id, event_type, ev_payload, actor, idem)
        signal_payload["eventId"] = ev.id
        try:
            await get_gateway().signal(request_id, signal, signal_payload)
            await asyncio.to_thread(mark_signal_sent, ev.id)
        except Exception as exc:
            log.warning("signal failed; reconciler will resend", extra={"request_id": request_id, "signal": signal,
                                                                         "error": type(exc).__name__})
        await publish(ev)
        if not wait:
            return _result("accepted", None, ev.id, state)
        outcome = await approvals_mod.wait_outcome(request_id, idem, OUTCOME_WAIT_S)
        if outcome is None:
            return _result("pending", None, ev.id, state)
        return _result(str(outcome.get("status", "accepted")), outcome.get("reason"), outcome.get("eventId", ev.id),
                       str(outcome.get("state", state)), **{k: v for k, v in outcome.items()
                                                            if k not in ("status", "reason", "eventId", "state")})

    return await idempotent(ws, idem, run)


def _validate_answer(ws: str, request_id: str, question_id: str, value: str) -> None:
    from actron.flow import questions as qmod

    with session_scope() as s:
        data = dict(_load_request(s, ws, request_id).data or {})
    questions = list(data.get("questions") or [])
    if not questions:
        return
    try:
        qmod.apply_answer(questions, {}, question_id, value, branch_names=list(data.get("branchNames") or []))
    except qmod.InvalidAnswer as exc:
        raise Invalid(str(exc), code="invalid_answer") from None


async def answer(ws: str, request_id: str, question_id: str, value: str, actor: Actor,
                 idempotency_key: str | None) -> ActionResult:
    if not question_id or not str(value).strip():
        raise Invalid("questionId and value are required.", code="invalid_answer")
    await asyncio.to_thread(_validate_answer, ws, request_id, question_id, str(value).strip())
    return await _act(ws, request_id, signal="answer", event_type="answer.received",
                      payload={"questionId": question_id, "value": str(value).strip()}, actor=actor,
                      key=idempotency_key)


async def edit_ticket(ws: str, request_id: str, content: dict[str, Any], actor: Actor,
                      idempotency_key: str | None) -> ActionResult:
    if not isinstance(content, dict) or not str(content.get("objective", "")).strip():
        raise Invalid("The ticket needs an objective.", code="invalid_ticket")
    return await _act(ws, request_id, signal="edit_ticket", event_type="ticket.edit_requested",
                      payload={"content": content}, actor=actor, key=idempotency_key, wait=True)


async def approve(ws: str, request_id: str, kind: Literal["ticket", "pr"], target: str, actor: Actor,
                  idempotency_key: str | None) -> ActionResult:
    if kind not in ("ticket", "pr") or not target:
        raise Invalid("Approvals need kind and the revision hash or head SHA.", code="invalid_approval")
    signal = "approve_ticket" if kind == "ticket" else "approve_pr"
    payload = {"revisionHash": target} if kind == "ticket" else {"headSha": target}
    return await _act(ws, request_id, signal=signal, event_type="approval.requested",
                      payload={"kind": kind, "target": target, **payload}, actor=actor, key=idempotency_key,
                      approval=(kind, target), wait=True)


async def feedback(ws: str, request_id: str, text_: str, head_sha: str, actor: Actor,
                   idempotency_key: str | None) -> ActionResult:
    if not (text_ or "").strip():
        raise Invalid("Feedback text is required.", code="invalid_feedback")
    return await _act(ws, request_id, signal="pr_feedback", event_type="review.feedback",
                      payload={"kind": None, "text": text_.strip(), "headSha": head_sha}, actor=actor,
                      key=idempotency_key)


async def cancel(ws: str, request_id: str, reason: str | None, actor: Actor, idempotency_key: str | None) -> ActionResult:
    return await _act(ws, request_id, signal="cancel", event_type="request.cancel_requested",
                      payload={"reason": reason or "cancelled"}, actor=actor, key=idempotency_key)


async def retry(ws: str, request_id: str, actor: Actor, idempotency_key: str | None) -> ActionResult:
    return await _act(ws, request_id, signal="retry", event_type="request.retry_requested", payload={},
                      actor=actor, key=idempotency_key)


async def close_pr(ws: str, request_id: str, reason: str | None, actor: Actor,
                   idempotency_key: str | None) -> ActionResult:
    return await _act(ws, request_id, signal="close_pr", event_type="pr.close_requested",
                      payload={"reason": reason or "closed"}, actor=actor, key=idempotency_key)


async def raise_budget(ws: str, cap_usd: float, actor: Actor, idempotency_key: str | None) -> ActionResult:
    """Set the daily cap and signal every build waiting on the budget (workspace-level)."""
    if cap_usd < 0:
        raise Invalid("The cap must be zero or more.", code="invalid_cap")

    async def run() -> ActionResult:
        def update_cap() -> list[str]:
            with session_scope() as s:
                user = resolve_actor(s, ws, actor)
                membership = s.get(m.Membership, (user.id, ws))
                if membership is None or membership.role != "owner":
                    wsrow = s.get(m.Workspace, ws)
                    approvers = set((wsrow.settings or {}).get("approvers") or []) if wsrow else set()
                    if not (user.slack_user_id and user.slack_user_id in approvers):
                        raise Forbidden("Only the workspace owner or an approver can change the budget.",
                                        code="not_an_approver")
                budget_mod.set_cap(s, ws, cap_usd)
                rows = s.scalars(select(m.Request.id).where(
                    m.Request.workspace_id == ws, m.Request.state == State.BUILDING.value)).all()
                return list(rows)

        waiting = await asyncio.to_thread(update_cap)
        sent = 0
        for rid in waiting:
            try:
                await get_gateway().signal(rid, "budget_raised", {"capUsd": cap_usd, "actor": actor.payload(),
                                                                  "idempotencyKey": f"budget:{idempotency_key}:{rid}"})
                sent += 1
            except Exception as exc:
                log.warning("budget_raised signal failed", extra={"request_id": rid, "error": type(exc).__name__})
        return {"status": "accepted", "reason": None, "eventId": None, "state": None, "signalled": sent}

    return await idempotent(ws, idempotency_key, run)


# Reconciler
def _pending_signals(older_than: datetime, limit: int = 100) -> list[tuple[int, str, str, dict[str, Any]]]:
    with session_scope() as s:
        rows = s.execute(
            select(m.Event.id, m.Event.workspace_id, m.Event.request_id, m.Event.payload)
            .where(m.Event.signal_status == "pending", m.Event.at < older_than)
            .order_by(m.Event.id).limit(limit)
        ).all()
        return [(r[0], r[1], r[2], dict(r[3] or {})) for r in rows if r[2]]


def _unstarted(older_than: datetime, limit: int = 50) -> list[tuple[str, str]]:
    with session_scope() as s:
        rows = s.execute(
            select(m.Request.workspace_id, m.Request.id).where(
                m.Request.data["workflowStarted"].astext == "false", m.Request.created_at < older_than,
                m.Request.state.notin_([st.value for st in FINAL_STATES]),
            ).limit(limit)
        ).all()
        return [(r[0], r[1]) for r in rows]


async def reconcile_once(older_than_s: float = 5.0) -> int:
    """Re-send signals that stayed `pending` and start workflows that never started. Returns how many it fixed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_s)
    fixed = 0
    for event_id, _ws, request_id, payload in await asyncio.to_thread(_pending_signals, cutoff):
        name = payload.get("signal")
        sp = dict(payload.get("signalPayload") or {})
        if not name:
            await asyncio.to_thread(mark_signal_sent, event_id)
            continue
        sp["eventId"] = event_id
        try:
            await get_gateway().signal(request_id, str(name), sp)
            await asyncio.to_thread(mark_signal_sent, event_id)
            fixed += 1
        except Exception as exc:
            log.warning("reconciler signal failed", extra={"request_id": request_id, "error": type(exc).__name__})
    for ws, request_id in await asyncio.to_thread(_unstarted, cutoff):
        if await _start_workflow(ws, request_id):
            fixed += 1
    return fixed


async def reconciler_loop(interval_s: float = 30.0, stop: asyncio.Event | None = None) -> None:
    while stop is None or not stop.is_set():
        try:
            await reconcile_once()
        except Exception as exc:
            log.warning("reconciler pass failed", extra={"error": type(exc).__name__})
        try:
            if stop is not None:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            else:
                await asyncio.sleep(interval_s)
        except TimeoutError:
            pass


# Read model (B.C7)
TIER_HIGH = 0.8
TIER_MEDIUM = 0.6
INFORMATIONAL_TYPES = {"notification.sent", "tool.result"}


def tier_for(confidence: float, flagged: bool = False) -> str:
    if flagged:
        return "POSSIBLE"
    if confidence >= TIER_HIGH:
        return "HIGH"
    if confidence >= TIER_MEDIUM:
        return "MEDIUM"
    return "POSSIBLE"


def person_ref(user: m.User | None, fallback_name: str = "Someone") -> dict[str, Any]:
    if user is None:
        return {"personId": None, "userId": None, "name": fallback_name, "avatarUrl": None}
    return {"personId": None, "userId": str(user.id), "name": user.name or fallback_name, "avatarUrl": user.avatar_url}


def _num_word(n: int) -> str:
    words = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
    return words[n] if 0 <= n < len(words) else str(n)


def sentence_for(ev_type: str, payload: dict[str, Any]) -> str:
    """One plain sentence for an event (Home rows, inbox, Slack status)."""
    p = payload
    by = (p.get("by") or {}).get("name") if isinstance(p.get("by"), dict) else p.get("by")
    table: dict[str, str] = {
        "request.created": f"Request created from {'Slack' if p.get('source') == 'slack' else 'the web app'}.",
        "investigation.started": "Investigation started.",
        "tool.called": f"Queried the graph: {p.get('tool', 'tool')}.",
        "tool.result": str(p.get("summary") or "Graph query finished."),
        "evidence.found": "Found evidence in the team's history.",
        "investigation.completed": str(p.get("summary") or "Investigation finished."),
        "question.asked": f"Asked: {p.get('text', 'a question')}",
        "answer.received": f"{by or 'Someone'} answered a question.",
        "ticket.revised": f"Ticket v{p.get('n')} saved.",
        "ticket.edit_requested": f"{by or 'Someone'} edited the ticket.",
        "ticket.synced": (f"Ticket {p.get('identifier')} synced to Linear." if p.get("identifier")
                          else "Ticket saved. Linear is not connected."),
        "approval.requested": f"{by or 'Someone'} asked to approve.",
        "approval.recorded": f"Approved by {by or 'someone'}.",
        "approval.refused": f"Approval refused: {str(p.get('reason', '')).replace('_', ' ')}.",
        "handoff.created": f"Handed {p.get('evidenceCount', 0)} pieces of evidence to the build.",
        "build.queued": f"Build queued, position {p.get('position')}.",
        "build.started": f"Build started on {p.get('branch', 'a new branch')}.",
        "build.step": str(p.get("text") or "Build step."),
        "tests.result": f"{p.get('passed', 0)} tests passed, {p.get('failed', 0)} failed.",
        "build.repair": f"Repair attempt {p.get('attempt')}.",
        "build.failed": f"Build failed: {p.get('reason', 'unknown reason')}.",
        "build.passed": "Build passed.",
        "pr.opened": f"PR #{p.get('number')} opened.",
        "pr.updated": f"PR #{p.get('number')} updated.",
        "review.feedback": f"{by or 'Someone'} requested changes.",
        "pr.approved": "PR approved.",
        "writeback.done": "Memory updated.",
        "request.cancelled": "Request cancelled.",
        "request.cancel_requested": f"{by or 'Someone'} asked to cancel.",
        "request.retry_requested": f"{by or 'Someone'} asked to retry.",
        "request.done": "Done.",
        "answer.ready": "Answer ready.",
        "memory.refreshing": "Updating memory with the latest merged code.",
        "memory.refreshed": "Memory is up to date with the merged code.",
        "memory.unverified": "Could not check for newer code. Using the memory as it is.",
        "budget.reached": "Daily model budget reached.",
        "request.state_changed": f"Now {p.get('to', '')}.",
        "judgment.made": f"Judged {p.get('count', '')} {p.get('what', 'items')}.".replace("  ", " "),
    }
    return table.get(ev_type, ev_type.replace(".", " ").capitalize() + ".")


def _headline(state: str, ctx: dict[str, Any]) -> tuple[str, str]:
    """Situation sentence and purpose line per state (PROMPT 8.8 D copy)."""
    label = ctx.get("label")
    decisions = int(ctx.get("decisionCount") or 0)
    if state == State.INVESTIGATING:
        if ctx.get("memoryRefreshing"):
            return "Updating memory with the latest merged code.", "Actron checks new code before investigating."
        n = int(ctx.get("toolCalls") or 0)
        return (f"Investigating. {n} graph queries so far.",
                "Actron is checking what your team already decided and built.")
    finding = {
        "conflict": f"{_num_word(decisions)} earlier decision{'s' if decisions != 1 else ''} affect this request."
        if decisions else "An earlier decision affects this request.",
        "possible_conflict": "Something in your history may affect this request.",
        "nothing_found": "Nothing in your history touches this. Safe to continue.",
        "clear": "Nothing here conflicts with this request.",
    }.get(str(label), "")
    if state == State.NEEDS_YOUR_INPUT:
        pending = int(ctx.get("pendingQuestions") or 0)
        head = finding or "Actron has a question before drafting the ticket."
        return head, f"Answer {pending} question{'s' if pending != 1 else ''} to continue."
    if state == State.TICKET_READY:
        return finding or "Drafting the ticket.", "The ticket is being written and synced."
    if state == State.AWAITING_APPROVAL:
        rev_n = ctx.get("revisionN")
        return (f"Ticket v{rev_n} is ready for your approval." if rev_n else "The ticket is ready for your approval.",
                "Approve to start the build, or edit the ticket first.")
    if state == State.BUILDING:
        if ctx.get("waitingBudget"):
            return ("Daily model budget reached.",
                    "The build waits until the cap is raised or the next day starts.")
        tests = ctx.get("tests")
        if tests:
            return (f"Building. {tests['passed']} of {tests['total']} tests passed.",
                    "Pi is building the change in an isolated container.")
        return "Building.", "Pi is building the change in an isolated container."
    if state == State.NEEDS_ATTENTION:
        reason = str(ctx.get("attentionReason") or "")
        if ctx.get("failedStep") == "build":
            attempts = int(ctx.get("attempts") or 0)
            head = ("The build failed twice. Here is why." if attempts >= 2
                    else "The build stopped. Here is why.")
        elif reason == "memory_stale":
            head = "Memory could not be updated in time."
        else:
            head = "The investigation did not finish. Here is why."
        return head, "Retry, edit the ticket, or cancel."
    if state == State.CHANGES_REQUESTED:
        return "Changes requested. Building a new revision.", "Pi is applying the review feedback."
    if state == State.PR_READY:
        num = ctx.get("prNumber")
        return (f"PR #{num} is ready for review." if num else "The PR is ready for review.",
                "Approve the PR, request changes, or close it.")
    if state == State.DONE:
        if ctx.get("outcome") == "answered":
            return "Answered. The sources are listed with the answer.", "Ask a follow-up any time."
        return "Done. Merged scope recorded in memory.", "The graph now includes this change."
    if ctx.get("outcome") == "closed":
        return "Closed. The PR was closed without merging.", "Nothing was merged."
    return "Cancelled.", "Nothing more will happen on this request."


def _evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in items:
        conf = float(e.get("confidence") or 0.0)
        src = e.get("source") or {}
        out.append({
            "evidenceId": str(e.get("evidenceId") or e.get("id") or e.get("nodeId")),
            "role": e.get("role", "impact"),
            "nodeId": e.get("nodeId", ""),
            "nodeType": e.get("nodeType", ""),
            "title": e.get("title") or e.get("label") or e.get("nodeId", ""),
            "quote": e.get("quote"),
            "source": {"type": src.get("type", ""), "id": src.get("id", e.get("nodeId", "")), "url": src.get("url"),
                       "author": src.get("author"), "at": src.get("at")},
            "confidence": conf,
            "tier": e.get("tier") or tier_for(conf, bool(e.get("flag"))),
            "path": list(e.get("path") or []),
        })
    return out


def _build_view(row: m.BuildRun, queue_position: int | None) -> dict[str, Any]:
    status = row.status if row.status in ("queued", "running", "passed", "failed", "stopped", "waiting_budget") \
        else "running"
    return {
        "id": row.id, "status": status, "queuePosition": queue_position if status == "queued" else None,
        "branch": row.branch, "baseSha": row.base_sha, "headSha": row.head_sha, "testsPassed": row.tests_passed,
        "testsFailed": row.tests_failed, "attempts": row.attempts, "startedAt": iso(row.started_at),
        "finishedAt": iso(row.finished_at), "stopReason": row.stop_reason,
        "tokens": {"input": row.input_tokens, "output": row.output_tokens}, "costUsd": round(float(row.cost_usd), 4),
        "report": row.report,
    }


def revision_view(row: m.TicketRevision) -> dict[str, Any]:
    from actron.flow.ticket import content_only

    return {"n": row.n, "hash": row.content_hash, "content": content_only(dict(row.content)),
            "createdBy": row.created_by, "createdAt": iso(row.created_at), "linear": row.linear,
            "externalEdit": bool(row.external_edit)}


def _questions_view(data: dict[str, Any], users: dict[str, m.User]) -> list[dict[str, Any]]:
    out = []
    answers = data.get("answers") or {}
    for q in data.get("questions") or []:
        a = answers.get(q.get("questionId"))
        ans = None
        if a:
            by_user = users.get(str(a.get("userId"))) if a.get("userId") else None
            ans = {"value": a.get("value"), "by": person_ref(by_user, a.get("name") or "Someone"),
                   "surface": a.get("surface", "ui"), "at": a.get("at")}
        out.append({"questionId": q.get("questionId"), "text": q.get("text", ""),
                    "kind": q.get("kind", "choice" if q.get("options") else "text"),
                    "options": list(q.get("options") or []), "evidenceIds": list(q.get("evidenceIds") or []),
                    "required": bool(q.get("required", True)), "answer": ans})
    return out


def _summary(req: m.Request, requester: m.User | None, last: m.Event | None, ctx: dict[str, Any]) -> dict[str, Any]:
    state = req.state
    step = PIPELINE_STEP[State(state)]
    data = req.data or {}
    if state == State.NEEDS_ATTENTION:
        step = 5 if data.get("failedStep") == "build" else 1
    elif state == State.CANCELLED:
        step = int(data.get("lastStep") or 1)
    return {
        "id": req.id, "title": req.title, "kind": req.kind, "state": state, "label": req.label,
        "requester": person_ref(requester), "source": req.source if req.source in ("slack", "ui") else "ui",
        "createdAt": iso(req.created_at), "updatedAt": iso(req.updated_at),
        "lastEvent": ({"type": last.type, "sentence": sentence_for(last.type, dict(last.payload or {})),
                       "at": iso(last.at)} if last else None),
        "pipelineStep": step, "needsYou": State(state) in NEEDS_YOU,
    }


def _last_events(s: Session, ids_: list[str]) -> dict[str, m.Event]:
    if not ids_:
        return {}
    rows = s.execute(
        text("SELECT DISTINCT ON (request_id) id FROM events WHERE request_id = ANY(:ids) "
             "AND type NOT IN ('notification.sent', 'tool.result') ORDER BY request_id, seq DESC"),
        {"ids": ids_},
    ).scalars().all()
    evs = s.scalars(select(m.Event).where(m.Event.id.in_(list(rows)))).all()
    return {e.request_id: e for e in evs if e.request_id}


def build_request_view(s: Session, ws: str, request_id: str) -> dict[str, Any]:
    req = _load_request(s, ws, request_id)
    data = dict(req.data or {})
    requester = s.get(m.User, req.requester_user_id) if req.requester_user_id else None
    last = _last_events(s, [req.id]).get(req.id)
    revisions = s.scalars(select(m.TicketRevision).where(m.TicketRevision.request_id == req.id)
                          .order_by(m.TicketRevision.n)).all()
    approval_rows = s.scalars(select(m.Approval).where(m.Approval.request_id == req.id)
                              .order_by(m.Approval.created_at)).all()
    build_rows = s.scalars(select(m.BuildRun).where(m.BuildRun.request_id == req.id)
                           .order_by(m.BuildRun.started_at)).all()
    tool_calls = s.scalar(select(func.count()).select_from(m.Event).where(
        m.Event.request_id == req.id, m.Event.type == "tool.called")) or 0
    tests_ev = s.scalar(select(m.Event).where(m.Event.request_id == req.id, m.Event.type == "tests.result")
                        .order_by(m.Event.seq.desc()).limit(1))
    answer_user_ids = [a.get("userId") for a in (data.get("answers") or {}).values() if a.get("userId")]
    users: dict[str, m.User] = {}
    for uid in answer_user_ids:
        try:
            u = s.get(m.User, uuid.UUID(str(uid)))
        except ValueError:
            u = None
        if u:
            users[str(u.id)] = u
    current = revisions[-1] if revisions else None
    tests = None
    if tests_ev is not None and req.state in (State.BUILDING, State.CHANGES_REQUESTED):
        p = tests_ev.payload or {}
        tests = {"passed": int(p.get("passed", 0)),
                 "total": int(p.get("passed", 0)) + int(p.get("failed", 0)) + int(p.get("skipped", 0))}
    pr = data.get("pr")
    questions = _questions_view(data, users)
    ctx = {
        "label": req.label, "decisionCount": len((data.get("findings") or {}).get("decisions") or []),
        "toolCalls": tool_calls, "pendingQuestions": sum(1 for q in questions if q["answer"] is None),
        "revisionN": current.n if current else None, "waitingBudget": data.get("waitingBudget"), "tests": tests,
        "attentionReason": data.get("attentionReason"), "failedStep": data.get("failedStep"),
        "attempts": build_rows[-1].attempts if build_rows else 0, "prNumber": (pr or {}).get("number"),
        "outcome": req.outcome, "memoryRefreshing": data.get("memoryRefreshing"),
    }
    headline, purpose = _headline(req.state, ctx)
    summary = _summary(req, requester, last, ctx)
    investigation = data.get("investigation")
    if investigation is not None:
        costs = budget_mod.request_costs(s, req.id)
        investigation = {"mode": investigation.get("mode", "pipeline"), "toolCalls": int(tool_calls),
                         "tokens": investigation.get("tokens") or costs["tokens"],
                         "costUsd": float(investigation.get("costUsd") or costs["costUsd"]),
                         "stub": bool(investigation.get("stub", False))}
    allowed = allowed_signals(req.state)
    if "answer" in allowed and not any(q["answer"] is None for q in questions):
        allowed = [a for a in allowed if a != "answer"]
    queue_pos = (data.get("build") or {}).get("queuePosition")
    slack = None
    if req.slack_channel and req.slack_thread_ts:
        slack = {"channel": req.slack_channel, "threadTs": req.slack_thread_ts, "permalink": data.get("slackPermalink")}
    ans = data.get("answer")
    return {
        **summary,
        "text": req.text, "headline": headline, "purpose": purpose, "slack": slack,
        "findings": data.get("findings"),
        "evidence": _evidence(list(data.get("evidence") or [])),
        "questions": questions,
        "revisions": [revision_view(r) for r in revisions],
        "currentRevision": {"n": current.n, "hash": current.content_hash} if current else None,
        "approvals": [approvals_mod.view(a) for a in approval_rows],
        "builds": [_build_view(b, queue_pos if i == len(build_rows) - 1 else None) for i, b in enumerate(build_rows)],
        "pr": ({"number": int(pr["number"]), "url": pr.get("url", ""), "headSha": pr.get("headSha", ""),
                "state": pr.get("state", "open"), "targetBranch": pr.get("targetBranch", "")} if pr else None),
        "investigation": investigation,
        "outcome": req.outcome,
        "answer": ({"text": ans.get("text", ""), "citations": _evidence(list(ans.get("citations") or []))}
                   if ans else None),
        "allowedActions": allowed,
        "memory": data.get("memory"),
        "budget": {"waiting": bool(data.get("waitingBudget"))},
    }


async def get_request_view(ws: str, request_id: str) -> dict[str, Any]:
    """B.C7 RequestDetail as a dict: the single read model for the API and Slack."""

    def load() -> dict[str, Any]:
        with session_scope() as s:
            return build_request_view(s, ws, request_id)

    return await asyncio.to_thread(load)


def list_requests_sync(s: Session, ws: str, group: str | None, limit: int) -> dict[str, Any]:
    needs = [st.value for st in NEEDS_YOU]
    final = [st.value for st in FINAL_STATES]
    base = select(m.Request).where(m.Request.workspace_id == ws)
    if group == "needs_you":
        q = base.where(m.Request.state.in_(needs)).order_by(m.Request.created_at.asc())
    elif group == "running":
        q = base.where(m.Request.state.notin_(needs + final)).order_by(m.Request.updated_at.desc())
    elif group == "done":
        q = base.where(m.Request.state.in_(final)).order_by(m.Request.updated_at.desc())
    else:
        q = base.order_by(m.Request.updated_at.desc())
    rows = s.scalars(q.limit(limit)).all()
    lasts = _last_events(s, [r.id for r in rows])
    users = {u.id: u for u in s.scalars(select(m.User).where(
        m.User.id.in_([r.requester_user_id for r in rows if r.requester_user_id]))).all()}
    counts_rows = s.execute(select(m.Request.state, func.count()).where(m.Request.workspace_id == ws)
                            .group_by(m.Request.state)).all()
    counts = {"needsYou": 0, "running": 0, "done": 0}
    for state, n in counts_rows:
        if state in needs:
            counts["needsYou"] += int(n)
        elif state in final:
            counts["done"] += int(n)
        else:
            counts["running"] += int(n)
    return {
        "requests": [_summary(r, users.get(r.requester_user_id) if r.requester_user_id else None, lasts.get(r.id), {})
                     for r in rows],
        "counts": counts,
    }


async def list_requests(ws: str, group: str | None = None, limit: int = 50) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        with session_scope() as s:
            return list_requests_sync(s, ws, group, limit)

    return await asyncio.to_thread(load)


def request_exists(ws: str, request_id: str) -> bool:
    with session_scope() as s:
        return s.scalar(select(m.Request.id).where(m.Request.id == request_id, m.Request.workspace_id == ws)) is not None


def set_request_fields(request_id: str, **values: Any) -> None:
    with session_scope() as s:
        s.execute(update(m.Request).where(m.Request.id == request_id).values(**values))
