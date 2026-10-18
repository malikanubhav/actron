"""Request routes (spec B, B.C7): create, list, detail, actions, revisions, PR diff, build log."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select

from actron.api import schemas as sc
from actron.api.deps import ApiError, Ctx, current, error_body, once, writer
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import service
from actron.flow.service import ActionResult

router = APIRouter(tags=["requests"])

_REFUSAL_MESSAGES = {
    "stale_revision": "This approval was for an older revision. Review the current ticket and approve again.",
    "stale_head": "The PR changed since you looked at it. Review the latest commit and approve again.",
    "external_edit": "The ticket was edited in Linear. Save a new revision before approving.",
    "invalid_transition": "This action is not available in the request's current state.",
    "not_an_approver": "You are not allowed to approve this request.",
    "invalid_answer": "That answer is not one of the options.",
}


def action_response(result: ActionResult, extra: dict[str, Any] | None = None) -> Response:
    """accepted/duplicate -> 200, pending -> 202, refused -> 409 with the reason as the error code."""
    status = result.get("status")
    body = {"result": {k: result.get(k) for k in ("status", "reason", "eventId", "state")}, **(extra or {})}
    if status == "refused":
        reason = str(result.get("reason") or "refused")
        return JSONResponse(error_body(reason, _REFUSAL_MESSAGES.get(reason, "The action was refused."),
                                       {"result": body["result"]}), status_code=409)
    return JSONResponse(body, status_code=202 if status == "pending" else 200)


async def _create(ctx: Ctx, body: sc.CreateRequestIn, kind_hint: str | None) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        view = await service.create_request(ctx.ws, text=body.text, actor=ctx.actor(), source="ui",
                                            kind_hint=kind_hint)
        return {"request": view}

    return await once(ctx, "create_request", run)


@router.post("/api/requests", status_code=201, response_model=sc.RequestOut)
async def create_request(body: sc.CreateRequestIn, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    return await _create(ctx, body, body.kindHint)


@router.post("/api/ask", status_code=201, response_model=sc.RequestOut)
async def ask(body: sc.CreateRequestIn, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    return await _create(ctx, body, "question")


@router.get("/api/requests", response_model=sc.RequestList)
async def list_requests(group: Literal["needs_you", "running", "done"] | None = None,
                        limit: int = Query(50, ge=1, le=200), ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return await service.list_requests(ctx.ws, group, limit)


@router.get("/api/requests/{request_id}", response_model=sc.RequestOut)
async def get_request(request_id: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return {"request": await service.get_request_view(ctx.ws, request_id)}


@router.post("/api/requests/{request_id}/answers", response_model=sc.ResultOut,
             responses={409: {"description": "refused"}})
async def answer(request_id: str, body: sc.AnswerIn, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.answer(ctx.ws, request_id, body.questionId, body.value, ctx.actor(), ctx.idempotency_key)
    return action_response(result)


def _revision(ws: str, request_id: str, n: int | None) -> dict[str, Any] | None:
    if n is None:
        return None
    with session_scope() as s:
        row = s.scalar(select(m.TicketRevision).join(m.Request, m.Request.id == m.TicketRevision.request_id)
                       .where(m.Request.workspace_id == ws, m.TicketRevision.request_id == request_id,
                              m.TicketRevision.n == n))
        return service.revision_view(row) if row else None


@router.post("/api/requests/{request_id}/ticket/revisions", response_model=sc.RevisionResult,
             responses={409: {"description": "refused"}})
async def revise_ticket(request_id: str, body: sc.RevisionIn, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.edit_ticket(ctx.ws, request_id, body.content.model_dump(), ctx.actor(),
                                       ctx.idempotency_key)
    n = (result.get("revision") or {}).get("n")
    revision = await asyncio.to_thread(_revision, ctx.ws, request_id, n)
    return action_response(result, {"revision": revision})


def _revisions(ws: str, request_id: str) -> dict[str, Any]:
    from actron.flow.ticket import diff_contents

    with session_scope() as s:
        if s.scalar(select(m.Request.id).where(m.Request.id == request_id, m.Request.workspace_id == ws)) is None:
            raise service.NotFound(f"Request {request_id} was not found.")
        rows = s.scalars(select(m.TicketRevision).where(m.TicketRevision.request_id == request_id)
                         .order_by(m.TicketRevision.n)).all()
        revisions = [service.revision_view(r) for r in rows]
        diffs = [{"from": a.n, "to": b.n, "changes": diff_contents(dict(a.content), dict(b.content))}
                 for a, b in itertools.pairwise(rows)]
        return {"revisions": revisions, "diffs": diffs}


@router.get("/api/requests/{request_id}/ticket/revisions", response_model=sc.RevisionList)
async def list_revisions(request_id: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return await asyncio.to_thread(_revisions, ctx.ws, request_id)


@router.post("/api/requests/{request_id}/approvals", response_model=sc.ResultOut,
             responses={202: {"description": "pending"}, 403: {"description": "not an approver"},
                        409: {"description": "refused"}})
async def approve(request_id: str, body: sc.ApprovalIn, ctx: Ctx = Depends(writer)) -> Response:
    target = body.revisionHash if body.kind == "ticket" else body.headSha
    if not target:
        field = "revisionHash" if body.kind == "ticket" else "headSha"
        raise ApiError(422, "invalid", f"{field} is required for a {body.kind} approval.",
                       {"fields": [{"field": field, "message": "required"}]})
    result = await service.approve(ctx.ws, request_id, body.kind, target, ctx.actor(), ctx.idempotency_key)
    return action_response(result)


@router.post("/api/requests/{request_id}/feedback", response_model=sc.ResultOut,
             responses={409: {"description": "refused"}})
async def feedback(request_id: str, body: sc.FeedbackIn, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.feedback(ctx.ws, request_id, body.text, body.headSha, ctx.actor(), ctx.idempotency_key)
    return action_response(result)


@router.post("/api/requests/{request_id}/cancel", response_model=sc.ResultOut,
             responses={409: {"description": "refused"}})
async def cancel(request_id: str, body: sc.ReasonIn | None = None, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.cancel(ctx.ws, request_id, body.reason if body else None, ctx.actor(), ctx.idempotency_key)
    return action_response(result)


@router.post("/api/requests/{request_id}/retry", response_model=sc.ResultOut,
             responses={409: {"description": "refused"}})
async def retry(request_id: str, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.retry(ctx.ws, request_id, ctx.actor(), ctx.idempotency_key)
    return action_response(result)


@router.post("/api/requests/{request_id}/close-pr", response_model=sc.ResultOut,
             responses={409: {"description": "refused"}})
async def close_pr(request_id: str, body: sc.ReasonIn | None = None, ctx: Ctx = Depends(writer)) -> Response:
    result = await service.close_pr(ctx.ws, request_id, body.reason if body else None, ctx.actor(),
                                    ctx.idempotency_key)
    return action_response(result)


@router.get("/api/requests/{request_id}/pr/diff", response_model=sc.PrDiff)
async def pr_diff(request_id: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    view = await service.get_request_view(ctx.ws, request_id)
    pr = view.get("pr")
    if not pr:
        raise ApiError(404, "no_pr", "This request has no pull request yet.")
    from actron.activities.request import ExternalError, _github_cfg, _github_client, _with_retry

    cfg = _github_cfg(ctx.ws)
    repo = cfg.get("fork") or cfg.get("repository")
    if not repo or not cfg.get("token"):
        raise ApiError(503, "github_not_connected", "GitHub is not connected, so the diff cannot be read.")

    async def call() -> list[dict[str, Any]]:
        client = _github_client(cfg)
        try:
            data: list[dict[str, Any]] = await client.get_json(f"/repos/{repo}/pulls/{pr['number']}/files",
                                                               {"per_page": 100})
            return data
        finally:
            await client.aclose()

    try:
        files = await _with_retry(call, what="GitHub PR files")
    except ExternalError as exc:
        raise ApiError(502, "github_error", "GitHub did not return the diff. Try again.") from exc
    return {"files": [{"path": f.get("filename", ""), "status": f.get("status", "modified"),
                       "additions": int(f.get("additions") or 0), "deletions": int(f.get("deletions") or 0),
                       "patch": f.get("patch") or ""} for f in files], "headSha": pr.get("headSha", "")}


def _log_path(ws: str, request_id: str, build_id: str) -> str | None:
    with session_scope() as s:
        row = s.scalar(select(m.BuildRun).join(m.Request, m.Request.id == m.BuildRun.request_id)
                       .where(m.Request.workspace_id == ws, m.BuildRun.request_id == request_id,
                              m.BuildRun.id == build_id))
        return row.log_path if row else None


def _read_log(p: Path) -> str:
    """A file as it is; a build folder as Pi's output for every attempt, in order (pi-attempt-N.jsonl/.stderr)."""
    if p.is_file():
        return p.read_text("utf-8", "replace")
    parts: list[str] = []

    def attempt_no(f: Path) -> int:
        digits = "".join(ch for ch in f.stem if ch.isdigit())
        return int(digits or 0)

    for f in sorted(p.glob("pi-attempt-*"), key=lambda f: (attempt_no(f), f.suffix)):
        body = f.read_text("utf-8", "replace")
        if body.strip():
            parts.append(f"== {f.name}\n{body}")
    return "\n".join(parts) or "No log was recorded for this build.\n"


@router.get("/api/requests/{request_id}/builds/{build_id}/log", response_class=PlainTextResponse)
async def build_log(request_id: str, build_id: str, ctx: Ctx = Depends(current)) -> PlainTextResponse:
    path = await asyncio.to_thread(_log_path, ctx.ws, request_id, build_id)
    if path is None:
        raise ApiError(404, "not_found", "Build not found.")
    p = Path(path) if path else None
    if p is None or not (p.is_file() or p.is_dir()):
        return PlainTextResponse("No log was recorded for this build.\n")
    text = await asyncio.to_thread(_read_log, p)
    from actron.config import get_settings
    from actron.logging import Redactor

    redactor = Redactor()
    redactor.add(get_settings().secret_values())
    return PlainTextResponse(redactor.scrub(text[-2_000_000:]))
