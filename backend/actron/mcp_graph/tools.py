"""The 20 read-only graph tools (spec B, B.C4) as plain async functions with Pydantic inputs.

The MCP server (`actron.mcp_graph.server`), the investigator's pipeline, the API quick queries and the
context pack all call `call_tool(ctx, name, args)`. Every call:
- validates its input against the tool's Pydantic model (errors come back as `{"error": {code, message}}`);
- emits `tool.called` and `tool.result` through `ctx.emit` with the node ids it returned (B.C2);
- runs read-only with a 2 second limit and at most 200 rows;
- never returns secret-looking properties, and truncates long text properties to 4,000 characters;
- code tools say which snapshot they describe (`snapshot`: the commit the graph was built from) and mark
  files that differ on the build's target branch (`differs: true`).
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from actron.graph import ids
from actron.graph import queries as Q
from actron.graph.store import GraphTimeout
from actron.logging import get_logger

log = get_logger(__name__)

TIMEOUT_S = 2.0
MAX_ROWS = 200
MAX_TEXT = 4000
MAX_LINKS = 50
FILE_OUTLINE_LINES = 2000
MAX_RANGE_LINES = 400
SECRET_KEY_RE = re.compile(r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|credential)", re.I)


class EventSink(Protocol):
    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None: ...


@dataclass
class ToolContext:
    """Everything a tool call needs. One per investigator run or Pi build (scoped to one workspace)."""

    ws: str
    store: Any  # GraphStore (or anything with the same `query` method and an `ontology`)
    emit: EventSink | None = None
    run_token: str | None = None
    snapshot_sha: str | None = None
    differing_paths: frozenset[str] = frozenset()
    by: Literal["investigator", "pi"] = "investigator"
    repo_dir: Path | None = None
    search_fields: Mapping[str, list[str]] | None = None
    timeout_s: float = TIMEOUT_S
    returned_ids: set[str] = field(default_factory=set)
    calls: int = 0

    def fields(self) -> Mapping[str, list[str]]:
        if self.search_fields is None:
            self.search_fields = self.store.ontology.search_fields()
        return self.search_fields


class ToolFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


IdsField = Field(min_length=1, max_length=50, description="Node ids, for example ['code:fn:owner/repo:src/a.ts::run'].")


class SearchIn(_In):
    query: str = Field(min_length=1, max_length=500, description="Words to search for.")
    types: list[str] | None = Field(None, description="Node types to search, for example ['CodeFunction', 'Decision'].")
    limit: int = Field(10, ge=1, le=20)


class IdIn(_In):
    id: str = Field(min_length=3, description="A node id, for example 'code:fn:owner/repo:src/a.ts::run'.")


class FunctionDepthIn(_In):
    functionId: str = Field(min_length=3, description="A function id (code:fn:...).")
    depth: int = Field(3, ge=1, le=3)


class IdsDepthIn(_In):
    ids: list[str] = IdsField
    depth: int = Field(3, ge=1, le=3)


class IdsIn(_In):
    ids: list[str] = IdsField


class ShortestPathIn(_In):
    fromId: str = Field(min_length=3)
    toId: str = Field(min_length=3)
    maxHops: int = Field(6, ge=1, le=6)


class DecisionsIn(_In):
    ids: list[str] = IdsField
    includeSuperseded: bool = False


class CodeRangeIn(_In):
    path: str = Field(min_length=1, description="File path in the repository, for example 'src/extension.ts'.")
    startLine: int = Field(ge=1)
    endLine: int = Field(ge=1)


class PathIn(_In):
    path: str = Field(min_length=1, description="File path in the repository, for example 'src/extension.ts'.")


class FindSymbolIn(_In):
    name: str = Field(min_length=1, description="Function or class name, for example 'activate'.")
    kind: Literal["function", "class"] | None = None


class HistoryIn(_In):
    id: str = Field(min_length=3, description="A function or class id.")
    limit: int = Field(10, ge=1, le=20)


class CodeAtIn(_In):
    id: str = Field(min_length=3, description="A function or class id.")
    commitSha: str = Field(min_length=4, max_length=64, description="Commit sha (full or abbreviated).")


class SearchCodeIn(_In):
    query: str = Field(min_length=1, max_length=500)
    pathPrefix: str | None = None
    limit: int = Field(10, ge=1, le=20)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[_In]
    description: str
    run: Callable[[ToolContext, Any], Any]
    summary: Callable[[Any], str]


# ------------------------------------------------------------------------------------------- helpers


def _clean_value(value: Any, secrets: Iterable[str]) -> Any:
    if isinstance(value, str):
        for s in secrets:
            if s and s in value:
                value = value.replace(s, "[redacted]")
        if len(value) > MAX_TEXT:
            return value[:MAX_TEXT] + f"… [truncated, {len(value)} characters in total]"
        return value
    if isinstance(value, list):
        return [_clean_value(v, secrets) for v in value[:MAX_ROWS]]
    return value


def clean_properties(props: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secret-looking properties and internal keys; truncate long text to 4,000 characters."""
    from actron.config import get_settings

    secrets = get_settings().secret_values()
    out: dict[str, Any] = {}
    for key, value in props.items():
        if key.startswith("_") or SECRET_KEY_RE.search(key):
            continue
        out[key] = _clean_value(value, secrets)
    return out


