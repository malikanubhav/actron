"""Connections (spec A, A11; spec B, B.C7): connect, change, disconnect, sync now, reset cursor.

Secrets are encrypted at rest and never returned; responses carry `secretLast4` only (A-AC-8).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select, text

from actron.api.deps import ApiError, Ctx, current, once, writer
from actron.config import get_settings
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow.events import iso
from actron.flow.service import get_gateway
from actron.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["connections"])

PROVIDERS = ("github", "code", "slack", "linear", "slack_export")
SECRET_KEYS = {"github": ("access_token", "token", "webhook_secret"), "code": ("access_token", "token"),
               "slack": ("bot_token", "app_token", "signing_secret"), "linear": ("api_key",), "slack_export": ()}
MAIN_SECRET = {"github": "access_token", "code": "access_token", "slack": "bot_token", "linear": "api_key"}
_SECRETISH = re.compile(r"(?i)(token|secret|key|password)")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (config or {}).items() if not _SECRETISH.search(k) or k in ("ticket_label",)}


def _sync_view(s: Any, ws: str, row: m.Connection) -> dict[str, Any]:
    run = s.scalar(select(m.SyncRun).where(m.SyncRun.workspace_id == ws, m.SyncRun.source == row.provider)
                   .order_by(m.SyncRun.started_at.desc()).limit(1))
    last_done = s.scalar(select(m.SyncRun.finished_at).where(
        m.SyncRun.workspace_id == ws, m.SyncRun.source == row.provider, m.SyncRun.status.in_(["done", "partial"]))
        .order_by(m.SyncRun.finished_at.desc()).limit(1))
    progress = s.execute(text(
        "SELECT payload FROM events WHERE workspace_id = :ws AND request_id IS NULL AND type = 'ingestion.progress' "
        "AND payload->>'source' = :src ORDER BY id DESC LIMIT 1"), {"ws": ws, "src": row.provider}).scalar()
    if row.status == "disconnected":
        state = "NOT CONNECTED"
    elif row.status == "error" or (run is not None and run.status == "failed"):
        state = "FAILED"
    elif run is None:
        state = "BACKFILLING"
    elif run.status == "running":
        state = "BACKFILLING" if run.mode == "backfill" else "SYNCING"
    elif run.status == "partial":
        state = "PARTIAL"
    else:
        state = "UP TO DATE"
    reason = run.reason if run is not None else None
    if not reason and run is not None and run.errors and state in ("PARTIAL", "FAILED"):
        reason = str((run.errors[-1] or {}).get("error", ""))[:300]
    counts = {k: int(v) for k, v in ((run.items if run else {}) or {}).items() if isinstance(v, int | float)}
    return {"state": state, "lastSyncedAt": iso(last_done), "reason": reason,
            "perMinute": float((progress or {}).get("perMinute") or 0), "counts": counts,
            "runId": str(run.id) if run else None}


def connection_view(s: Any, ws: str, row: m.Connection) -> dict[str, Any]:
    sync = _sync_view(s, ws, row)
    sync.pop("runId", None)
    return {"id": str(row.id), "provider": row.provider, "status": row.status, "config": _public_config(row.config),
            "secretLast4": row.secret_last4, "createdAt": iso(row.created_at), "updatedAt": iso(row.updated_at),
            "sync": sync}


def _list(ws: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.scalars(select(m.Connection).where(m.Connection.workspace_id == ws)
                         .order_by(m.Connection.created_at)).all()
        return [connection_view(s, ws, r) for r in rows]


@router.get("/api/connections")
async def list_connections(ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return {"connections": await asyncio.to_thread(_list, ctx.ws)}


async def _validate(provider: str, config: dict[str, Any], secret: dict[str, Any]) -> dict[str, Any]:
    try:
        from actron.connectors import forms
    except Exception:
        return {}
    form_provider = "github" if provider == "code" else provider
    result = await forms.validate(form_provider, {**config, **secret})
    d: dict[str, Any] = result.as_dict()
    if not d.get("ok"):
        errors = [{"field": k, "message": v} for k, v in (d.get("field_errors") or {}).items()]
        raise ApiError(422, "validation_failed", str(d.get("message") or "The connection did not validate."),
                       {"fields": errors})
    details: dict[str, Any] = dict(d.get("details") or {})
    return details


async def _slack_team(ws: str, config: dict[str, Any], details: dict[str, Any]) -> None:
    """B11a: a token-form Slack connection must belong to the workspace's team (adopted on first connect)."""
    team_id = details.get("team_id") or config.get("teamId")
    if not team_id:
        return
    config["teamId"] = str(team_id)
    if details.get("team"):
        config.setdefault("teamName", details.get("team"))
    if details.get("bot_user_id"):
        config.setdefault("botUserId", details.get("bot_user_id"))
    try:
        from actron.integrations import slack_oauth
    except Exception:
        return
    try:
        await slack_oauth.ensure_team(ws, str(team_id))
    except slack_oauth.TeamMismatch as exc:
        raise ApiError(409, "team_mismatch", str(exc)) from exc


