"""Write-back (spec B, B10): after the PR is approved (or merged), record what was delivered in the graph.

Ingests the PR (W3's mapping, A8 for one PR) and links the request, build, investigation, procedures and the
functions the build touched. Every write is a MERGE, so running it twice creates nothing new (B-AC-50); the
procedure's `successCount` goes up only when its `LEARNED_FROM_BUILD` link is new.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from actron.db import models as m
from actron.db.session import session_scope
from actron.graph import ids
from actron.graph.store import LinkRow, store_for
from actron.logging import get_logger

log = get_logger(__name__)
EXPLICIT = {"method": "explicit", "confidence": 1.0}


def _ctx(request_id: str, build_id: str | None) -> dict[str, Any]:
    with session_scope() as s:
        req = s.get(m.Request, request_id)
        if req is None:
            raise LookupError(request_id)
        build = s.get(m.BuildRun, build_id) if build_id else None
        if build is None:
            build = s.scalar(select(m.BuildRun).where(m.BuildRun.request_id == request_id)
                             .order_by(m.BuildRun.started_at.desc()).limit(1))
        data = dict(req.data or {})
        return {
            "ws": req.workspace_id, "title": req.title, "data": data,
            "build": None if build is None else {
                "id": build.id, "status": build.status, "branch": build.branch, "baseSha": build.base_sha,
                "headSha": build.head_sha, "testsPassed": build.tests_passed, "testsFailed": build.tests_failed,
                "startedAt": build.started_at, "finishedAt": build.finished_at,
                "filesChanged": list((build.report or {}).get("filesChanged") or []),
            },
        }


async def ingest_pr(ws: str, repo: str, number: int) -> dict[str, int]:
    """Fetch one PR with its files and commits from GitHub and write it with W3's mapping."""
    from actron.activities.request import _github_cfg, _github_client, _with_retry
    from actron.connectors.common import Batch, write_generic
    from actron.connectors.github import map_pr_commits, map_pr_files, map_pull

    cfg = _github_cfg(ws)
    ingested = str(cfg.get("repository") or repo)

    async def fetch() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        client = _github_client(cfg)
        try:
            pr = await client.get_json(f"/repos/{repo}/pulls/{number}")
            files = await client.get_json(f"/repos/{repo}/pulls/{number}/files", {"per_page": 100})
            commits = await client.get_json(f"/repos/{repo}/pulls/{number}/commits", {"per_page": 100})
            return pr, files or [], commits or []
        finally:
            await client.aclose()

    pr, files, commits = await _with_retry(fetch, what="GitHub PR for write-back")
    b = Batch(step="writeback")
    repo_id = ((pr.get("base") or {}).get("repo") or {}).get("id") or 0
    map_pull(b, repo, repo_id, pr, None)
    map_pr_files(b, repo, number, files, ingested)
    map_pr_commits(b, repo, number, commits, ingested)
    result = await asyncio.to_thread(write_generic, ws, b)
    store = store_for(ws)
    await asyncio.to_thread(store.update_nodes, "GithubPullRequest",
                            [{"id": ids.github_pr(repo, number), "openedByActron": True}])
    return {"prs": 1, "commits": len(commits), "files": len(files), "links": result.links_created}


def _ensure_pr_node(ws: str, repo: str, pr: dict[str, Any], title: str) -> str:
    """Without GitHub access, keep a minimal PR record from what the build reported."""
    store = store_for(ws)
    pid = ids.github_pr(repo, int(pr["number"]))
    if store.get_node(pid) is None:
        now = datetime.now(UTC)
        store.upsert_nodes("GithubPullRequest", [{
            "id": pid, "number": int(pr["number"]), "title": title, "state": pr.get("state") or "open",
            "createdAt": now, "updatedAt": now, "url": pr.get("url") or "", "headSha": pr.get("headSha"),
            "openedByActron": True}], source="github")
    return pid


def link_build(ws: str, request_id: str, build_id: str | None, repo: str | None) -> dict[str, int]:
    """DELIVERED_BY, PRODUCED, HANDED_TO, USED_PROCEDURE, LEARNED_FROM_BUILD, BUILD_TOUCHED (idempotent)."""
    ctx = _ctx(request_id, build_id)
    data = ctx["data"]
    build = ctx["build"]
    store = store_for(ws)
    counts = {"prs": 0, "functions": 0, "procedures": 0}
    rid = ids.request(request_id)
    pr = data.get("pr")
    pid = None
    if pr and pr.get("number") and repo:
        pid = _ensure_pr_node(ws, repo, pr, ctx["title"])
        store.upsert_links("DELIVERED_BY", "Request", "GithubPullRequest", [LinkRow(rid, pid, EXPLICIT)])
        counts["prs"] = 1
    if build is None:
        return counts
    bid = ids.build(build["id"])
    store.upsert_nodes("BuildRun", [{
        "id": bid, "status": build["status"], "branch": build["branch"], "baseSha": build["baseSha"] or "unknown",
        "headSha": build["headSha"], "testsPassed": build["testsPassed"], "testsFailed": build["testsFailed"],
        "startedAt": build["startedAt"], "finishedAt": build["finishedAt"]}], source="actron")
    if pid:
        store.upsert_links("PRODUCED", "BuildRun", "GithubPullRequest", [LinkRow(bid, pid, EXPLICIT)])
    investigation = (data.get("investigation") or {}).get("investigationId")
    if investigation:
        store.upsert_links("HANDED_TO", "Investigation", "BuildRun",
                           [LinkRow(ids.investigation(str(investigation)) if ":" not in str(investigation)
                                    else str(investigation), bid, EXPLICIT)])
    procedures = [p["id"] for p in (data.get("findings") or {}).get("procedures") or [] if p.get("id")]
    for proc in procedures:
        store.upsert_links("USED_PROCEDURE", "BuildRun", "Procedure", [LinkRow(bid, proc, EXPLICIT)])
        existing = store.query("MATCH (p:Procedure {id: $p})-[r:LEARNED_FROM_BUILD]->(b:BuildRun {id: $b}) "
                               "RETURN count(r) AS c", {"p": proc, "b": bid}, read_only=True)
        if existing and int(existing[0]["c"]) > 0:
            continue
        res = store.upsert_links("LEARNED_FROM_BUILD", "Procedure", "BuildRun", [LinkRow(proc, bid, EXPLICIT)])
        if res.created:
            store.query("MATCH (p:Procedure {id: $p}) SET p.successCount = coalesce(p.successCount, 0) + 1, "
                        "p.lastUsedAt = $now", {"p": proc, "now": datetime.now(UTC).isoformat()})
            counts["procedures"] += 1
    files = list(build.get("filesChanged") or (data.get("build") or {}).get("filesChanged") or [])
    code_repo = repo
    try:
        from actron.activities.request import _github_cfg

        code_repo = str(_github_cfg(ws).get("repository") or repo or "")
    except Exception:
        pass
    if files and code_repo:
        prefixes = [f"code:fn:{code_repo.lower()}:{f}::" for f in files]
        rows = store.query("MATCH (f:CodeFunction) WHERE any(p IN $prefixes WHERE f.id STARTS WITH p) "
                           "AND coalesce(f.deleted, false) = false RETURN f.id AS id LIMIT 500",
                           {"prefixes": prefixes}, read_only=True)
        fn_ids = [r["id"] for r in rows]
        if fn_ids:
            store.upsert_links("BUILD_TOUCHED", "BuildRun", "CodeFunction", [LinkRow(bid, f, EXPLICIT) for f in fn_ids])
        counts["functions"] = len(fn_ids)
    return counts