def _node_ids_in(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if ":" in value and len(value) < 600:
            try:
                ids.parse_id(value)
            except ids.InvalidId:
                return
            out.add(value)
    elif isinstance(value, Mapping):
        for v in value.values():
            _node_ids_in(v, out)
    elif isinstance(value, list):
        for v in value:
            _node_ids_in(v, out)


def node_ids_in(value: Any) -> list[str]:
    found: set[str] = set()
    _node_ids_in(value, found)
    return sorted(found)


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _label(node_id: str) -> str:
    try:
        return ids.label_of(node_id)
    except ids.InvalidId:
        raise ToolFailure("invalid_input", f"{node_id!r} is not an Actron node id") from None


def _q(ctx: ToolContext, cypher: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.store.query(cypher, dict(params), read_only=True,
                                                  timeout_ms=int(ctx.timeout_s * 1000))
    return rows


def _snapshot(ctx: ToolContext) -> str | None:
    if ctx.snapshot_sha:
        return ctx.snapshot_sha
    try:
        rows = _q(ctx, "MATCH (r:CodeRepository) WHERE coalesce(r.deleted, false) = false "
                       "RETURN r.headSha AS sha LIMIT 1", {})
    except Exception:
        return None
    sha = rows[0].get("sha") if rows else None
    ctx.snapshot_sha = sha if isinstance(sha, str) else None
    return ctx.snapshot_sha


def _path_of(node_id: str) -> str | None:
    try:
        return ids.parse_id(node_id).parts.get("path")
    except ids.InvalidId:
        return None


def _numbered(text: str, start: int) -> str:
    return "\n".join(f"{start + i:>5}  {line}" for i, line in enumerate(text.split("\n")))


def _code_meta(ctx: ToolContext, path: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = {"snapshot": _snapshot(ctx)}
    if path and path in ctx.differing_paths:
        meta["differs"] = True
        meta["note"] = ("This file differs on the target branch; this is the working-branch snapshot. "
                        "Read the file from the checkout for the target branch version.")
    return meta


# ------------------------------------------------------------------------------------------- graph tools


def _search(ctx: ToolContext, inp: SearchIn) -> list[dict[str, Any]]:
    rows = Q.seeds_fulltext(ctx.store, inp.query, search_fields=ctx.fields(), types=inp.types, limit=inp.limit,
                            timeout_ms=int(ctx.timeout_s * 1000))
    return [{"id": r.id, "type": r.type, "label": r.label, "snippet": r.snippet, "score": r.score} for r in rows]


def _no_node(ctx: ToolContext, node_id: str) -> ToolFailure:
    """`not_found` for an id, naming real ids that end the same way (a wrong file in the id is the usual mistake)."""
    label = _label(node_id)
    name = node_id.rsplit("::", 1)[-1]
    similar: list[str] = []
    if name and name != node_id:
        rows = _q(ctx, f"MATCH (n:`{label}`) WHERE n.id ENDS WITH $suffix RETURN n.id AS id LIMIT 5",
                  {"suffix": f"::{name}"})
        similar = [str(r["id"]) for r in rows]
    hint = f" Did you mean: {', '.join(similar)}?" if similar else ""
    return ToolFailure("not_found", f"No node with id {node_id}.{hint}")


def _get_node(ctx: ToolContext, inp: IdIn) -> dict[str, Any]:
    label = _label(inp.id)
    rows = _q(ctx, f"MATCH (n:`{label}` {{id: $id}}) RETURN n LIMIT 1", {"id": inp.id})
    if not rows:
        raise _no_node(ctx, inp.id)
    out_links = _q(ctx, f"MATCH (n:`{label}` {{id: $id}})-[r]->(m) WHERE coalesce(r.deleted, false) = false "
                        "RETURN type(r) AS type, m.id AS toId, labels(m)[0] AS toType, r.method AS method, "
                        "r.confidence AS confidence LIMIT $limit", {"id": inp.id, "limit": MAX_LINKS})
    in_links = _q(ctx, f"MATCH (n:`{label}` {{id: $id}})<-[r]-(m) WHERE coalesce(r.deleted, false) = false "
                       "RETURN type(r) AS type, m.id AS fromId, labels(m)[0] AS fromType, r.method AS method, "
                       "r.confidence AS confidence LIMIT $limit", {"id": inp.id, "limit": MAX_LINKS})
    return {
        "id": inp.id,
        "type": label,
        "properties": clean_properties(rows[0]["n"]),
        "links": {"outgoing": out_links, "incoming": in_links},
    }


def _callers(ctx: ToolContext, inp: FunctionDepthIn) -> list[dict[str, Any]]:
    _label(inp.functionId)
    try:
        rows = Q.callers(ctx.store, inp.functionId, inp.depth, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    except Q.QueryError as exc:
        raise ToolFailure("invalid_input", str(exc)) from None
    return [{"id": r.id, "label": r.label, "depth": r.depth, "callSiteLines": r.callSiteLines,
             "confidence": r.confidence} for r in rows]


def _callees(ctx: ToolContext, inp: FunctionDepthIn) -> list[dict[str, Any]]:
    _label(inp.functionId)
    try:
        rows = Q.callees(ctx.store, inp.functionId, inp.depth, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    except Q.QueryError as exc:
        raise ToolFailure("invalid_input", str(exc)) from None
    return [{"id": r.id, "label": r.label, "depth": r.depth, "callSiteLines": r.callSiteLines,
             "confidence": r.confidence} for r in rows]


def _impact(ctx: ToolContext, inp: IdsDepthIn) -> dict[str, Any]:
    res = Q.impact(ctx.store, inp.ids, inp.depth, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    return {
        "functions": [{"id": f.id, "depth": f.depth, "criticalityPercentile": f.criticalityPercentile}
                      for f in res.functions],
        "files": [{"id": f.id, "path": f.path} for f in res.files],
        "tests": [{"id": t.id, "label": t.label} for t in res.tests],
        "components": [{"id": c.id, "name": c.name} for c in res.components],
    }


def _criticality(ctx: ToolContext, inp: IdsIn) -> list[dict[str, Any]]:
    return _dump(Q.criticality(ctx.store, inp.ids, timeout_ms=int(ctx.timeout_s * 1000)))  # type: ignore[no-any-return]


def _shortest_path(ctx: ToolContext, inp: ShortestPathIn) -> dict[str, Any]:
    _label(inp.fromId)
    _label(inp.toId)
    res = Q.shortest_path(ctx.store, inp.fromId, inp.toId, inp.maxHops, timeout_ms=int(ctx.timeout_s * 1000))
    if not res.found:
        return {"found": False}
    return {"found": True, "nodes": _dump(res.nodes), "links": _dump(res.links)}


def _decisions_for(ctx: ToolContext, inp: DecisionsIn) -> list[dict[str, Any]]:
    rows = Q.decisions_constraining(ctx.store, inp.ids, include_superseded=inp.includeSuperseded, limit=MAX_ROWS,
                                    timeout_ms=int(ctx.timeout_s * 1000))
    return [
        {
            "decisionId": d.id,
            "statement": d.statement,
            "status": d.status,
            "quote": d.quote,
            "source": ({"type": d.source.type, "id": d.source.id, "url": d.source.url, "author": d.sourceAuthor,
                        "at": d.sourceAt} if d.source else None),
            "scope": d.scope,
            "constrains": d.constrains,
        }
        for d in rows
    ]


def _related_work(ctx: ToolContext, inp: IdsIn) -> list[dict[str, Any]]:
    rows = Q.related_work(ctx.store, inp.ids, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    return [{"id": r.id, "type": r.type, "title": r.title, "state": r.state, "url": r.url, "at": r.at} for r in rows]


def _tests_for(ctx: ToolContext, inp: IdsIn) -> list[dict[str, Any]]:
    rows = Q.tests_for(ctx.store, inp.ids, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    return [{"testId": t.id, "label": t.label, "method": t.method, "confidence": t.confidence} for t in rows]


def _owners(ctx: ToolContext, inp: IdsIn) -> list[dict[str, Any]]:
    rows = Q.owners(ctx.store, inp.ids, limit=20, timeout_ms=int(ctx.timeout_s * 1000))
    return [{"personId": o.personId, "name": o.name, "basis": o.basis, "score": o.score} for o in rows]


def _procedures_for(ctx: ToolContext, inp: IdsIn) -> list[dict[str, Any]]:
    rows = Q.procedures_for(ctx.store, inp.ids, limit=MAX_ROWS, timeout_ms=int(ctx.timeout_s * 1000))
    return [{"procedureId": p.procedureId, "title": p.title, "testCommand": p.testCommand,
             "coChangedPaths": p.coChangedPaths, "steps": p.steps} for p in rows]


# ------------------------------------------------------------------------------------------- code tools


def _file_node(ctx: ToolContext, path: str) -> dict[str, Any] | None:
    rows = _q(ctx, "MATCH (f:CodeFile {path: $path}) WHERE coalesce(f.deleted, false) = false RETURN f LIMIT 1",
              {"path": path})
    return rows[0]["f"] if rows else None


def _file_lines(ctx: ToolContext, path: str) -> tuple[dict[str, Any] | None, list[str] | None]:
    """The file's lines from the snapshot: `CodeFile.text`, or rebuilt from its functions, classes and
    chunks (their line ranges cover the file, spec A, A-AC-28)."""
    node = _file_node(ctx, path)
    if node is None:
        return None, None
    text = node.get("text")
    if isinstance(text, str):
        return node, text.split("\n")
    rows = _q(ctx,
              "MATCH (f:CodeFile {path: $path})<-[:FUNCTION_DEFINED_IN|CLASS_DEFINED_IN|CHUNK_OF]-(p) "
              "WHERE coalesce(p.deleted, false) = false "
              "RETURN p.startLine AS s, coalesce(p.body, p.text) AS t LIMIT $cap",
              {"path": path, "cap": 5000})
    if not rows:
        return node, None
    lines: dict[int, str] = {}
    for r in sorted(rows, key=lambda x: (x.get("s") or 0)):
        start, body = r.get("s"), r.get("t")
        if not isinstance(start, int) or not isinstance(body, str):
            continue
        for i, line in enumerate(body.split("\n")):
            lines.setdefault(start + i, line)
    if not lines:
        return node, None
    last = max(lines)
    return node, [lines.get(i, "") for i in range(1, last + 1)]


def _outline(ctx: ToolContext, path: str) -> dict[str, Any]:
    node = _file_node(ctx, path)
    if node is None:
        raise ToolFailure("not_found", f"No file {path} in the snapshot")
    fid = node["id"]
    classes = _q(ctx,
                 "MATCH (f:CodeFile {id: $fid})<-[:CLASS_DEFINED_IN]-(c:CodeClass) WHERE coalesce(c.deleted, false) = false "
                 "OPTIONAL MATCH (c)<-[:METHOD_OF]-(m:CodeFunction) WHERE coalesce(m.deleted, false) = false "
                 "WITH c, m ORDER BY m.startLine "
                 "RETURN c.id AS id, c.name AS name, c.startLine AS startLine, c.endLine AS endLine, "
                 "collect(CASE WHEN m IS NULL THEN NULL ELSE {id: m.id, name: m.name, signature: m.signature, "
                 "startLine: m.startLine, endLine: m.endLine} END) AS methods ORDER BY startLine LIMIT $cap",
                 {"fid": fid, "cap": MAX_ROWS})
    functions = _q(ctx,
                   "MATCH (f:CodeFile {id: $fid})<-[:FUNCTION_DEFINED_IN]-(fn:CodeFunction) "
                   "WHERE coalesce(fn.deleted, false) = false AND NOT (fn)-[:METHOD_OF]->(:CodeClass) "
                   "RETURN fn.id AS id, fn.qualifiedName AS qualifiedName, fn.signature AS signature, "
                   "fn.startLine AS startLine, fn.endLine AS endLine ORDER BY startLine LIMIT $cap",
                   {"fid": fid, "cap": MAX_ROWS})
    imports = _q(ctx,
                 "MATCH (f:CodeFile {id: $fid})-[r:IMPORTS|IMPORTS_PACKAGE]->(x) "
                 "RETURN coalesce(x.path, x.name) AS target, type(r) AS kind, r.symbols AS symbols, r.line AS line "
                 "ORDER BY line LIMIT $cap",
                 {"fid": fid, "cap": MAX_ROWS})
    for c in classes:
        c["methods"] = [m for m in (c.get("methods") or []) if m]
    return {"path": path, "language": node.get("language"), "classes": classes, "functions": functions,
            "imports": imports, **_code_meta(ctx, path)}


def _get_code(ctx: ToolContext, inp: IdIn) -> dict[str, Any]:
    label = _label(inp.id)
    if label not in ("CodeFunction", "CodeClass", "CodeChunk", "CodeFile", "CodeDocument"):
        raise ToolFailure("invalid_input", "get_code takes a function, class, chunk, document or file id")
    if label == "CodeFile":
        path = _path_of(inp.id) or ""
        node, lines = _file_lines(ctx, path)
        if node is None:
            raise ToolFailure("not_found", f"No file {path} in the snapshot")
        if lines is None:
            raise ToolFailure("not_found", f"The snapshot has no source text for {path}")
        if len(lines) > FILE_OUTLINE_LINES:
            outline = _outline(ctx, path)
            return {"id": inp.id, "path": path, "startLine": 1, "endLine": len(lines),
                    "language": node.get("language"), "code": None, "outline": outline,
                    "hint": f"This file has {len(lines)} lines. Ask get_code_range for up to 400 lines at a time.",
                    **_code_meta(ctx, path)}
        return {"id": inp.id, "path": path, "startLine": 1, "endLine": len(lines), "language": node.get("language"),
                "code": _numbered("\n".join(lines), 1), **_code_meta(ctx, path)}
    rel = {"CodeFunction": "FUNCTION_DEFINED_IN", "CodeClass": "CLASS_DEFINED_IN", "CodeChunk": "CHUNK_OF",
           "CodeDocument": "SECTION_OF"}[label]
    rows = _q(ctx, f"MATCH (n:`{label}` {{id: $id}}) OPTIONAL MATCH (n)-[:{rel}]->(f:CodeFile) "
                   "RETURN n, f.path AS path, f.language AS language LIMIT 1", {"id": inp.id})
    if not rows:
        raise _no_node(ctx, inp.id)
    n = rows[0]["n"]
    node_path: str | None = rows[0].get("path") or _path_of(inp.id)
    body = n.get("body") if label in ("CodeFunction", "CodeClass") else n.get("text")
    start = int(n.get("startLine") or 1)
    text = body if isinstance(body, str) else ""
    end = int(n.get("endLine") or start + text.count("\n"))
    out = {"id": inp.id, "path": node_path, "startLine": start, "endLine": end,
           "language": rows[0].get("language"), "code": _numbered(text, start), **_code_meta(ctx, node_path)}
    if n.get("deleted"):
        out["deleted"] = True
    return out


def _get_code_range(ctx: ToolContext, inp: CodeRangeIn) -> dict[str, Any]:
    if inp.endLine < inp.startLine:
        raise ToolFailure("invalid_input", "endLine must be at or after startLine")
    if inp.endLine - inp.startLine + 1 > MAX_RANGE_LINES:
        raise ToolFailure("invalid_input", f"Ask for at most {MAX_RANGE_LINES} lines at a time")
    node, lines = _file_lines(ctx, inp.path)
    if node is None:
        raise ToolFailure("not_found", f"No file {inp.path} in the snapshot")
    if lines is None:
        raise ToolFailure("not_found", f"The snapshot has no source text for {inp.path}")
    end = min(inp.endLine, len(lines))
    chunk = "\n".join(lines[inp.startLine - 1 : end])
    return {"path": inp.path, "startLine": inp.startLine, "endLine": end,
            "code": _numbered(chunk, inp.startLine), **_code_meta(ctx, inp.path)}


def _file_outline(ctx: ToolContext, inp: PathIn) -> dict[str, Any]:
    return _outline(ctx, inp.path)


def _find_symbol(ctx: ToolContext, inp: FindSymbolIn) -> list[dict[str, Any]]:
    labels = {"function": ["CodeFunction"], "class": ["CodeClass"], None: ["CodeFunction", "CodeClass"]}[inp.kind]
    stages = [
        "n.name = $name OR n.qualifiedName = $name",
        "toLower(n.name) = toLower($name) OR toLower(n.qualifiedName) = toLower($name)",
        "n.qualifiedName ENDS WITH $name OR toLower(n.name) ENDS WITH toLower($name)",
    ]
    for cond in stages:
        out: list[dict[str, Any]] = []
        for label in labels:
            rows = _q(ctx, f"MATCH (n:`{label}`) WHERE ({cond}) AND coalesce(n.deleted, false) = false "
                           "RETURN n.id AS id, n.qualifiedName AS qualifiedName, n.startLine AS startLine, "
                           "n.signature AS signature ORDER BY n.id LIMIT $cap", {"name": inp.name, "cap": MAX_ROWS})
            for r in rows:
                r["path"] = _path_of(r["id"])
                r["kind"] = "function" if label == "CodeFunction" else "class"
                out.append(r)
        if out:
            snap = _snapshot(ctx)
            for r in out:
                r["snapshot"] = snap
                if r["path"] in ctx.differing_paths:
                    r["differs"] = True
            return out[:MAX_ROWS]
    return []


def _references(ctx: ToolContext, inp: IdIn) -> list[dict[str, Any]]:
    label = _label(inp.id)
    rel = {"CodeFunction": "CALLS", "CodeClass": "INSTANTIATES"}.get(label)
    if rel is None:
        raise ToolFailure("invalid_input", "references takes a function or class id")
    rows = _q(ctx, f"MATCH (t:`{label}` {{id: $id}})<-[r:{rel}]-(c:CodeFunction) "
                   "WHERE coalesce(c.deleted, false) = false "
                   "OPTIONAL MATCH (c)-[:FUNCTION_DEFINED_IN]->(f:CodeFile) "
                   "RETURN c.id AS callerId, c.qualifiedName AS name, c.body AS body, c.startLine AS start, "
                   "r.callSiteLines AS lines, f.path AS path ORDER BY callerId LIMIT $cap",
              {"id": inp.id, "cap": MAX_ROWS})
    file_cache: dict[str, list[str] | None] = {}
    out: list[dict[str, Any]] = []
    snap = _snapshot(ctx)
    for r in rows:
        path = r.get("path") or _path_of(r["callerId"])
        if path and path not in file_cache:
            file_cache[path] = _file_lines(ctx, path)[1]
        flines = file_cache.get(path) if path else None
        body_lines = str(r.get("body") or "").split("\n")
        start = int(r.get("start") or 1)
        for line in (r.get("lines") or [None]):
            snippet = ""
            if isinstance(line, int):
                if flines:
                    lo, hi = max(1, line - 2), min(len(flines), line + 2)
                    snippet = _numbered("\n".join(flines[lo - 1 : hi]), lo)
                else:
                    lo = max(start, line - 2)
                    hi = min(start + len(body_lines) - 1, line + 2)
                    snippet = _numbered("\n".join(body_lines[lo - start : hi - start + 1]), lo)
            item = {"callerId": r["callerId"], "callerQualifiedName": r.get("name"), "path": path, "line": line,
                    "snippet": snippet, "snapshot": snap}
            if path in ctx.differing_paths:
                item["differs"] = True
            out.append(item)
    return out[:MAX_ROWS]


def _search_code(ctx: ToolContext, inp: SearchCodeIn) -> list[dict[str, Any]]:
    rows = Q.seeds_fulltext(ctx.store, inp.query, search_fields=ctx.fields(),
                            types=["CodeFunction", "CodeClass", "CodeChunk"], limit=MAX_ROWS,
                            timeout_ms=int(ctx.timeout_s * 1000))
    picked = []
    for r in rows:
        path = _path_of(r.id)
        if inp.pathPrefix and not (path or "").startswith(inp.pathPrefix):
            continue
        picked.append((r, path))
        if len(picked) >= inp.limit:
            break
    nodes = Q.fetch_nodes(ctx.store, [r.id for r, _ in picked], int(ctx.timeout_s * 1000))
    snap = _snapshot(ctx)
    out = []
    for r, path in picked:
        n = nodes.get(r.id, {})
        item = {"id": r.id, "path": path, "startLine": n.get("startLine"), "endLine": n.get("endLine"),
                "snippet": r.snippet, "score": r.score, "snapshot": snap}
        if path in ctx.differing_paths:
            item["differs"] = True
        out.append(item)
    return out


# ------------------------------------------------------------------------------------------- history tools


def repo_dir_for(ctx: ToolContext, repo: str) -> Path | None:
    """Where the clone of `repo` (owner/name) lives: the context's repo_dir, else the clone directory."""
    if ctx.repo_dir is not None:
        return ctx.repo_dir if (ctx.repo_dir / ".git").exists() else None
    from actron.config import get_settings

    base = get_settings().ACTRON_CLONE_DIR
    owner, _, name = repo.partition("/")
    for cand in (base / ctx.ws / owner / name, base / owner / name, base / ctx.ws / f"{owner}__{name}",
                 base / f"{owner}__{name}", base / name):
        if (cand / ".git").exists():
            return cand
    return None


def _git(repo: Path, *args: str, timeout: float = 5.0) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
                             check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def _rename_chain(ctx: ToolContext, node_id: str) -> list[dict[str, Any]]:
    """The node and its earlier names (newest first), with their qualified names and paths."""
    chains = Q.expand_renames(ctx.store, [node_id], int(ctx.timeout_s * 1000))
    chain_ids = max(chains.values(), key=len)
    nodes = Q.fetch_nodes(ctx.store, chain_ids, int(ctx.timeout_s * 1000))
    out = []
    for nid in chain_ids:
        n = nodes.get(nid, {"id": nid})
        try:
            parts = ids.parse_id(nid).parts
        except ids.InvalidId:
            continue
        out.append({"id": nid, "qualname": parts.get("qualname"), "dup": int(parts.get("dup") or 1),
                    "path": parts.get("path"), "repo": parts.get("repo"), "node": n})
    return out


def _history(ctx: ToolContext, inp: HistoryIn) -> list[dict[str, Any]]:
    label = _label(inp.id)
    if label not in ("CodeFunction", "CodeClass"):
        raise ToolFailure("invalid_input", "history takes a function or class id")
    # The B.C4 shape is built here; connectors.code.history_tools returns a different, ingestion-side shape.
    chain = _rename_chain(ctx, inp.id)
    rel = "TOUCHED" if label == "CodeFunction" else "TOUCHED_CLASS"
    rows = _q(ctx, f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[x:{rel}]-(c:GitCommit) "
                   "OPTIONAL MATCH (pr:GithubPullRequest)-[:MERGED_AS|INCLUDES_COMMIT]->(c) "
                   "RETURN tid, c.sha AS sha, c.shortSha AS shortSha, c.subject AS subject, "
                   "coalesce(c.authorName, c.authorEmail) AS author, c.authoredAt AS authoredAt, "
                   "x.changeType AS changeType, x.linesChanged AS linesChanged, min(pr.number) AS prNumber "
                   "ORDER BY authoredAt DESC LIMIT $cap",
              {"tids": [c["id"] for c in chain], "cap": inp.limit * 2 + 5})
    names = {c["id"]: c["qualname"] for c in chain}
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        key = (str(r["sha"]), str(r["tid"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"commitSha": r["sha"], "shortSha": r.get("shortSha") or str(r["sha"])[:7],
                    "subject": r.get("subject"), "author": r.get("author"), "authoredAt": r.get("authoredAt"),
                    "changeType": r.get("changeType"), "linesChanged": r.get("linesChanged"),
                    "prNumber": r.get("prNumber"), "id": r["tid"], "name": names.get(r["tid"]),
                    "renamed": r["tid"] != inp.id})
    out.sort(key=lambda h: h["renamed"])
    out.sort(key=lambda h: str(h.get("authoredAt") or ""), reverse=True)
    if out or not chain:
        return out[: inp.limit]
    return _git_history(ctx, chain[0], inp.limit)


def _git_history(ctx: ToolContext, item: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
    """Fallback when the graph has no TOUCHED links: `git log -L` over the symbol's current line range."""
    node = item["node"]
    repo = repo_dir_for(ctx, str(item.get("repo") or ""))
    start, end, path = node.get("startLine"), node.get("endLine"), item.get("path")
    if repo is None or not isinstance(start, int) or not isinstance(end, int) or not path:
        return []
    raw = _git(repo, "log", f"-n{limit}", "--no-patch", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%aI",
               f"-L{start},{end}:{path}", timeout=10.0)
    out = []
    for line in (raw or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        out.append({"commitSha": parts[0], "shortSha": parts[1], "subject": parts[2], "author": parts[3],
                    "authoredAt": parts[4], "changeType": "modified", "linesChanged": None, "prNumber": None,
                    "id": item["id"], "name": item.get("qualname"), "renamed": False})
    return out


_DEF_PATTERNS = (
    r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s*{name}\b",
    r"^\s*(async\s+)?def\s+{name}\b",
    r"^\s*(export\s+)?(abstract\s+)?class\s+{name}\b",
    r"^\s*(public|private|protected|static|async|\s)*{name}\s*\(",
    r"^\s*(export\s+)?(const|let|var)\s+{name}\s*=",
    r"^\s*func\s+(\([^)]*\)\s*)?{name}\b",
    r"^\s*(pub\s+)?fn\s+{name}\b",
    r"^\s*\(defn-?\s+{name}\b",
)


def _slice_symbol(text: str, path: str, qualname: str, dup: int) -> tuple[int, int, str] | None:
    """Locate a symbol in a file version: W2's parser when available, else a definition-line heuristic
    (brace matching or indentation)."""
    lines = text.split("\n")
    parsed: Any = None
    try:
        from actron.connectors.code.parse import parse_file

        parsed = parse_file(path, text.encode())
    except Exception:
        parsed = None
    if parsed is not None:
        key = qualname if dup == 1 else f"{qualname}~{dup}"
        for sym in parsed.symbols:
            if sym.key == key:
                return sym.start_line, sym.end_line, "\n".join(lines[sym.start_line - 1 : sym.end_line])
    name = qualname.split(".")[-1].split(" > ")[-1]
    hits = 0
    for idx, line in enumerate(lines):
        if not any(re.search(p.format(name=re.escape(name)), line) for p in _DEF_PATTERNS):
            continue
        hits += 1
        if hits < dup:
            continue
        end = _block_end(lines, idx)
        return idx + 1, end + 1, "\n".join(lines[idx : end + 1])
    return None


def _block_end(lines: list[str], start: int) -> int:
    depth = 0
    opened = False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch in "{(":
                depth += 1
                opened = opened or ch == "{"
            elif ch in "})":
                depth -= 1
        if opened and depth <= 0:
            return i
        if not opened and lines[start].rstrip().endswith(":") and i > start:
            indent = len(lines[start]) - len(lines[start].lstrip())
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                return i
    return len(lines) - 1


def _get_code_at(ctx: ToolContext, inp: CodeAtIn) -> dict[str, Any]:
    label = _label(inp.id)
    if label not in ("CodeFunction", "CodeClass"):
        raise ToolFailure("invalid_input", "get_code_at takes a function or class id")
    if not re.fullmatch(r"[0-9a-fA-F]{4,64}", inp.commitSha):
        raise ToolFailure("invalid_input", "commitSha must be a hex commit sha")
    chain = _rename_chain(ctx, inp.id)
    if not chain:
        raise ToolFailure("not_found", f"No node with id {inp.id}")
    repo = repo_dir_for(ctx, str(chain[0].get("repo") or ""))
    if repo is None:
        raise ToolFailure("unavailable", "No local clone of this repository to read history from")
    sha = (_git(repo, "rev-parse", "--verify", f"{inp.commitSha}^{{commit}}") or "").strip()
    if not sha:
        return {"found": False, "id": inp.id, "commitSha": inp.commitSha, "reason": "unknown commit"}
    for item in chain:
        path = item.get("path")
        if not path:
            continue
        text = _git(repo, "show", f"{sha}:{path}")
        if text is None:
            continue
        found = _slice_symbol(text, str(path), str(item.get("qualname") or ""), int(item.get("dup") or 1))
        if found:
            start, end, code = found
            return {"found": True, "id": inp.id, "commitSha": sha, "path": path, "startLine": start, "endLine": end,
                    "name": item.get("qualname"), "renamed": item["id"] != inp.id, "code": _numbered(code, start)}
    return {"found": False, "id": inp.id, "commitSha": sha}


# ------------------------------------------------------------------------------------------- registry


def _count(noun: str, plural: str | None = None) -> Callable[[Any], str]:
    def summary(out: Any) -> str:
        n = len(out) if isinstance(out, list) else 0
        if n == 0:
            return f"No {plural or noun + 's'} found"
        return f"{n} {noun if n == 1 else (plural or noun + 's')}"
    return summary


def _impact_summary(out: Any) -> str:
    return (f"{len(out.get('functions', []))} functions, {len(out.get('tests', []))} tests, "
            f"{len(out.get('files', []))} files could be affected")


def _path_summary(out: Any) -> str:
    return f"Connected in {len(out.get('nodes', [])) - 1} steps" if out.get("found") else "No connection found"


def _node_summary(out: Any) -> str:
    return f"{out.get('type')} with {len(out['links']['outgoing']) + len(out['links']['incoming'])} links"


def _code_summary(out: Any) -> str:
    if out.get("found") is False:
        return "Not present at that commit"
    return f"{out.get('path')} lines {out.get('startLine')}-{out.get('endLine')}"


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec("search", SearchIn, "Full-text search over code, decisions, tickets, PRs and messages; start here "
                 "to find the nodes a request is about, for example {\"query\": \"evaluate on save\"}.",
                 _search, _count("result")),
        ToolSpec("get_node", IdIn, "Read one node's properties and its links in both directions, for example "
                 "{\"id\": \"code:fn:owner/repo:src/a.ts::run\"}.", _get_node, _node_summary),
        ToolSpec("callers", FunctionDepthIn, "List the functions that call a function, up to 3 hops back, for example "
                 "{\"functionId\": \"code:fn:owner/repo:src/a.ts::run\", \"depth\": 2}.", _callers, _count("caller")),
        ToolSpec("callees", FunctionDepthIn, "List the functions a function calls, up to 3 hops, for example "
                 "{\"functionId\": \"code:fn:owner/repo:src/a.ts::run\"}.", _callees, _count("callee")),
        ToolSpec("impact", IdsDepthIn, "Show what could break if these functions or classes change (callers, "
                 "files, tests, components), for example {\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.",
                 _impact, _impact_summary),
        ToolSpec("criticality", IdsIn, "Read PageRank and caller counts to see how central functions are, for "
                 "example {\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.", _criticality, _count("function")),
        ToolSpec("shortest_path", ShortestPathIn, "Find how two nodes are connected, in either direction, for "
                 "example {\"fromId\": \"slack:msg:C1:1.2\", \"toId\": \"code:fn:owner/repo:src/a.ts::run\"}.",
                 _shortest_path, _path_summary),
        ToolSpec("decisions_for", DecisionsIn, "List the team decisions that constrain this code or feature, with "
                 "the source quote, for example {\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.",
                 _decisions_for, _count("decision")),
        ToolSpec("related_work", IdsIn, "List earlier PRs, tickets, issues and messages about this code, for example "
                 "{\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.", _related_work, _count("related item")),
        ToolSpec("tests_for", IdsIn, "List the tests that exercise this code, for example "
                 "{\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.", _tests_for, _count("test")),
        ToolSpec("owners", IdsIn, "List the people who own or know this code, with the reason, for example "
                 "{\"ids\": [\"code:fn:owner/repo:src/a.ts::run\"]}.", _owners, _count("owner")),
        ToolSpec("procedures_for", IdsIn, "Read how changes are usually made in this area (steps, test command), "
                 "for example {\"ids\": [\"code:file:owner/repo:src/a.ts\"]}.", _procedures_for,
                 _count("procedure")),
        ToolSpec("get_code", IdIn, "Read the full source of a function, class, chunk or file from the graph "
                 "snapshot, for example {\"id\": \"code:fn:owner/repo:src/a.ts::run\"}.", _get_code, _code_summary),
        ToolSpec("get_code_range", CodeRangeIn, "Read up to 400 lines of a file from the graph snapshot, for "
                 "example {\"path\": \"src/a.ts\", \"startLine\": 1, \"endLine\": 80}.", _get_code_range,
                 _code_summary),
        ToolSpec("file_outline", PathIn, "List a file's classes, methods, functions and imports with line "
                 "numbers, for example {\"path\": \"src/a.ts\"}.", _file_outline,
                 lambda o: f"{len(o.get('functions', []))} functions, {len(o.get('classes', []))} classes"),
        ToolSpec("find_symbol", FindSymbolIn, "Find a function or class by name (exact, then any case, then "
                 "suffix), for example {\"name\": \"activate\"}.", _find_symbol, _count("match", "matches")),
        ToolSpec("references", IdIn, "Show each call site of a function (or construction of a class) with two "
                 "lines of context, for example {\"id\": \"code:fn:owner/repo:src/a.ts::run\"}.", _references,
                 _count("call site")),
        ToolSpec("history", HistoryIn, "List the commits that changed a function, newest first, including its "
                 "earlier names, for example {\"id\": \"code:fn:owner/repo:src/a.ts::run\", \"limit\": 5}.",
                 _history, _count("commit")),
        ToolSpec("get_code_at", CodeAtIn, "Read a function's source as it was at an earlier commit, for example "
                 "{\"id\": \"code:fn:owner/repo:src/a.ts::run\", \"commitSha\": \"a1b2c3d\"}.", _get_code_at,
                 _code_summary),
        ToolSpec("search_code", SearchCodeIn, "Full-text search over function and class bodies and code chunks, "
                 "for example {\"query\": \"retry timeout\", \"pathPrefix\": \"src/\"}.", _search_code,
                 _count("result")),
    ]
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOLS)


def _short_args(args: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 300:
            v = v[:300] + "…"
        elif isinstance(v, list) and len(v) > 20:
            v = [*v[:20], f"… {len(v) - 20} more"]
        out[k] = v
    return out


async def _emit(ctx: ToolContext, type_: str, payload: dict[str, Any]) -> None:
    if ctx.emit is None:
        return
    try:
        await ctx.emit(type_, payload, actor="actron", surface="system")
    except Exception as exc:  # events are best-effort; a tool answer must not fail because of them
        log.warning("tool event emit failed", extra={"type": type_, "error": type(exc).__name__})


async def call_tool(ctx: ToolContext, name: str, args: Mapping[str, Any] | None = None) -> Any:
    """Run one tool and return its JSON output, or `{"error": {"code", "message"}}`. Never raises."""
    args = dict(args or {})
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    await _emit(ctx, "tool.called", {"callId": call_id, "tool": name, "args": _short_args(args), "by": ctx.by})
    started = time.monotonic()
    ctx.calls += 1
    error: dict[str, str] | None = None
    output: Any = None
    spec = TOOLS.get(name)
    if spec is None:
        error = {"code": "unknown_tool", "message": f"No tool named {name}"}
    else:
        try:
            inp = spec.input_model.model_validate(args)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ())) or "input"
            error = {"code": "invalid_input", "message": f"{where}: {first.get('msg')}"}
        else:
            try:
                output = await asyncio.wait_for(asyncio.to_thread(spec.run, ctx, inp), timeout=ctx.timeout_s + 0.5)
            except ToolFailure as exc:
                error = {"code": exc.code, "message": exc.message}
            except (TimeoutError, GraphTimeout):
                error = {"code": "timeout", "message": f"{name} took longer than {ctx.timeout_s:.0f} seconds"}
            except Q.QueryError as exc:
                error = {"code": "invalid_input", "message": str(exc)}
            except Exception as exc:
                log.warning("tool failed", extra={"tool": name, "error": type(exc).__name__})
                error = {"code": "internal", "message": f"{name} failed: {type(exc).__name__}"}
    duration = int((time.monotonic() - started) * 1000)
    if error is not None:
        await _emit(ctx, "tool.result", {"callId": call_id, "ok": False, "summary": error["message"],
                                         "nodeIds": [], "durationMs": duration, "error": error})
        return {"error": error}
    output = _dump(output)
    node_list = node_ids_in(output)
    ctx.returned_ids.update(node_list)
    summary = spec.summary(output) if spec else ""
    await _emit(ctx, "tool.result", {"callId": call_id, "ok": True, "summary": summary,
                                     "nodeIds": node_list[:MAX_ROWS], "durationMs": duration})
    return output


ToolCaller = Callable[[str, Mapping[str, Any]], Awaitable[Any]]


def bind(ctx: ToolContext) -> ToolCaller:
    async def caller(name: str, args: Mapping[str, Any]) -> Any:
        return await call_tool(ctx, name, args)

    return caller
