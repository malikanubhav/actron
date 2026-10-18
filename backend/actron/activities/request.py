"""Activities for RequestWorkflow (spec B, B2). All I/O of the request flow lives here.

Each activity takes one JSON object and returns one JSON object, so workflow tests can replace any of them with a
fake registered under the same name.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio import activity
from ulid import ULID

from actron.config import get_settings
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import approvals as approvals_mod
from actron.flow import budget as budget_mod
from actron.flow import notifications
from actron.flow import questions as qmod
from actron.flow import ticket as ticket_mod
from actron.flow.events import Event, emit, insert_event, notify_slack, publish, sink_for
from actron.flow.states import FINAL_STATES, PIPELINE_STEP, State
from actron.logging import get_logger

log = get_logger(__name__)

FRESH_POLL_S = 10.0
FRESH_TIMEOUT_S = 600.0


class ExternalError(RuntimeError):
    """A provider call failed after retries."""


# Helpers
def _data(request_id: str) -> dict[str, Any]:
    with session_scope() as s:
        req = s.get(m.Request, request_id)
        return dict(req.data or {}) if req else {}


def _merge_data(request_id: str, values: dict[str, Any]) -> None:
    with session_scope() as s:
        req = s.scalar(select(m.Request).where(m.Request.id == request_id).with_for_update())
        if req is not None:
            req.data = {**(req.data or {}), **values}
            req.updated_at = datetime.now(UTC)


def _request(request_id: str) -> dict[str, Any]:
    with session_scope() as s:
        req = s.get(m.Request, request_id)
        if req is None:
            raise LookupError(request_id)
        return {"id": req.id, "ws": req.workspace_id, "kind": req.kind, "title": req.title, "text": req.text,
                "state": req.state, "label": req.label, "data": dict(req.data or {}),
                "linearIssueId": req.linear_issue_id, "prNumber": req.pr_number,
                "requester": str(req.requester_user_id) if req.requester_user_id else None}


async def emit_tx(ws: str, fn: Callable[[Session], list[Event]]) -> list[Event]:
    """Run `fn` in one transaction (it inserts events), add notifications, then publish and notify Slack."""

    def run() -> list[Event]:
        with session_scope() as s:
            evs = fn(s)
            extra: list[Event] = []
            for ev in evs:
                extra += notifications.create_for_event(s, ev)
            return evs + extra

    evs = await asyncio.to_thread(run)
    for ev in evs:
        await publish(ev)
    for ev in evs:
        await notify_slack(ws, ev)
    return evs


def _heartbeat(*details: Any) -> None:
    with contextlib.suppress(RuntimeError):  # not inside an activity (plain function tests)
        activity.heartbeat(*details)


async def _with_retry(fn: Callable[[], Any], *, attempts: int = 3, what: str = "call") -> Any:
    delay = 0.5
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:
            if i == attempts - 1:
                raise ExternalError(f"{what} failed: {type(exc).__name__}: {exc}") from exc
            await asyncio.sleep(delay)
            delay *= 2
    raise ExternalError(what)


def _github_cfg(ws: str) -> dict[str, Any]:
    try:
        from actron.connectors.common import resolve_config

        return dict(resolve_config(ws, "github").values)
    except Exception as exc:
        log.info("github config unavailable", extra={"error": type(exc).__name__})
        s = get_settings()
        return {"repository": s.GITHUB_REPOSITORY, "fork": s.GITHUB_FORK or s.GITHUB_REPOSITORY,
                "token": s.GITHUB_TOKEN, "working_branch": None, "api_url": s.GITHUB_API_URL}


def _github_client(cfg: dict[str, Any]) -> Any:
    from actron.integrations.github_client import GithubClient

    return GithubClient(cfg.get("token"), base_url=cfg.get("api_url"))


def _graph_repo(ws: str) -> dict[str, Any] | None:
    from actron.graph.store import store_for

    try:
        rows = store_for(ws).query(
            "MATCH (r:CodeRepository) WHERE coalesce(r.deleted, false) = false "
            "RETURN r.id AS id, r.headSha AS sha, r.defaultBranch AS branch, r.url AS url LIMIT 1",
            read_only=True,
        )
    except Exception as exc:
        log.warning("graph repo lookup failed", extra={"error": type(exc).__name__})
        return None
    return rows[0] if rows else None


def working_branch(ws: str, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg if cfg is not None else _github_cfg(ws)
    if cfg.get("working_branch"):
        return str(cfg["working_branch"])
    repo = _graph_repo(ws)
    return str((repo or {}).get("branch") or "main")


async def remote_head(ws: str, branch: str, cfg: dict[str, Any] | None = None) -> str | None:
    """Head sha of `branch` on the ingested repository (GitHub API, else `git ls-remote`). None if missing."""
    cfg = cfg if cfg is not None else _github_cfg(ws)
    repository = cfg.get("repository")
    if repository and not _has_github_token(cfg):
        # Without a token the public API allows 60 calls an hour; `git ls-remote` does not count against it.
        public_url = get_settings().git_url(str(repository))
        return await asyncio.to_thread(_ls_remote, public_url, branch)
    if repository:
        from actron.connectors.common import NotFoundError

        async def call() -> str | None:
            client = _github_client(cfg)
            try:
                data = await client.commit(repository, f"heads/{branch}")
                return str(data.get("sha")) if data.get("sha") else None
            except NotFoundError:
                return None
            finally:
                await client.aclose()

        result: str | None = await _with_retry(call, what="GitHub branch head")
        return result
    repo = _graph_repo(ws)
    url = (repo or {}).get("url")
    if not url:
        raise ExternalError("no repository is connected")
    return await asyncio.to_thread(_ls_remote, str(url), branch)


def _has_github_token(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("token"))


def _ls_remote(url: str, branch: str) -> str | None:
    out = subprocess.run(["git", "ls-remote", url, f"refs/heads/{branch}"], capture_output=True, text=True,
                         timeout=30, check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    line = out.stdout.strip().split("\n")[0] if out.stdout.strip() else ""
    return line.split()[0] if line else None


def _person(actor: dict[str, Any] | None) -> dict[str, Any]:
    a = actor or {}
    return {"personId": None, "userId": a.get("userId"), "name": a.get("name") or "Someone"}


# Freshness gate
@activity.defn(name="ensure_fresh")
async def ensure_fresh(args: dict[str, Any]) -> dict[str, Any]:
    """B2: make sure the graph holds the working branch's current head before investigating or building."""
    ws, rid = args["ws"], args["requestId"]
    target = args.get("branch")
    timeout_s = float(args.get("timeoutSeconds") or FRESH_TIMEOUT_S)
    poll_s = float(args.get("pollSeconds") or FRESH_POLL_S)
    cfg = _github_cfg(ws)
    repo = _graph_repo(ws)
    if repo is None and not cfg.get("repository"):
        await emit(ws, rid, "memory.unverified", {"reason": "No repository is connected yet."})
        return {"status": "unverified", "sha": None, "reason": "no_repository"}
    working = working_branch(ws, cfg)
    graph_sha = (repo or {}).get("sha")
    try:
        head = await remote_head(ws, working, cfg)
        target_sha = None
        if target and target != working:
            target_sha = await remote_head(ws, target, cfg)
            if target_sha is None:
                return {"status": "missing_branch", "sha": graph_sha, "reason": "missing_branch", "branch": target}
    except Exception as exc:
        await emit(ws, rid, "memory.unverified", {"reason": f"Could not reach the repository ({type(exc).__name__})."})
        return {"status": "unverified", "sha": graph_sha, "reason": "unreachable"}
    if head is None:
        return {"status": "missing_branch", "sha": graph_sha, "reason": "missing_branch", "branch": working}
    if head == graph_sha:
        return {"status": "fresh", "sha": head, "targetSha": target_sha}
    started = datetime.now(UTC)
    await emit(ws, rid, "memory.refreshing", {"fromSha": graph_sha, "toSha": head})
    await asyncio.to_thread(_merge_data, rid, {"memoryRefreshing": True})
    from actron.flow.service import get_gateway

    for source in ("code", "github"):
        try:
            await get_gateway().trigger_schedule(ws, source)
        except Exception as exc:
            log.warning("sync trigger failed", extra={"source": source, "error": type(exc).__name__})
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    try:
        while loop.time() < deadline:
            _heartbeat("waiting for sync")
            await asyncio.sleep(poll_s)
            now_repo = await asyncio.to_thread(_graph_repo, ws)
            if (now_repo or {}).get("sha") == head:
                changed = await asyncio.to_thread(_functions_changed_since, ws, started)
                await emit(ws, rid, "memory.refreshed", {"sha": head, "functionsChanged": changed})
                return {"status": "refreshed", "sha": head, "targetSha": target_sha}
        return {"status": "stale", "sha": graph_sha, "reason": "memory_stale"}
    finally:
        await asyncio.to_thread(_merge_data, rid, {"memoryRefreshing": False})