def _store(ws: str, providers: list[str], config: dict[str, Any], secret: dict[str, Any]) -> list[str]:
    from actron.db.crypto import encrypt_secret, last4

    with session_scope() as s:
        ids_: list[str] = []
        for provider in providers:
            row = s.scalar(select(m.Connection).where(m.Connection.workspace_id == ws,
                                                      m.Connection.provider == provider))
            if row is not None and row.status != "disconnected":
                raise ApiError(409, "already_connected", f"{provider} is already connected.")
            main = secret.get(MAIN_SECRET.get(provider, ""), "")
            enc = encrypt_secret(secret) if secret else None
            if row is None:
                row = m.Connection(workspace_id=ws, provider=provider)
                s.add(row)
            row.status = "connected"
            row.config = config
            row.secret_encrypted = enc
            row.secret_last4 = last4(str(main)) if main else None
            row.updated_at = datetime.now(UTC)
            s.flush()
            ids_.append(str(row.id))
        return ids_


async def _save_upload(ws: str, upload: Any) -> str:
    base = get_settings().ACTRON_CLONE_DIR.parent / "uploads" / ws
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid.uuid4().hex}.zip"
    size = 0
    with path.open("wb") as fh:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                path.unlink(missing_ok=True)
                raise ApiError(413, "too_large", "The export is larger than 500 MB.")
            fh.write(chunk)
    return str(path)


@router.post("/api/connections", status_code=201,
             responses={409: {"description": "already connected"}, 422: {"description": "invalid"}})
async def create_connection(request: Request, ctx: Ctx = Depends(writer)) -> Response:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        provider = str(form.get("provider") or "")
        if provider != "slack_export":
            raise ApiError(422, "invalid", "Uploads are only accepted for the Slack export.")
        archive = form.get("archive")
        if archive is None or not hasattr(archive, "read"):
            raise ApiError(422, "invalid", "Attach the Slack export archive.", {"fields": [{"field": "archive",
                                                                                          "message": "required"}]})
        saved = await _save_upload(ctx.ws, archive)
        try:
            from actron.connectors.slack_export import validate_export

            await asyncio.to_thread(validate_export, Path(saved))
        except ImportError:
            pass
        except Exception as exc:
            Path(saved).unlink(missing_ok=True)
            raise ApiError(422, "invalid_export", f"The Slack export could not be read: {exc}"[:300],
                           {"fields": [{"field": "archive", "message": "not a valid Slack export"}]}) from exc
        config: dict[str, Any] = {"path": saved, "archivePath": saved,
                                  "filename": getattr(archive, "filename", None)}
        if form.get("events"):
            config["events"] = str(form.get("events"))
        secret: dict[str, Any] = {}
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise ApiError(422, "invalid", "The body must be JSON.") from exc
        if not isinstance(body, dict):
            raise ApiError(422, "invalid", "The body must be a JSON object.")
        provider = str(body.get("provider") or "")
        config = dict(body.get("config") or {})
        secret = {k: v for k, v in dict(body.get("secret") or {}).items() if v}
    if provider not in PROVIDERS:
        raise ApiError(422, "invalid", "Unknown provider.", {"fields": [{"field": "provider", "message": "unknown"}]})

    async def run() -> dict[str, Any]:
        if provider in ("github", "code"):
            # The Connect form sends field ids (`working_branch`, C12); the API's own name is `workingBranch`.
            if not config.get("workingBranch") and config.get("working_branch"):
                config["workingBranch"] = config.pop("working_branch")
            if not config.get("workingBranch"):
                raise ApiError(422, "invalid", "Choose a working branch.",
                               {"fields": [{"field": "workingBranch", "message": "required"}]})
            if not secret.get("webhook_secret"):
                try:
                    from actron.connectors.forms import generate_webhook_secret

                    secret["webhook_secret"] = generate_webhook_secret()
                except Exception:
                    pass
        if provider != "slack_export":
            details = await _validate(provider, config, secret)
            if provider == "slack":
                await _slack_team(ctx.ws, config, details)
        providers = ["code", "github"] if provider in ("github", "code") else [provider]
        ids_ = await asyncio.to_thread(_store, ctx.ws, providers, config, secret)
        run_id = ""
        gateway = get_gateway()
        for p in providers:
            try:
                wf = await gateway.start_source_sync(ctx.ws, p, "backfill")
                run_id = run_id or wf
                await gateway.ensure_schedule(ctx.ws, p)
            except Exception as exc:
                log.warning("sync start failed", extra={"source": p, "error": type(exc).__name__})
        primary = ids_[-1] if provider in ("github", "code") else ids_[0]
        return {"connection": await asyncio.to_thread(_view_by_id, ctx.ws, primary), "runId": run_id}

    result = await once(ctx, "create_connection", run)
    return JSONResponse(result, status_code=201)


