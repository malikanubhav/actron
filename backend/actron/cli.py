"""`actron` command line (spec B, B12; PRD 16).

  actron ingest code --repo owner/name [--ws dev] [--branch B] [--url U] [--path LOCAL_CHECKOUT]
  actron ingest slack-export PATH [--ws dev]
  actron sync SOURCE [--ws dev]
  actron status [--ws dev]
  actron serve [--host H] [--port P]
  actron worker [--queues ingest,link,request,build]
  actron query "MATCH (n) RETURN count(n)" [--ws dev]
  actron seed-dev
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from actron.config import get_settings


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def seed_dev() -> dict[str, Any]:
    """Create the `dev` workspace row and its graph indexes. No sample data."""
    from actron.db import models as m
    from actron.db.session import session_scope
    from actron.graph import ids
    from actron.graph.ontology import default_ontology, ensure_indexes
    from actron.graph.store import store_for

    with session_scope() as s:
        row = s.get(m.Workspace, "dev")
        created = row is None
        if row is None:
            s.add(m.Workspace(id="dev", name="Development", settings={},
                              graph_name=ids.graph_name(get_settings().FALKORDB_GRAPH_PREFIX, "dev")))
    ensure_indexes(store_for("dev"), default_ontology())
    return {"workspace": "dev", "created": created, "indexes": "ensured"}


async def ingest_code(ws: str, repo: str, branch: str | None, url: str | None, path: str | None) -> dict[str, Any]:
    from actron.connectors.code.pipeline import ingest_code as run
    from actron.flow.events import publish_workspace_event

    async def emit(type: str, payload: dict[str, Any], *, actor: str = "actron", surface: str = "system") -> None:
        print(f"{type}: {json.dumps(payload, default=str)[:200]}", file=sys.stderr)
        await publish_workspace_event(ws, type, payload)

    s = get_settings()
    report = await run(ws, repo, url=url, branch=branch, clone_dir=s.ACTRON_CLONE_DIR,
                       depth=s.ACTRON_GIT_HISTORY_DEPTH, token=s.GITHUB_TOKEN, emit=emit,
                       repo_dir=Path(path) if path else None)
    return dict(vars(report)) if hasattr(report, "__dict__") else {"report": str(report)}


async def ingest_slack_export(ws: str, path: str) -> dict[str, Any]:
    """Register the export as the workspace's `slack_export` connection and start its import workflow."""
    from sqlalchemy import select

    from actron.db import models as m
    from actron.db.session import session_scope
    from actron.flow.service import get_gateway

    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"{p} does not exist")
    try:
        from actron.connectors.slack_export import validate_export

        report = validate_export(p) if p.is_file() else None
    except ImportError:
        report = None
    with session_scope() as s:
        row = s.scalar(select(m.Connection).where(m.Connection.workspace_id == ws,
                                                  m.Connection.provider == "slack_export"))
        if row is None:
            row = m.Connection(workspace_id=ws, provider="slack_export")
            s.add(row)
        row.status = "connected"
        row.config = {"path": str(p), "archivePath": str(p), "filename": p.name}
    wf = await get_gateway().start_source_sync(ws, "slack_export", "backfill")
    return {"workflowId": wf, "path": str(p), "validation": vars(report) if report is not None else None,
            "note": "The import runs on the worker (`actron worker`)."}


async def sync(ws: str, source: str) -> dict[str, Any]:
    from actron.flow.service import get_gateway

    gateway = get_gateway()
    try:
        await gateway.trigger_schedule(ws, source)
        return {"triggered": source}
    except Exception:
        wf = await gateway.start_source_sync(ws, source, "incremental")
        return {"started": wf}


def status(ws: str) -> dict[str, Any]:
    from actron.api.routes.ingestion import _status

    return _status(ws)


def query(ws: str, cypher: str) -> list[dict[str, Any]]:
    from actron.graph.store import store_for

    return store_for(ws).query(cypher, read_only=True, timeout_ms=30000)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="actron", description="Actron command line.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest", help="ingest a source now")
    ing_sub = ing.add_subparsers(dest="what", required=True)
    code = ing_sub.add_parser("code", help="clone and ingest a repository")
    code.add_argument("--repo", required=True, help="owner/name")
    code.add_argument("--ws", default="dev")
    code.add_argument("--branch")
    code.add_argument("--url")
    code.add_argument("--path", help="use an existing local checkout")
    exp = ing_sub.add_parser("slack-export", help="import a Slack export (zip or folder)")
    exp.add_argument("path")
    exp.add_argument("--ws", default="dev")
    sy = sub.add_parser("sync", help="trigger a source's incremental sync")
    sy.add_argument("source", choices=["code", "github", "slack", "linear"])
    sy.add_argument("--ws", default="dev")
    st = sub.add_parser("status", help="ingestion status")
    st.add_argument("--ws", default="dev")
    sv = sub.add_parser("serve", help="run the API")
    sv.add_argument("--host", default=None)
    sv.add_argument("--port", type=int, default=None)
    wk = sub.add_parser("worker", help="run the Temporal workers")
    wk.add_argument("--queues", default="ingest,link,request,build")
    q = sub.add_parser("query", help="read-only Cypher against a workspace graph")
    q.add_argument("cypher")
    q.add_argument("--ws", default="dev")
    sub.add_parser("seed-dev", help="create the dev workspace and graph indexes (no data)")
    return p


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "ingest" and args.what == "code":
        _print(asyncio.run(ingest_code(args.ws, args.repo, args.branch, args.url, args.path)))
    elif args.cmd == "ingest":
        _print(asyncio.run(ingest_slack_export(args.ws, args.path)))
    elif args.cmd == "sync":
        _print(asyncio.run(sync(args.ws, args.source)))
    elif args.cmd == "status":
        _print(status(args.ws))
    elif args.cmd == "serve":
        import uvicorn

        s = get_settings()
        uvicorn.run("actron.api.app:app", host=args.host or s.ACTRON_HOST, port=args.port or s.ACTRON_PORT)
    elif args.cmd == "worker":
        from actron.worker import main as worker_main

        worker_main(["--queues", args.queues])
    elif args.cmd == "query":
        _print(query(args.ws, args.cypher))
    elif args.cmd == "seed-dev":
        _print(seed_dev())


if __name__ == "__main__":
    main()