def _functions_changed_since(ws: str, since: datetime) -> int:
    from actron.graph.store import store_for, to_graph_value

    try:
        rows = store_for(ws).query(
            "MATCH (f:CodeFunction) WHERE f.refreshedAt >= $since RETURN count(f) AS c",
            {"since": to_graph_value(since)}, read_only=True,
        )
        return int(rows[0]["c"]) if rows else 0
    except Exception:
        return 0


# State changes
@activity.defn(name="set_state")
async def set_state(args: dict[str, Any]) -> dict[str, Any]:
    """Every transition: mirror `requests.state`, write `request.state_changed` (and done/cancelled), publish."""
    ws, rid, to = args["ws"], args["requestId"], State(args["to"])
    reason = args.get("reason")
    outcome = args.get("outcome")
    extra = dict(args.get("data") or {})
    flags = dict(args.get("flags") or {})

    def fn(s: Session) -> list[Event]:
        req = s.scalar(select(m.Request).where(m.Request.id == rid).with_for_update())
        if req is None:
            raise LookupError(rid)
        prev = req.state
        if prev == to.value and not extra:
            return []
        data = {**(req.data or {}), **extra}
        if to is State.CANCELLED and prev in State._value2member_map_:
            data["lastStep"] = PIPELINE_STEP[State(prev)]
        req.data = data
        req.state = to.value
        req.updated_at = datetime.now(UTC)
        if to in FINAL_STATES:
            req.closed_at = datetime.now(UTC)
            req.outcome = outcome
        out: list[Event] = []
        if prev != to.value:
            out.append(insert_event(s, ws, rid, "request.state_changed",
                                    {"from": prev, "to": to.value, "reason": reason, **flags}))
        if to is State.DONE:
            out.append(insert_event(s, ws, rid, "request.done", {"outcome": outcome}))
        if to is State.CANCELLED:
            out.append(insert_event(s, ws, rid, "request.cancelled",
                                    {"reason": reason, "by": args.get("by"), "outcome": outcome}))
        return out

    await emit_tx(ws, fn)
    from actron.flow.service import mirror_request_node

    await asyncio.to_thread(mirror_request_node, ws, rid)
    return {"state": to.value}


# Investigation
def _stub_findings(rid: str) -> dict[str, Any]:
    from actron.graph import ids

    return {"requestId": ids.request(rid), "seeds": [], "decisions": [], "relatedWork": [],
            "impact": {"callers": [], "tests": [], "criticality": []}, "owners": [], "procedures": [],
            "label": "nothing_found", "graph": {"nodes": [], "edges": []}}


