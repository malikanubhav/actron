"""Graph routes (spec B, B.C7): request subgraph, node inspector, neighbours, search, path, sample, stats,
quick queries. Everything is read-only and scoped to the caller's workspace graph."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from actron.api.deps import ApiError, Ctx, current
from actron.graph import ids
from actron.graph.store import store_for

router = APIRouter(tags=["graph"])
QUICK_TOOLS = ("callers", "owners", "decisions_for", "shortest_path", "tests_for")
NAME_KEYS = ("title", "name", "qualifiedName", "statement", "identifier", "path", "text")
TIMEOUT_MS = 5000


def group_of(label: str) -> str:
    if label.startswith("Slack"):
        return "slack"
    if label.startswith("Linear"):
        return "linear"
    if label.startswith("Github"):
        return "github"
    if label.startswith(("Code", "Git")):
        return "code"
    return "core"


def _display(props: dict[str, Any]) -> str:
    for k in NAME_KEYS:
        v = props.get(k)
        if isinstance(v, str) and v:
            return v[:120]
    return str(props.get("id", ""))


def _label(node_id: str) -> str:
    try:
        return ids.label_of(node_id)
    except ids.InvalidId as exc:
        raise ApiError(404, "not_found", "That node id is not valid.") from exc


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    try:
        from actron.mcp_graph.tools import clean_properties

        return clean_properties(props)
    except Exception:
        return {k: (v[:4000] if isinstance(v, str) else v) for k, v in props.items() if not k.startswith("_")}


def _tool_ctx(ws: str) -> Any:
    from actron.mcp_graph.tools import ToolContext

    return ToolContext(ws=ws, store=store_for(ws), emit=None)


async def _tool(ws: str, name: str, args: dict[str, Any]) -> Any:
    try:
        from actron.mcp_graph.tools import call_tool
    except Exception as exc:
        raise ApiError(503, "not_ready", "Graph tools are not available in this build.") from exc
    out = await call_tool(_tool_ctx(ws), name, args)
    if isinstance(out, dict) and "error" in out and len(out) == 1:
        err = out["error"]
        raise ApiError(422 if err.get("code") in ("invalid", "bad_input") else 404, str(err.get("code", "error")),
                       str(err.get("message", "The graph query failed.")))
    return out


@router.get("/api/graph/subgraph")
async def subgraph(requestId: str, mode: Literal["aggregated", "expanded"] = "aggregated",
                   ctx: Ctx = Depends(current)) -> dict[str, Any]:
    from actron.flow.service import request_exists

    if not await asyncio.to_thread(request_exists, ctx.ws, requestId):
        raise ApiError(404, "not_found", f"Request {requestId} was not found.")
    from actron.graph import queries

    sg = await asyncio.to_thread(queries.subgraph_for_request, store_for(ctx.ws), requestId, mode)
    out: dict[str, Any] = sg.model_dump(by_alias=True, mode="json") if hasattr(sg, "model_dump") else dict(sg)
    return out


def _node(ws: str, node_id: str) -> dict[str, Any]:
    label = _label(node_id)
    store = store_for(ws)
    rows = store.query(f"MATCH (n:`{label}` {{id: $id}}) RETURN n LIMIT 1", {"id": node_id}, read_only=True,
                       timeout_ms=TIMEOUT_MS)
    if not rows:
        raise ApiError(404, "not_found", "That node is not in the graph.")
    props = {k: v for k, v in rows[0]["n"].items() if k != "_label"}
    out_rows = store.query(
        f"MATCH (n:`{label}` {{id: $id}})-[r]->(m) RETURN type(r) AS type, m.id AS to, r.method AS method, "
        "r.confidence AS confidence LIMIT 50", {"id": node_id}, read_only=True, timeout_ms=TIMEOUT_MS)
    in_rows = store.query(
        f"MATCH (n:`{label}` {{id: $id}})<-[r]-(m) RETURN type(r) AS type, m.id AS frm, r.method AS method, "
        "r.confidence AS confidence LIMIT 50", {"id": node_id}, read_only=True, timeout_ms=TIMEOUT_MS)
    sources = [{"type": k, "url": props[k]} for k in ("sourceUrl", "url") if isinstance(props.get(k), str)]
    return {
        "node": {"id": node_id, "type": label, "label": _display(props), "group": group_of(label),
                 "props": _clean(props)},
        "sources": sources[:1] if len(sources) == 2 and sources[0]["url"] == sources[1]["url"] else sources,
        "outgoing": [{"from": node_id, "to": r["to"], "type": r["type"], "method": r.get("method"),
                      "confidence": r.get("confidence")} for r in out_rows],
        "incoming": [{"from": r["frm"], "to": node_id, "type": r["type"], "method": r.get("method"),
                      "confidence": r.get("confidence")} for r in in_rows],
    }


@router.get("/api/graph/nodes/{node_id:path}/neighbours")
async def neighbours(node_id: str, types: str | None = None, limit: int = Query(50, ge=1, le=100),
                     ctx: Ctx = Depends(current)) -> dict[str, Any]:
    label = _label(node_id)
    wanted = [t for t in (types or "").split(",") if t]

    def run() -> dict[str, Any]:
        rows = store_for(ctx.ws).query(
            f"MATCH (n:`{label}` {{id: $id}})-[r]-(m) WHERE coalesce(m.deleted, false) = false "
            "RETURN m AS m, type(r) AS type, startNode(r).id AS a, endNode(r).id AS b, r.method AS method, "
            "r.confidence AS confidence LIMIT $limit",
            {"id": node_id, "limit": limit * 3 if wanted else limit}, read_only=True, timeout_ms=TIMEOUT_MS)
        nodes: dict[str, dict[str, Any]] = {}
        links = []
        for r in rows:
            mp = r["m"]
            mlabel = str(mp.get("_label") or _label(str(mp.get("id"))))
            if wanted and mlabel not in wanted:
                continue
            if len(nodes) >= limit and mp["id"] not in nodes:
                continue
            nodes[mp["id"]] = {"id": mp["id"], "type": mlabel, "label": _display(mp), "group": group_of(mlabel)}
            links.append({"from": r["a"], "to": r["b"], "type": r["type"], "method": r.get("method"),
                          "confidence": r.get("confidence")})
        center = _node(ctx.ws, node_id)["node"]
        center.pop("props", None)
        return {"mode": "expanded", "nodes": [center, *nodes.values()], "links": links,
                "truncated": len(rows) >= limit}

    return await asyncio.to_thread(run)


@router.get("/api/graph/nodes/{node_id:path}")
async def node(node_id: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    return await asyncio.to_thread(_node, ctx.ws, node_id)


@router.get("/api/graph/search")
async def search(q: str = Query(min_length=1, max_length=200), types: str | None = None,
                 limit: int = Query(20, ge=1, le=20), ctx: Ctx = Depends(current)) -> dict[str, Any]:
    args: dict[str, Any] = {"query": q, "limit": limit}
    if types:
        args["types"] = [t for t in types.split(",") if t]
    out = await _tool(ctx.ws, "search", args)
    return {"results": out if isinstance(out, list) else []}


@router.get("/api/graph/path")
async def path(from_: str = Query(alias="from"), to: str = Query(), maxHops: int = Query(6, ge=1, le=6),
               ctx: Ctx = Depends(current)) -> dict[str, Any]:
    _label(from_)
    _label(to)
    out = await _tool(ctx.ws, "shortest_path", {"fromId": from_, "toId": to, "maxHops": maxHops})
    if not isinstance(out, dict) or out.get("found") is False or not out.get("nodes"):
        return {"found": False, "nodes": [], "links": []}
    nodes = []
    for n in out.get("nodes") or []:
        t = str(n.get("type") or n.get("_label") or _label(str(n.get("id"))))
        nodes.append({"id": n.get("id"), "type": t, "label": n.get("label") or _display(n), "group": group_of(t)})
    links = [{"from": lk.get("from") or lk.get("fromId"), "to": lk.get("to") or lk.get("toId"), "type": lk.get("type"),
              "method": lk.get("method"), "confidence": lk.get("confidence")} for lk in out.get("links") or []]
    return {"found": True, "nodes": nodes, "links": links}


@router.get("/api/graph/sample")
async def sample(limit: int = Query(1000, ge=1, le=3000), ctx: Ctx = Depends(current)) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        rows = store_for(ctx.ws).query(
            "MATCH (a)-[r]->(b) WHERE coalesce(a.deleted, false) = false AND coalesce(b.deleted, false) = false "
            "RETURN a.id AS a, labels(a)[0] AS la, type(r) AS t, b.id AS b, labels(b)[0] AS lb LIMIT $limit",
            {"limit": limit}, read_only=True, timeout_ms=10000)
        nodes: dict[str, dict[str, Any]] = {}
        links = []
        for r in rows:
            for nid, lab in ((r["a"], r["la"]), (r["b"], r["lb"])):
                if nid not in nodes and len(nodes) < limit:
                    nodes[nid] = {"id": nid, "type": lab, "label": nid.rsplit(":", 1)[-1][:60], "group": group_of(lab)}
            if r["a"] in nodes and r["b"] in nodes:
                links.append({"from": r["a"], "to": r["b"], "type": r["t"], "method": None, "confidence": None})
        return {"mode": "expanded", "nodes": list(nodes.values()), "links": links, "truncated": len(rows) >= limit}

    return await asyncio.to_thread(run)


@router.get("/api/graph/stats")
async def stats(ctx: Ctx = Depends(current)) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        store = store_for(ctx.ws)
        by = store.query("MATCH (n) RETURN labels(n)[0] AS t, count(n) AS c ORDER BY c DESC", read_only=True,
                         timeout_ms=10000)
        links = store.query("MATCH ()-[r]->() RETURN count(r) AS c", read_only=True, timeout_ms=10000)
        onto = store.ontology
        return {
            "nodeTypes": len(by), "nodes": sum(int(r["c"]) for r in by),
            "links": int(links[0]["c"]) if links else 0,
            "byType": [{"type": r["t"], "group": group_of(str(r["t"])), "count": int(r["c"])} for r in by],
            "ontology": {"types": len(onto.nodes), "relationships": len(onto.relationships)},
        }

    return await asyncio.to_thread(run)


@router.get("/api/graph/quick/{tool}")
async def quick(tool: str, ids_: str = Query(alias="ids", min_length=1), depth: int | None = Query(None, ge=1, le=3),
                ctx: Ctx = Depends(current)) -> Any:
    if tool not in QUICK_TOOLS:
        raise ApiError(404, "unknown_tool", f"{tool} is not a quick query.")
    id_list = [i for i in ids_.split(",") if i]
    if tool == "callers":
        args: dict[str, Any] = {"functionId": id_list[0]}
        if depth:
            args["depth"] = depth
    elif tool == "shortest_path":
        if len(id_list) < 2:
            raise ApiError(422, "invalid", "shortest_path needs two ids.")
        args = {"fromId": id_list[0], "toId": id_list[1]}
    else:
        args = {"ids": id_list}
    return await _tool(ctx.ws, tool, args)
