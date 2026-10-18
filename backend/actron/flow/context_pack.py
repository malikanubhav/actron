"""Context pack (`/context/code.md`) built from the graph so Pi does not need to explore (spec B, B9 step 2).

For each affected function or class in the ticket: full line-numbered source, direct callers (with call-site
lines and ±2 lines of context) and callees (signature and path), covering tests (full source when under
120 lines), the decisions that constrain it; then the outline of every touched file, the area's procedure,
and the files that differ on a non-working target branch.

Size limit 60,000 characters. When larger, the pack keeps full source for the affected symbols and gives
outlines and names for the rest, and says which graph tool to call for more. As a last resort each source
block is cut and the pack names `get_code_range` for the missing lines.

All graph reads go through a `ToolCaller` (W5's MCP tools: `call_tool(ctx, name, args)`), so the pack shows
exactly what the code tools would return.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from actron.graph import ids
from actron.logging import get_logger

log = get_logger(__name__)

PACK_LIMIT = 60_000
TEST_SOURCE_MAX_LINES = 120
MAX_CALLERS = 12
MAX_CALLEES = 12
MAX_TESTS = 6

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[Any]]


class ContextPackUnavailable(RuntimeError):
    """The graph tools could not be reached."""


@dataclass
class SymbolInfo:
    id: str
    qualname: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    language: str = ""
    code: str = ""
    callers: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    callees: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ContextPack:
    markdown: str
    symbols: list[SymbolInfo]
    tier: str  # "full" | "compact" | "cut"
    snapshot: str | None
    # For the graph-first check: function id -> {path, hasCallers, callersInPack}
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.markdown)

    def where_to_work(self) -> list[str]:
        out = []
        for s in self.symbols:
            lines = f" (lines {s.start_line}-{s.end_line})" if s.start_line and s.end_line else ""
            out.append(f"- `{s.qualname}` in `{s.path}`{lines}")
        return out


def _ok(value: Any) -> bool:
    return not (isinstance(value, dict) and "error" in value and len(value) <= 2)


async def _safe(tools: ToolCaller, name: str, args: dict[str, Any]) -> Any:
    try:
        value = await tools(name, args)
    except Exception as exc:  # a missing tool or a timeout must not stop the build
        log.info("graph tool failed while building the context pack", extra={"tool": name, "error": str(exc)})
        return None
    return value if _ok(value) else None


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("items", "results", "rows"):
            if isinstance(value.get(key), list):
                return [v for v in value[key] if isinstance(v, dict)]
    return []


def _numbered(code: str, start: int | None) -> str:
    """Line-number the code unless the tool already did (`  12 | text` or `12: text`)."""
    lines = code.splitlines()
    if lines and all(line.lstrip()[:1].isdigit() for line in lines[: min(3, len(lines))]):
        return code
    first = start or 1
    width = len(str(first + len(lines)))
    return "\n".join(f"{str(first + i).rjust(width)} | {line}" for i, line in enumerate(lines))


def _fence(code: str, language: str = "") -> str:
    ticks = "````" if "```" in code else "```"
    return f"{ticks}{language}\n{code}\n{ticks}"


def _qualname(node_id: str) -> tuple[str, str]:
    try:
        parsed = ids.parse_id(node_id)
    except ids.InvalidId:
        return node_id, ""
    return parsed.parts.get("qualname") or parsed.parts.get("path") or node_id, parsed.parts.get("path", "")


async def gather_symbol(tools: ToolCaller, node_id: str) -> SymbolInfo:
    qualname, path = _qualname(node_id)
    info = SymbolInfo(id=node_id, qualname=qualname, path=path)
    code = await _safe(tools, "get_code", {"id": node_id})
    if isinstance(code, dict):
        info.path = str(code.get("path") or path)
        info.start_line = code.get("startLine")
        info.end_line = code.get("endLine")
        info.language = str(code.get("language") or "")
        info.code = str(code.get("code") or "")
    info.callers = _as_list(await _safe(tools, "callers", {"functionId": node_id, "depth": 1}))[:MAX_CALLERS]
    info.references = _as_list(await _safe(tools, "references", {"id": node_id}))[:MAX_CALLERS]
    info.callees = _as_list(await _safe(tools, "callees", {"functionId": node_id, "depth": 1}))[:MAX_CALLEES]
    for callee in info.callees:
        if "signature" not in callee and callee.get("id"):
            node = await _safe(tools, "get_node", {"id": callee["id"]})
            props = (node or {}).get("properties") or {} if isinstance(node, dict) else {}
            callee["signature"] = props.get("signature")
            callee["path"] = props.get("path") or _qualname(str(callee["id"]))[1]
    for test in _as_list(await _safe(tools, "tests_for", {"ids": [node_id]}))[:MAX_TESTS]:
        test_id = str(test.get("testId") or test.get("id") or "")
        src = await _safe(tools, "get_code", {"id": test_id}) if test_id else None
        if isinstance(src, dict):
            test["path"] = src.get("path")
            body = str(src.get("code") or "")
            if body and len(body.splitlines()) < TEST_SOURCE_MAX_LINES:
                test["code"] = body
                test["startLine"] = src.get("startLine")
        info.tests.append(test)
    info.decisions = _as_list(await _safe(tools, "decisions_for", {"ids": [node_id]}))
    return info


def _caller_block(info: SymbolInfo, *, snippets: bool) -> list[str]:
    out: list[str] = []
    refs_by_caller: dict[str, list[dict[str, Any]]] = {}
    for ref in info.references:
        refs_by_caller.setdefault(str(ref.get("callerId")), []).append(ref)
    listed: set[str] = set()
    for caller in info.callers:
        cid = str(caller.get("id"))
        listed.add(cid)
        qn, cpath = _qualname(cid)
        label = caller.get("label") or qn
        lines = caller.get("callSiteLines") or []
        where = f"{cpath}:{','.join(str(n) for n in lines)}" if lines else cpath
        out.append(f"- `{label}` ({where}) id `{cid}`")
        if snippets:
            for ref in refs_by_caller.get(cid, []):
                if ref.get("snippet"):
                    out.append(_fence(str(ref["snippet"]), info.language))
    for cid, refs in refs_by_caller.items():
        if cid in listed:
            continue
        ref = refs[0]
        out.append(f"- `{ref.get('callerQualifiedName') or cid}` ({ref.get('path')}:{ref.get('line')})")
        if snippets and ref.get("snippet"):
            out.append(_fence(str(ref["snippet"]), info.language))
    return out


def _symbol_section(info: SymbolInfo, *, compact: bool, cut_lines: int | None = None) -> str:
    rng = f":{info.start_line}-{info.end_line}" if info.start_line else ""
    parts = [f"## `{info.qualname}` — `{info.path}{rng}`", f"Id: `{info.id}`", ""]
    if info.code:
        code = info.code
        note = ""
        if cut_lines is not None and len(code.splitlines()) > cut_lines:
            code = "\n".join(code.splitlines()[:cut_lines])
            note = (f"\n(Source cut at {cut_lines} lines to fit the pack. Call get_code_range with path "
                    f"`{info.path}` for the rest.)")
        parts.append(_fence(_numbered(code, info.start_line), info.language) + note)
    else:
        parts.append(f"(Source not available from the graph. Call get_code with id `{info.id}`.)")
    parts += ["", "### Callers"]
    callers = _caller_block(info, snippets=not compact)
    parts += callers or ["- None found in the graph."]
    if compact and callers:
        parts.append(f"(Call sites left out to fit the pack. Call references with id `{info.id}`.)")
    parts += ["", "### Callees"]
    if info.callees:
        for c in info.callees:
            sig = c.get("signature") or c.get("label") or _qualname(str(c.get("id")))[0]
            parts.append(f"- `{sig}` ({c.get('path') or _qualname(str(c.get('id')))[1]})")
    else:
        parts.append("- None found in the graph.")
    parts += ["", "### Tests that cover it"]
    if info.tests:
        for t in info.tests:
            label = t.get("label") or t.get("testId")
            parts.append(f"#### `{label}` ({t.get('path') or ''})")
            if t.get("code") and not compact:
                parts.append(_fence(_numbered(str(t["code"]), t.get("startLine")), info.language))
            elif t.get("code"):
                parts.append(f"(Source left out to fit the pack. Call get_code with id `{t.get('testId')}`.)")
    else:
        parts.append("- No covering tests found in the graph.")
    parts += ["", "### Decisions that constrain it"]
    if info.decisions:
        for d in info.decisions:
            src = d.get("source") or {}
            where = src.get("url") or src.get("type") or ""
            quote = f' — "{d["quote"]}"' if d.get("quote") else ""
            parts.append(f"- {d.get('statement')} ({d.get('status', 'approved')}){quote} ({where})")
    else:
        parts.append("- None recorded.")
    return "\n".join(parts)


def _outline_section(outlines: dict[str, dict[str, Any]]) -> str:
    parts = ["# File outlines"]
    for path, outline in outlines.items():
        parts.append(f"## `{path}`")
        for cls in outline.get("classes") or []:
            parts.append(f"- class `{cls.get('name')}` (lines {cls.get('startLine')}-{cls.get('endLine')})")
            for m in cls.get("methods") or []:
                name = m.get("signature") or m.get("name") or m.get("qualifiedName")
                parts.append(f"  - `{name}` (lines {m.get('startLine')}-{m.get('endLine')})")
        for fn in outline.get("functions") or []:
            name = fn.get("signature") or fn.get("qualifiedName")
            parts.append(f"- `{name}` (lines {fn.get('startLine')}-{fn.get('endLine')})")
        if not outline.get("classes") and not outline.get("functions"):
            parts.append("- (no outline in the graph)")
    return "\n".join(parts)


def _procedure_section(procedures: list[dict[str, Any]], test_command: str | None) -> str:
    parts = ["# How changes are tested here"]
    if test_command:
        parts.append(f"Test command: `{test_command}`")
    for p in procedures:
        if p.get("title"):
            parts.append(f"## {p['title']}")
        if p.get("testCommand"):
            parts.append(f"- Test command: `{p['testCommand']}`")
        if p.get("coChangedPaths"):
            parts.append("- Files that usually change together: " + ", ".join(f"`{c}`" for c in p["coChangedPaths"]))
        for step in p.get("steps") or []:
            parts.append(f"- {step}")
    if len(parts) == 1:
        parts.append("- No procedure recorded for this area.")
    return "\n".join(parts)


def _differs_section(target_branch: str, files: list[str], repo_dir: Path | None, budget: int) -> str:
    if not files:
        return ""
    parts = [f"# Files that differ on `{target_branch}`",
             "The graph describes the working branch. These files are read from the checkout instead."]
    for path in files:
        parts.append(f"## `{path}` (differs on {target_branch})")
        text = ""
        if repo_dir is not None and (repo_dir / path).is_file():
            text = (repo_dir / path).read_text(encoding="utf-8", errors="replace")
        if text and len(text) <= budget:
            parts.append(_fence(_numbered(text, 1)))
            budget -= len(text)
        else:
            parts.append(f"(Read `{path}` from /work; it is too large to include.)")
    return "\n".join(parts)


async def build_context_pack(
    ticket: dict[str, Any],
    evidence: dict[str, Any],
    procedures: list[dict[str, Any]],
    *,
    tools: ToolCaller,
    test_command: str | None = None,
    differing_files: list[str] | None = None,
    target_branch: str = "",
    repo_dir: Path | None = None,
    snapshot: str | None = None,
    limit: int = PACK_LIMIT,
) -> ContextPack:
    affected = [str(a) for a in ticket.get("affectedFunctions") or []]
    symbols = [await gather_symbol(tools, node_id) for node_id in affected]
    paths: list[str] = []
    for s in symbols:
        if s.path and s.path not in paths:
            paths.append(s.path)
    outlines: dict[str, dict[str, Any]] = {}
    for path in paths:
        outline = await _safe(tools, "file_outline", {"path": path})
        outlines[path] = outline if isinstance(outline, dict) else {}
    if not procedures:
        found = await _safe(tools, "procedures_for", {"ids": affected}) if affected else None
        procedures = _as_list(found)
    differ = [f for f in differing_files or [] if f in paths or any(f == s.path for s in symbols)]

    header = ["# Code context from the team's graph",
              f"Snapshot: `{snapshot}`. Every line below is the code at the base commit." if snapshot
              else "Every line below is the code at the base commit.",
              "Ask the graph (get_code, get_code_range, file_outline, find_symbol, references, callers, "
              "impact, tests_for, decisions_for, search_code) for anything that is not here.", ""]
    tail = [_outline_section(outlines), _procedure_section(procedures, test_command)]

    def render(compact: bool, cut: int | None) -> str:
        body = [_symbol_section(s, compact=compact, cut_lines=cut) for s in symbols]
        text = "\n\n".join(["\n".join(header), *body, *tail])
        if compact:
            text += ("\n\n(This pack was shortened to fit 60,000 characters: callers are listed without call "
                     "sites and long test sources are left out. Use references, get_code and tests_for for them.)")
        return text

    tier = "full"
    markdown = render(False, None)
    if len(markdown) > limit:
        tier, markdown = "compact", render(True, None)
    if len(markdown) > limit:
        per = max(20, (limit // max(1, len(symbols))) // 80)
        tier, markdown = "cut", render(True, per)
        if len(markdown) > limit:
            markdown = markdown[: limit - 200] + "\n\n(Pack cut at 60,000 characters. Use the graph tools.)"
    if differ:
        extra = _differs_section(target_branch, differ, repo_dir, max(0, limit - len(markdown) - 500))
        if len(markdown) + len(extra) <= limit:
            markdown += "\n\n" + extra
        else:
            markdown += (f"\n\n# Files that differ on `{target_branch}`\n" +
                         "\n".join(f"- `{f}` (read it from /work)" for f in differ))

    meta: dict[str, dict[str, Any]] = {}
    for s in symbols:
        has_callers = bool(s.callers or s.references)
        meta[s.id] = {"path": s.path, "hasCallers": has_callers,
                      "callersInPack": has_callers and tier != "cut"}
    return ContextPack(markdown=markdown, symbols=symbols, tier=tier, snapshot=snapshot, meta=meta)


def graph_tool_caller(
    ws: str,
    *,
    emit: Any | None = None,
    snapshot_sha: str | None = None,
    differing_paths: list[str] | None = None,
    repo_dir: Path | None = None,
) -> ToolCaller:
    """W5's `actron.mcp_graph.tools.call_tool(ToolContext, name, args)` on the workspace's graph.

    Each call emits `tool.called`/`tool.result` through `emit` (by = "pi": the calls are made for the build).
    Raises ContextPackUnavailable when the tools or the graph cannot be reached.
    """
    try:
        from actron.graph.store import store_for
        from actron.mcp_graph.tools import ToolContext, call_tool
    except ImportError as exc:
        raise ContextPackUnavailable("actron.mcp_graph.tools is not available") from exc
    try:
        store = store_for(ws)
    except Exception as exc:
        raise ContextPackUnavailable(f"graph for {ws} is not reachable: {exc}") from exc
    ctx = ToolContext(ws=ws, store=store, emit=emit, snapshot_sha=snapshot_sha,
                      differing_paths=frozenset(differing_paths or []), by="pi", repo_dir=repo_dir)

    async def call(name: str, args: dict[str, Any]) -> Any:
        return await call_tool(ctx, name, args)

    return call


async def empty_tools(name: str, args: dict[str, Any]) -> Any:
    """Used when the graph tools are unavailable: every call returns an error, so the pack says so."""
    return {"error": {"code": "unavailable", "message": "graph tools are not available"}}