@activity.defn(name="investigate_request")
async def investigate_request(args: dict[str, Any]) -> dict[str, Any]:
    """Run W5's investigator (agent or pipeline). Over the daily budget, the pipeline with stubs is used."""
    ws, rid = args["ws"], args["requestId"]
    req = await asyncio.to_thread(_request, rid)
    mode = "auto"
    status = await asyncio.to_thread(_budget_status, ws)
    if status["reached"]:
        await emit(ws, rid, "budget.reached", {"spentUsd": status["spentTodayUsd"], "capUsd": status["capUsd"]})
        mode = "pipeline"
    sink = sink_for(ws, rid)
    try:
        from actron.flow.investigate import investigate
    except Exception:
        investigate = None  # type: ignore[assignment]
    if investigate is None:
        # Stub until the investigator is installed: says so plainly, finds nothing.
        await sink("investigation.started", {"mode": "pipeline", "stub": True, "reason": "investigator not installed"})
        findings = _stub_findings(rid)
        summary = "The investigator is not installed in this build, so nothing was checked."
        await sink("investigation.completed", {
            "label": "nothing_found", "summary": summary,
            "counts": {"decisions": 0, "relatedWork": 0, "callers": 0, "tests": 0}, "findingsRef": rid,
        })
        values = {"findings": findings, "evidence": [], "findingQuestions": [],
                  "investigation": {"mode": "pipeline", "stub": True, "summary": summary}}
        await asyncio.to_thread(_store_investigation, rid, "nothing_found", values)
        return {"label": "nothing_found", "questionCount": 0, "evidenceCount": 0, "stub": True}
    result = await investigate(ws, rid, req["text"], req["kind"], emit=sink, mode=mode)  # type: ignore[arg-type]
    dump = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    findings = result.findings.to_json() if hasattr(result.findings, "to_json") else dump.get("findings")
    values = {
        "findings": findings,
        "evidence": dump.get("evidence") or [],
        "findingQuestions": dump.get("questions") or [],
        "investigation": {
            "mode": dump.get("mode", "pipeline"), "toolCalls": dump.get("tool_calls", 0),
            "tokens": dump.get("tokens") or {"input": 0, "output": 0}, "costUsd": dump.get("cost_usd", 0.0),
            "stub": bool(dump.get("stub")), "summary": dump.get("summary"),
            "investigationId": dump.get("investigation_id"), "fallbackReason": dump.get("fallback_reason"),
        },
    }
    label = str(dump.get("label") or (findings or {}).get("label") or "nothing_found")
    await asyncio.to_thread(_store_investigation, rid, label, values)
    return {"label": label, "questionCount": len(dump.get("questions") or []),
            "evidenceCount": len(dump.get("evidence") or []), "stub": bool(dump.get("stub"))}


def _store_investigation(rid: str, label: str, values: dict[str, Any]) -> None:
    with session_scope() as s:
        req = s.scalar(select(m.Request).where(m.Request.id == rid).with_for_update())
        if req is not None:
            req.label = label
            req.data = {**(req.data or {}), **values}


def _budget_status(ws: str) -> dict[str, Any]:
    with session_scope() as s:
        return budget_mod.status(s, ws)


async def list_branches(ws: str, cfg: dict[str, Any]) -> list[qmod.Branch]:
    """Branches of the ingested repository, protected flag and last commit date where GitHub gives it."""
    repository = cfg.get("repository")
    if not repository:
        return []

    async def call() -> list[dict[str, Any]]:
        client = _github_client(cfg)
        try:
            rows: list[dict[str, Any]] = await client.branches(repository, limit=100)
            return rows
        finally:
            await client.aclose()

    try:
        rows = await _with_retry(call, what="GitHub branches")
    except ExternalError as exc:
        log.warning("branch list failed", extra={"error": str(exc)[:200]})
        return []
    out = []
    for b in rows:
        commit = b.get("commit") or {}
        date = (((commit.get("commit") or {}).get("committer") or {}).get("date")) or b.get("updated_at")
        out.append(qmod.Branch(str(b.get("name")), bool(b.get("protected")), date))
    return out


@activity.defn(name="prepare_questions")
async def prepare_questions(args: dict[str, Any]) -> dict[str, Any]:
    """B6: the investigator's questions (max 3, evidence checked) plus the target-branch question."""
    ws, rid = args["ws"], args["requestId"]
    req = await asyncio.to_thread(_request, rid)
    data = req["data"]
    evidence_ids = {str(e.get("evidenceId")) for e in data.get("evidence") or []}
    try:
        from actron.flow.findings import Findings

        evidence_ids |= Findings.model_validate(data.get("findings") or {}).node_ids()
    except Exception:
        pass
    questions = qmod.limit_finding_questions(list(data.get("findingQuestions") or []), evidence_ids)
    cfg = _github_cfg(ws)
    working = working_branch(ws, cfg)
    branches: list[qmod.Branch] = []
    target: str | None = None
    if req["kind"] in ("feature", "bug"):
        branches = await list_branches(ws, cfg)
        names = [b.name for b in branches] or [working]
        target = qmod.branch_named_in_text(req["text"], names)
        if target is None:
            questions.append(qmod.target_branch_question(working, branches))
    names = sorted({b.name for b in branches} | {working})
    await asyncio.to_thread(_merge_data, rid, {"questions": questions, "answers": {}, "branchNames": names,
                                               "workingBranch": working, "targetBranch": target})
    for q in questions:
        await emit(ws, rid, "question.asked", {"questionId": q["questionId"], "text": q["text"],
                                               "options": q.get("options") or [], "evidenceIds": q.get("evidenceIds") or []})
    return {"questions": questions, "branchNames": names, "workingBranch": working, "targetBranch": target}


