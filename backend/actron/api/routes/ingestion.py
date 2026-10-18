"""Ingestion status and run history (spec B, B.C7; spec A, A.C5, A.C6)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from actron.api.deps import Ctx, current
from actron.api.routes.connections import _sync_view
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow.events import iso
from actron.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["ingestion"])

_LINKING_KEYS = {"referencesResolved": "references_resolved", "pending": "pending", "decisions": "decisions",
                 "identities": "identities", "linksKept": "links_kept", "linksDropped": "links_dropped"}


def _graph_totals(ws: str) -> dict[str, int]:
    from actron.graph.store import store_for

    try:
        store = store_for(ws)
        nodes = store.query("MATCH (n) RETURN count(n) AS c", read_only=True, timeout_ms=5000)
        links = store.query("MATCH ()-[r]->() RETURN count(r) AS c", read_only=True, timeout_ms=5000)
        return {"nodes": int(nodes[0]["c"]) if nodes else 0, "links": int(links[0]["c"]) if links else 0}
    except Exception as exc:
        log.warning("graph totals unavailable", extra={"error": type(exc).__name__})
        return {"nodes": 0, "links": 0}


def _status(ws: str) -> dict[str, Any]:
    with session_scope() as s:
        rows = s.scalars(select(m.Connection).where(m.Connection.workspace_id == ws)
                         .order_by(m.Connection.created_at)).all()
        sources = []
        for row in rows:
            v = _sync_view(s, ws, row)
            sources.append({"provider": row.provider, "state": v["state"], "counts": v["counts"],
                            "perMinute": v["perMinute"], "lastSyncedAt": v["lastSyncedAt"], "reason": v["reason"],
                            "runId": v["runId"]})
        linking_payload = s.execute(text(
            "SELECT payload FROM events WHERE workspace_id = :ws AND request_id IS NULL "
            "AND type = 'linking.finished' ORDER BY id DESC LIMIT 1"), {"ws": ws}).scalar() or {}
    counts = dict((linking_payload or {}).get("counts") or {})
    linking = {k: int(counts.get(v, counts.get(k, 0)) or 0) for k, v in _LINKING_KEYS.items()}
    connected = [x for x in sources if x["state"] != "NOT CONNECTED"]
    done = [x for x in connected if x["state"] in ("UP TO DATE", "PARTIAL")]
    percent = round(100 * len(done) / len(connected)) if connected else 0
    return {"sources": sources, "linking": linking, "memoryPercent": percent, "totals": _graph_totals(ws)}


@router.get("/api/ingestion/status")
async def ingestion_status(ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return await asyncio.to_thread(_status, ctx.ws)


def _runs(ws: str, source: str | None, limit: int) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(m.SyncRun).where(m.SyncRun.workspace_id == ws)
        if source:
            q = q.where(m.SyncRun.source == source)
        rows = s.scalars(q.order_by(m.SyncRun.started_at.desc()).limit(limit)).all()
        return [{"id": str(r.id), "source": r.source, "mode": r.mode, "status": r.status,
                 "startedAt": iso(r.started_at), "finishedAt": iso(r.finished_at),
                 "items": {k: int(v) for k, v in (r.items or {}).items() if isinstance(v, int | float)},
                 "errors": [{"action": str(e.get("action", "")), "error": str(e.get("error", "")),
                             **({"url": e["url"]} if e.get("url") else {}), "at": str(e.get("at", ""))}
                            for e in (r.errors or []) if isinstance(e, dict)],
                 "reason": r.reason} for r in rows]


@router.get("/api/ingestion/runs")
async def ingestion_runs(source: str | None = None, limit: int = Query(20, ge=1, le=200),
                         ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return {"runs": await asyncio.to_thread(_runs, ctx.ws, source, limit)}