def _view_by_id(ws: str, conn_id: str) -> dict[str, Any]:
    with session_scope() as s:
        row = _row(s, ws, conn_id)
        return connection_view(s, ws, row)


def _row(s: Any, ws: str, conn_id: str) -> m.Connection:
    try:
        cid = uuid.UUID(conn_id)
    except ValueError:
        raise ApiError(404, "not_found", "Connection not found.") from None
    row: m.Connection | None = s.get(m.Connection, cid)
    if row is None or row.workspace_id != ws:
        raise ApiError(404, "not_found", "Connection not found.")
    return row


class _Patch:
    pass


@router.patch("/api/connections/{conn_id}")
async def patch_connection(conn_id: str, request: Request, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ApiError(422, "invalid", "The body must be JSON.") from exc
    partial = body.get("config") if isinstance(body, dict) else None
    if not isinstance(partial, dict) or not partial:
        raise ApiError(422, "invalid", "Send {config: {...}} with the fields to change.")
    partial = {k: v for k, v in partial.items() if not _SECRETISH.search(k)}

    def apply() -> tuple[str, bool]:
        with session_scope() as s:
            row = _row(s, ctx.ws, conn_id)
            old_branch = (row.config or {}).get("workingBranch")
            rows = [row]
            if row.provider in ("github", "code"):
                rows = list(s.scalars(select(m.Connection).where(m.Connection.workspace_id == ctx.ws,
                                                                 m.Connection.provider.in_(["github", "code"]))))
            for r in rows:
                r.config = {**(r.config or {}), **partial}
                r.updated_at = datetime.now(UTC)
            changed = "workingBranch" in partial and partial["workingBranch"] != old_branch
            return row.provider, changed

    _, reingest = await asyncio.to_thread(apply)
    if reingest:
        try:
            await get_gateway().start_source_sync(ctx.ws, "code", "backfill")
        except Exception as exc:
            log.warning("re-ingest start failed", extra={"error": type(exc).__name__})
    out: dict[str, Any] = {"connection": await asyncio.to_thread(_view_by_id, ctx.ws, conn_id)}
    if reingest:
        out["reingest"] = True
    return out


@router.delete("/api/connections/{conn_id}", status_code=204)
async def delete_connection(conn_id: str, ctx: Ctx = Depends(writer)) -> Response:
    def apply() -> list[str]:
        with session_scope() as s:
            row = _row(s, ctx.ws, conn_id)
            rows = [row]
            if row.provider in ("github", "code"):
                rows = list(s.scalars(select(m.Connection).where(m.Connection.workspace_id == ctx.ws,
                                                                 m.Connection.provider.in_(["github", "code"]))))
            for r in rows:
                r.status = "disconnected"
                r.secret_encrypted = None
                r.secret_last4 = None
            return [r.provider for r in rows]

    for provider in await asyncio.to_thread(apply):
        try:
            await get_gateway().pause_schedule(ctx.ws, provider)
        except Exception as exc:
            log.info("schedule pause skipped", extra={"source": provider, "error": type(exc).__name__})
    return Response(status_code=204)


@router.post("/api/connections/{conn_id}/sync", status_code=202)
async def sync_now(conn_id: str, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    def load() -> tuple[str, str]:
        with session_scope() as s:
            row = _row(s, ctx.ws, conn_id)
            return row.provider, row.status

    provider, status = await asyncio.to_thread(load)
    if status == "disconnected":
        raise ApiError(409, "disconnected", "Connect this source again before syncing.")
    gateway = get_gateway()
    try:
        if provider == "slack_export":
            await gateway.start_source_sync(ctx.ws, provider, "backfill")
        else:
            # One repository form makes the `code` and `github` rows; the card's Sync now refreshes both.
            for p in (["code", "github"] if provider in ("code", "github") else [provider]):
                await gateway.trigger_schedule(ctx.ws, p)
    except Exception as exc:
        raise ApiError(503, "temporal_unavailable", "The sync could not be started. Try again shortly.") from exc
    return {"triggered": True}


@router.post("/api/connections/{conn_id}/reset-cursor")
async def reset_cursor(conn_id: str, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    def apply() -> dict[str, Any]:
        with session_scope() as s:
            row = _row(s, ctx.ws, conn_id)
            s.execute(delete(m.SyncCursor).where(m.SyncCursor.workspace_id == ctx.ws,
                                                 m.SyncCursor.source == row.provider))
            return connection_view(s, ctx.ws, row)

    return {"connection": await asyncio.to_thread(apply)}