@activity.defn(name="record_answer")
async def record_answer(args: dict[str, Any]) -> dict[str, Any]:
    rid = args["requestId"]
    actor = args.get("actor") or {}

    def fn() -> None:
        with session_scope() as s:
            req = s.scalar(select(m.Request).where(m.Request.id == rid).with_for_update())
            if req is None:
                return
            data = dict(req.data or {})
            answers = dict(data.get("answers") or {})
            answers[args["questionId"]] = {
                "value": args["value"], "userId": actor.get("userId"), "name": actor.get("name"),
                "surface": actor.get("surface", "ui"), "at": datetime.now(UTC).isoformat(),
            }
            data["answers"] = answers
            if args["questionId"] == qmod.TARGET_BRANCH_ID:
                data["targetBranch"] = qmod.target_branch_from_answer(args["value"], data.get("workingBranch") or "main")
            req.data = data

    await asyncio.to_thread(fn)
    return {"ok": True}


@activity.defn(name="write_answer")
async def write_answer(args: dict[str, Any]) -> dict[str, Any]:
    """Q&A (B14): compose the answer with citations from the evidence and emit `answer.ready`."""
    ws, rid = args["ws"], args["requestId"]
    req = await asyncio.to_thread(_request, rid)
    evidence = list(req["data"].get("evidence") or [])
    text_, cited, stub = await _compose_answer(ws, rid, req["text"], evidence)
    await asyncio.to_thread(_merge_data, rid, {"answer": {"text": text_, "citations": cited, "stub": stub}})
    await emit(ws, rid, "answer.ready", {"answerRef": rid, "text": text_, "citations": [c.get("evidenceId") for c in cited]})
    return {"ok": True}


async def _compose_answer(ws: str, rid: str, question: str,
                          evidence: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], bool]:
    from actron.flow.qa import compose_answer

    return await compose_answer(ws, rid, question, evidence)


# Tickets
@activity.defn(name="draft_ticket")
async def draft_ticket(args: dict[str, Any]) -> dict[str, Any]:
    ws, rid = args["ws"], args["requestId"]
    req = await asyncio.to_thread(_request, rid)
    data = req["data"]
    target = data.get("targetBranch") or data.get("workingBranch") or "main"
    answers = [{"questionId": qid, "value": a.get("value"),
                "text": next((q.get("text") for q in data.get("questions") or [] if q.get("questionId") == qid), "")}
               for qid, a in (data.get("answers") or {}).items()]
    content: dict[str, Any] | None = None
    try:
        from actron.models import write_ticket

        t = await write_ticket(req["text"], data.get("findings") or {}, answers, ws=ws, request_id=rid)
        content = t.model_dump()
    except Exception as exc:
        log.info("write_ticket unavailable; using the template", extra={"error": type(exc).__name__})
    if content is None:
        content = ticket_mod.template_ticket(request_id=rid, title=req["title"], text=req["text"],
                                             findings=data.get("findings"), answers=answers, target_branch=target)
    content["targetBranch"] = target
    return ticket_mod.normalise_content(content, rid)


@activity.defn(name="save_revision")
async def save_revision(args: dict[str, Any]) -> dict[str, Any]:
    """B7: canonicalise, hash, insert revision n = previous + 1, emit `ticket.revised`."""
    ws, rid = args["ws"], args["requestId"]
    created_by = str(args.get("createdBy") or "actron")
    by = args.get("by") or {"personId": None, "userId": None, "name": "Actron"}

    def fn(s: Session) -> list[Event]:
        req = s.scalar(select(m.Request).where(m.Request.id == rid).with_for_update())
        if req is None:
            raise LookupError(rid)
        content = ticket_mod.normalise_content(dict(args["content"]), rid)
        if not content["targetBranch"]:
            data = req.data or {}
            content["targetBranch"] = data.get("targetBranch") or data.get("workingBranch") or "main"
        h = ticket_mod.ticket_hash(content)
        n = int(s.scalar(select(func.coalesce(func.max(m.TicketRevision.n), 0))
                         .where(m.TicketRevision.request_id == rid)) or 0) + 1
        s.add(m.TicketRevision(request_id=rid, n=n, content=content, content_hash=h, created_by=created_by,
                               created_at=datetime.now(UTC)))
        s.flush()
        result.update({"n": n, "hash": h, "targetBranch": content["targetBranch"]})
        return [insert_event(s, ws, rid, "ticket.revised",
                             {"n": n, "hash": h, "contentRef": f"{rid}/r{n}", "by": by})]

    result: dict[str, Any] = {}
    await emit_tx(ws, fn)
    return result


def build_branch(rid: str, revision: int, attempt: int, same_branch: bool, pr: dict[str, Any] | None) -> str:
    """Branch a build pushes to. A request with an open PR keeps building on that PR's branch (also after an edited
    ticket), because the PR is updated in place: a new branch would leave the PR on the old commit while Actron
    records the new one."""
    branch = f"actron/{rid}-r{revision}" + (f"-{attempt}" if attempt > 1 and not same_branch else "")
    pr = pr or {}
    if pr.get("branch") and (same_branch or pr.get("state", "open") == "open"):
        return str(pr["branch"])
    return branch


def _revision(rid: str, n: int) -> m.TicketRevision | None:
    with session_scope() as s:
        return s.scalar(select(m.TicketRevision).where(m.TicketRevision.request_id == rid, m.TicketRevision.n == n))


def _linear_client(cfg: dict[str, Any]) -> Any:
    """W3's LinearClient (timeouts, retries and typed errors live there)."""
    from actron.integrations.linear_client import LinearClient

    return LinearClient(cfg.get("token"), base_url=cfg.get("api_url"))


async def linear_write(cfg: dict[str, Any], issue_id: str | None, title: str, description: str) -> dict[str, Any]:
    """Create the issue (with a chosen id, so a retried create cannot duplicate it) or update it."""
    client = _linear_client(cfg)
    try:
        if issue_id:
            out: dict[str, Any] = await client.issue_update(issue_id, title=title, description=description)
        else:
            out = await client.issue_create(issue_id=str(uuid.uuid4()), team_id=str(cfg["team"]), title=title,
                                            description=description)
        return out
    finally:
        await client.aclose()


async def linear_read(cfg: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    client = _linear_client(cfg)
    try:
        found: dict[str, Any] | None = await client.issue(issue_id)
        return found
    finally:
        await client.aclose()


def _linear_cfg(ws: str) -> dict[str, Any]:
    try:
        from actron.connectors.common import resolve_config

        return dict(resolve_config(ws, "linear").values)
    except Exception:
        s = get_settings()
        return {"token": s.LINEAR_API_KEY, "team": s.LINEAR_TEAM_ID, "api_url": s.LINEAR_API_URL}


@activity.defn(name="sync_ticket")
async def sync_ticket(args: dict[str, Any]) -> dict[str, Any]:
    """B7: create or update the Linear issue; with Linear not connected, record that and continue (B-AC-35)."""
    ws, rid, n, h = args["ws"], args["requestId"], int(args["n"]), str(args["hash"])
    cfg = _linear_cfg(ws)
    req = await asyncio.to_thread(_request, rid)
    if not cfg.get("token") or not cfg.get("team"):
        await emit(ws, rid, "ticket.synced", {"linearIssueId": None, "identifier": None, "url": None, "n": n,
                                              "hash": h, "skipped": True, "reason": "Linear not connected"})
        return {"synced": False, "reason": "Linear not connected"}
    rev = await asyncio.to_thread(_revision, rid, n)
    if rev is None:
        raise LookupError(f"{rid} r{n}")
    body = ticket_mod.render_markdown(dict(rev.content), n=n, content_hash=h)
    title = str(rev.content.get("objective") or req["title"])[:200]
    try:
        issue = await linear_write(cfg, req["linearIssueId"], title, body)
    except Exception as exc:
        await emit(ws, rid, "ticket.synced", {"linearIssueId": None, "identifier": None, "url": None, "n": n,
                                              "hash": h, "skipped": True,
                                              "reason": f"Linear did not accept the ticket ({type(exc).__name__})"})
        return {"synced": False, "reason": "linear_error"}
    linear = {"issueId": issue.get("id"), "identifier": issue.get("identifier"), "url": issue.get("url")}

    def store() -> None:
        with session_scope() as s:
            r = s.get(m.Request, rid)
            if r is not None:
                r.linear_issue_id = linear["issueId"]
            row = s.scalar(select(m.TicketRevision).where(m.TicketRevision.request_id == rid, m.TicketRevision.n == n))
            if row is not None:
                row.linear = linear

    await asyncio.to_thread(store)
    await emit(ws, rid, "ticket.synced", {"linearIssueId": linear["issueId"], "identifier": linear["identifier"],
                                          "url": linear["url"], "n": n, "hash": h})
    await asyncio.to_thread(_link_tracked_by, ws, rid, linear["issueId"])
    return {"synced": True, **linear}


def _link_tracked_by(ws: str, rid: str, issue_id: str | None) -> None:
    if not issue_id:
        return
    from actron.graph import ids
    from actron.graph.store import LinkRow, store_for

    try:
        store_for(ws).upsert_links("TRACKED_BY", "Request", "LinearIssue", [
            LinkRow(ids.request(rid), ids.linear_issue(issue_id), {"method": "explicit", "confidence": 1.0})])
    except Exception as exc:
        log.info("TRACKED_BY not written", extra={"error": type(exc).__name__})


@activity.defn(name="check_external_edit")
async def check_external_edit(args: dict[str, Any]) -> dict[str, Any]:
    """B-AC-34: read the Linear issue and compare its JSON block and marker with the current revision."""
    ws, rid, h = args["ws"], args["requestId"], str(args["hash"])
    req = await asyncio.to_thread(_request, rid)
    cfg = _linear_cfg(ws)
    if not req["linearIssueId"] or not cfg.get("token"):
        return {"externalEdit": False, "checked": False}
    try:
        issue = await linear_read(cfg, str(req["linearIssueId"]))
    except Exception as exc:
        log.warning("linear read failed; approval not blocked", extra={"error": type(exc).__name__})
        return {"externalEdit": False, "checked": False}
    description = str((issue or {}).get("description") or "")
    edited = ticket_mod.detect_external_edit(description, h)
    if edited:
        def mark() -> None:
            with session_scope() as s:
                row = s.scalar(select(m.TicketRevision).where(m.TicketRevision.request_id == rid,
                                                              m.TicketRevision.content_hash == h))
                if row is not None:
                    row.external_edit = True

        await asyncio.to_thread(mark)
    return {"externalEdit": edited, "checked": True}


# Approvals and outcomes
@activity.defn(name="record_approval")
async def record_approval(args: dict[str, Any]) -> dict[str, Any]:
    """The workflow's decision on an approval: the row, the outcome event, and the hand-back to the service."""
    ws, rid = args["ws"], args["requestId"]
    kind, target, status = args["kind"], str(args["target"]), args["status"]
    reason = args.get("reason")
    actor = dict(args.get("actor") or {})
    surface = str(actor.get("surface")) if actor.get("surface") in ("slack", "ui") else "ui"
    by = _person(actor)

    def fn(s: Session) -> list[Event]:
        approvals_mod.record(s, rid, kind=kind, target=target, status=status, reason=reason, actor=actor)
        if status == "accepted":
            evs = [insert_event(s, ws, rid, "approval.recorded",
                                {"kind": kind, "target": target, "by": by, "surface": surface},
                                actor="person" if surface == "ui" else "slack", surface=surface)]
            if kind == "pr":
                evs.append(insert_event(s, ws, rid, "pr.approved", {"headSha": target, "by": by, "surface": surface},
                                        actor="person" if surface == "ui" else "slack", surface=surface))
            return evs
        return [insert_event(s, ws, rid, "approval.refused",
                             {"kind": kind, "target": target, "reason": reason, "by": by, "surface": surface},
                             surface=surface)]

    evs = await emit_tx(ws, fn)
    outcome = {"status": status, "reason": reason, "eventId": evs[0].id if evs else None,
               "state": args.get("state")}
    if args.get("idempotencyKey"):
        await approvals_mod.publish_outcome(rid, str(args["idempotencyKey"]), outcome)
    return outcome


@activity.defn(name="publish_outcome")
async def publish_outcome(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("idempotencyKey"):
        await approvals_mod.publish_outcome(str(args["requestId"]), str(args["idempotencyKey"]),
                                            dict(args.get("outcome") or {}))
    return {"ok": True}


@activity.defn(name="send_reminder")
async def send_reminder(args: dict[str, Any]) -> dict[str, Any]:
    """B-AC-10: one reminder after 24 hours of waiting (a notification and a `notification.sent` event)."""
    ws, rid, kind = args["ws"], args["requestId"], args["kind"]

    def fn(s: Session) -> list[Event]:
        req = s.get(m.Request, rid)
        if req is None:
            return []
        title = "Reminder: Actron is waiting for your answer" if kind == "needs_input" else \
            "Reminder: a ticket is waiting for your approval"
        note = m.Notification(workspace_id=ws, user_id=req.requester_user_id, request_id=rid, kind=kind,
                              title=title, body=req.title, tab=notifications.TAB_FOR.get(kind, "evidence"),
                              created_at=datetime.now(UTC))
        s.add(note)
        s.flush()
        return [insert_event(s, ws, rid, "notification.sent", {
            "kind": kind, "toPersonId": None, "toUserId": str(req.requester_user_id) if req.requester_user_id else None,
            "channel": "ui", "notificationId": str(note.id), "title": title, "reminder": True,
            "tab": notifications.TAB_FOR.get(kind, "evidence")})]

    await emit_tx(ws, fn)
    return {"ok": True}


# Budget
@activity.defn(name="budget_check")
async def budget_check(args: dict[str, Any]) -> dict[str, Any]:
    ws, rid = args["ws"], args["requestId"]
    status = await asyncio.to_thread(_budget_status, ws)
    if status["reached"]:
        await asyncio.to_thread(_merge_data, rid, {"waitingBudget": True,
                                                   "build": {"status": "waiting_budget", "queuePosition": None}})
        await emit(ws, rid, "budget.reached", {"spentUsd": status["spentTodayUsd"], "capUsd": status["capUsd"]})
    return status


@activity.defn(name="budget_resumed")
async def budget_resumed(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.to_thread(_merge_data, args["requestId"], {"waitingBudget": False})
    return {"ok": True}


# Build
def _build_evidence(findings: dict[str, Any]) -> dict[str, Any]:
    return {k: findings.get(k) for k in ("requestId", "seeds", "decisions", "relatedWork", "impact", "owners", "label")}


@activity.defn(name="prepare_build")
async def prepare_build(args: dict[str, Any]) -> dict[str, Any]:
    """B.C6 BuildInput, a queued `build_runs` row, and `handoff.created` (emitted before the child starts)."""
    ws, rid = args["ws"], args["requestId"]
    rev = args["revision"]
    req = await asyncio.to_thread(_request, rid)
    data = req["data"]
    row = await asyncio.to_thread(_revision, rid, int(rev["n"]))
    if row is None:
        raise LookupError(f"{rid} r{rev['n']}")
    ticket = {**dict(row.content), "revision": row.n}
    findings = data.get("findings") or {}
    procedures = list(findings.get("procedures") or [])
    test_command = next((t.get("command") for t in ticket.get("testPlan") or [] if t.get("command")), None) or \
        next((p.get("testCommand") for p in procedures if p.get("testCommand")), None)
    settings = get_settings()
    build_id = f"bld_{ULID()}"
    attempt = int(args.get("attempt") or 1)
    branch = build_branch(rid, row.n, attempt, bool(args.get("sameBranch")), data.get("pr"))
    base_sha = args.get("targetSha") or args.get("baseSha") or ""
    cfg = _github_cfg(ws)
    repository = str(cfg.get("repository") or "")
    previous = None
    if args.get("feedback") or (data.get("build") or {}).get("id"):
        previous = {"buildId": (data.get("build") or {}).get("id"), "feedback": args.get("feedback")}
    inp = {
        "ws": ws, "requestId": rid, "buildId": build_id, "revisionHash": row.content_hash, "revision": row.n,
        "ticket": ticket, "evidence": _build_evidence(findings), "procedures": procedures, "baseSha": base_sha,
        "branch": branch, "testCommand": test_command, "maxRepairs": settings.ACTRON_MAX_REPAIRS,
        "timeoutSeconds": settings.ACTRON_BUILD_TIMEOUT_SECONDS,
        "repository": repository, "repoUrl": settings.git_url(repository) if repository else None,
        "pushTarget": cfg.get("fork") or None, "upstream": cfg.get("upstream"),
        "workingBranch": data.get("workingBranch") or cfg.get("working_branch"),
        "ticketIdentifier": (row.linear or {}).get("identifier"), "existingPrNumber": (data.get("pr") or {}).get("number"),
        "previousBuild": previous,
        "targetBranch": ticket.get("targetBranch") or data.get("workingBranch") or "main",
        "feedback": args.get("feedback"),
    }
    investigation_id = (data.get("investigation") or {}).get("investigationId")
    evidence_count = len(data.get("evidence") or [])

    def fn(s: Session) -> list[Event]:
        s.add(m.BuildRun(id=build_id, request_id=rid, status="queued", branch=branch, base_sha=base_sha,
                         started_at=datetime.now(UTC)))
        s.flush()
        r = s.get(m.Request, rid)
        if r is not None:
            r.data = {**(r.data or {}), "build": {"id": build_id, "status": "queued", "queuePosition": None}}
        return [insert_event(s, ws, rid, "handoff.created", {"investigationId": investigation_id, "buildId": build_id,
                                                             "evidenceCount": evidence_count, "branch": branch})]

    await emit_tx(ws, fn)
    return inp


def _get(result: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    if camel in result:
        return result[camel]
    return result.get(snake, default)


@activity.defn(name="record_build_result")
async def record_build_result(args: dict[str, Any]) -> dict[str, Any]:
    """Mirror the child's BuildResult (B.C6) into `build_runs` and the request (PR number, head)."""
    rid, build_id = args["requestId"], args["buildId"]
    res = dict(args.get("result") or {})
    status = str(_get(res, "status", "status", "failed"))
    tokens = res.get("tokens") or {}

    def fn() -> dict[str, Any]:
        with session_scope() as s:
            row = s.get(m.BuildRun, build_id)
            if row is None:
                row = m.BuildRun(id=build_id, request_id=rid, status=status, branch=str(args.get("branch") or ""),
                                 started_at=datetime.now(UTC))
                s.add(row)
            row.status = status
            row.head_sha = _get(res, "headSha", "head_sha", row.head_sha)
            row.tests_passed = int(_get(res, "testsPassed", "tests_passed", row.tests_passed or 0) or 0)
            row.tests_failed = int(_get(res, "testsFailed", "tests_failed", row.tests_failed or 0) or 0)
            row.attempts = int(_get(res, "attempts", "attempts", row.attempts or 0) or 0)
            row.stop_reason = _get(res, "stopReason", "stop_reason", row.stop_reason)
            row.input_tokens = int(tokens.get("input", row.input_tokens or 0) or 0)
            row.output_tokens = int(tokens.get("output", row.output_tokens or 0) or 0)
            row.finished_at = row.finished_at or datetime.now(UTC)
            # The build folder holds Pi's output per attempt; the log route reads it (Raw log in the Build tab).
            build_dir = get_settings().ACTRON_BUILD_HOST_DIR / build_id
            if not row.log_path and build_dir.is_dir():
                row.log_path = str(build_dir)
            files = _get(res, "filesChanged", "files_changed") or []
            sent = res.get("report")
            report: dict[str, Any] = dict(sent) if isinstance(sent, dict) else dict(row.report or {})
            # The build sends Build.report in the request view's shape (flow/build.py build_ui_report);
            # an older or partial result only names the files.
            listed = report.get("filesChanged")
            if not (isinstance(listed, list) and all(isinstance(f, dict) for f in listed)) or (files and not listed):
                report["filesChanged"] = [{"path": str(p), "additions": 0, "deletions": 0} for p in files]
            for key in ("tests", "constraints", "procedures"):
                report.setdefault(key, [])
            row.report = report
            req = s.scalar(select(m.Request).where(m.Request.id == rid).with_for_update())
            pr = None
            if req is not None:
                data = dict(req.data or {})
                number = _get(res, "prNumber", "pr_number")
                if status == "passed" and number:
                    known = data.get("pr") or {}
                    # The PR's head branch is fixed when it is opened; a later build of the same PR must not replace it.
                    pr_branch = known.get("branch") if known.get("number") == int(number) else None
                    pr = {"number": int(number), "url": _get(res, "prUrl", "pr_url", ""), "headSha": row.head_sha or "",
                          "state": "open", "targetBranch": args.get("targetBranch") or data.get("targetBranch") or "",
                          "branch": pr_branch or row.branch}
                    data["pr"] = pr
                    req.pr_number = int(number)
                data["build"] = {"id": build_id, "status": status, "queuePosition": None}
                req.data = data
            return {"status": status, "pr": pr, "stopReason": row.stop_reason, "headSha": row.head_sha}

    return await asyncio.to_thread(fn)


@activity.defn(name="mark_build_cancelled")
async def mark_build_cancelled(args: dict[str, Any]) -> dict[str, Any]:
    def fn() -> None:
        with session_scope() as s:
            row = s.get(m.BuildRun, args["buildId"])
            if row is not None and row.status in ("queued", "running", "waiting_budget"):
                row.status = "stopped"
                row.stop_reason = "cancelled"
                row.finished_at = datetime.now(UTC)

    await asyncio.to_thread(fn)
    return {"ok": True}


# Pull requests
async def _pr_json(ws: str, number: int) -> dict[str, Any]:
    cfg = _github_cfg(ws)
    repo = cfg.get("fork") or cfg.get("repository")
    if not repo or not cfg.get("token"):
        raise ExternalError("GitHub is not connected")

    async def call() -> dict[str, Any]:
        client = _github_client(cfg)
        try:
            data: dict[str, Any] = await client.get_json(f"/repos/{repo}/pulls/{number}")
            return data
        finally:
            await client.aclose()

    result: dict[str, Any] = await _with_retry(call, what="GitHub pull request")
    return result


@activity.defn(name="read_pr_head")
async def read_pr_head(args: dict[str, Any]) -> dict[str, Any]:
    """B.C1: approve_pr is checked against the PR's current head, re-read from GitHub."""
    ws, rid = args["ws"], args["requestId"]
    data = await asyncio.to_thread(_data, rid)
    pr = data.get("pr") or {}
    if not pr.get("number"):
        return {"headSha": None, "verified": False}
    try:
        j = await _pr_json(ws, int(pr["number"]))
    except ExternalError:
        return {"headSha": pr.get("headSha"), "verified": False}
    head = ((j.get("head") or {}).get("sha")) or pr.get("headSha")
    if head != pr.get("headSha"):
        await asyncio.to_thread(_merge_data, rid, {"pr": {**pr, "headSha": head}})
    return {"headSha": head, "verified": True, "state": "merged" if j.get("merged") else j.get("state")}


@activity.defn(name="check_pr")
async def check_pr(args: dict[str, Any]) -> dict[str, Any]:
    """Merge watch (A11): the PR's state, recorded on the request."""
    ws, rid = args["ws"], args["requestId"]
    data = await asyncio.to_thread(_data, rid)
    pr = data.get("pr") or {}
    if not pr.get("number"):
        return {"state": "unknown"}
    try:
        j = await _pr_json(ws, int(pr["number"]))
    except ExternalError:
        return {"state": "unknown"}
    state = "merged" if j.get("merged") or j.get("merged_at") else str(j.get("state") or "open")
    if state != pr.get("state"):
        await asyncio.to_thread(_merge_data, rid, {"pr": {**pr, "state": state}})
    return {"state": state}


@activity.defn(name="close_pr")
async def close_pr(args: dict[str, Any]) -> dict[str, Any]:
    ws, rid = args["ws"], args["requestId"]
    data = await asyncio.to_thread(_data, rid)
    pr = data.get("pr") or {}
    cfg = _github_cfg(ws)
    repo = cfg.get("fork") or cfg.get("repository")
    closed = False
    if pr.get("number") and repo and cfg.get("token"):
        async def call() -> None:
            client = _github_client(cfg)
            try:
                await client.request("PATCH", f"/repos/{repo}/pulls/{pr['number']}", json={"state": "closed"})
            finally:
                await client.aclose()

        try:
            await _with_retry(call, what="GitHub close PR")
            closed = True
        except ExternalError as exc:
            log.warning("close PR failed", extra={"error": str(exc)[:200]})
    if pr:
        await asyncio.to_thread(_merge_data, rid, {"pr": {**pr, "state": "closed" if closed else pr.get("state")}})
    return {"closed": closed}


@activity.defn(name="trigger_syncs")
async def trigger_syncs(args: dict[str, Any]) -> dict[str, Any]:
    from actron.flow.service import get_gateway

    done = []
    for source in args.get("sources") or ("code", "github"):
        try:
            await get_gateway().trigger_schedule(args["ws"], source)
            done.append(source)
        except Exception as exc:
            log.warning("sync trigger failed", extra={"source": source, "error": type(exc).__name__})
    return {"triggered": done}


# Review feedback
@activity.defn(name="classify_feedback")
async def classify_feedback(args: dict[str, Any]) -> dict[str, Any]:
    """J10 on PR feedback; the stub answer is `question` (never act without a person)."""
    ws, rid = args["ws"], args["requestId"]
    ticket: dict[str, Any] = {}

    def latest() -> dict[str, Any]:
        with session_scope() as s:
            row = s.scalar(select(m.TicketRevision).where(m.TicketRevision.request_id == rid)
                           .order_by(m.TicketRevision.n.desc()).limit(1))
            return dict(row.content) if row else {}

    ticket = await asyncio.to_thread(latest)
    kind, provider, prob = "question", "stub", None
    try:
        from actron.models import feedback_kind

        j = await feedback_kind(str(args["text"]), ticket, ws=ws, request_id=rid)
        kind = str(j.answer)
        provider = str(j.provider)
        prob = j.probability
    except Exception as exc:
        log.warning("feedback_kind unavailable", extra={"error": type(exc).__name__})
    if kind not in ("code_change_within_scope", "scope_change", "question", "approval"):
        kind = "question"
    await emit(ws, rid, "judgment.made", {"job": "feedback_kind", "provider": provider, "count": 1,
                                          "what": "review feedback", "answer": kind, "probability": prob})
    return {"kind": kind}


@activity.defn(name="answer_feedback")
async def answer_feedback(args: dict[str, Any]) -> dict[str, Any]:
    ws, rid = args["ws"], args["requestId"]
    data = await asyncio.to_thread(_data, rid)
    text_, cited, stub = await _compose_answer(ws, rid, str(args["text"]), list(data.get("evidence") or []))
    await emit(ws, rid, "answer.ready", {"answerRef": f"{rid}/review/{uuid.uuid4().hex[:8]}", "text": text_,
                                         "context": "review", "stub": stub,
                                         "citations": [c.get("evidenceId") for c in cited]})
    return {"ok": True}


# Write-back (B10)
@activity.defn(name="writeback")
async def writeback(args: dict[str, Any]) -> dict[str, Any]:
    """Ingest the PR, link request, build, investigation, procedures and touched functions; `writeback.done`."""
    from actron.flow import writeback as wb

    ws, rid = args["ws"], args["requestId"]
    cfg = _github_cfg(ws)
    repo = str(cfg.get("fork") or cfg.get("repository") or "") or None
    counts: dict[str, Any] = {"prs": 0, "commits": 0, "functions": 0, "procedures": 0}
    number = args.get("prNumber")
    if number and repo and cfg.get("token"):
        try:
            got = await wb.ingest_pr(ws, repo, int(number))
            counts["commits"] = got["commits"]
        except Exception as exc:
            log.warning("PR ingest for write-back failed; recording what the build reported",
                        extra={"error": type(exc).__name__})
    linked = await asyncio.to_thread(wb.link_build, ws, rid, args.get("buildId"), repo)
    counts.update({k: v for k, v in linked.items() if k != "commits"})
    await emit(ws, rid, "writeback.done", {"counts": counts})
    return {"counts": counts}


ACTIVITIES: list[Callable[..., Any]] = [
    writeback,
    ensure_fresh, set_state, investigate_request, prepare_questions, record_answer, write_answer, draft_ticket,
    save_revision, sync_ticket, check_external_edit, record_approval, publish_outcome, send_reminder, budget_check,
    budget_resumed, prepare_build, record_build_result, mark_build_cancelled, read_pr_head, check_pr, close_pr,
    trigger_syncs, classify_feedback, answer_feedback,
]
