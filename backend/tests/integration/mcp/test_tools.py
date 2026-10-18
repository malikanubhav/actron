"""The 20 graph tools on the fixture graph (spec B, B.C4). B-AC-19, B-AC-21, B-AC-70, B-AC-80 (marking)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from actron.mcp_graph.tools import TOOL_NAMES, ToolContext, call_tool
from tests.integration.graph import fixture_graph as fx
from tests.integration.mcp.conftest import EventLog

pytestmark = pytest.mark.integration

HEAD = "f1xa000000000000000000000000000000000005"

BC4 = (
    "search", "get_node", "callers", "callees", "impact", "criticality", "shortest_path", "decisions_for",
    "related_work", "tests_for", "owners", "procedures_for", "get_code", "get_code_range", "file_outline",
    "find_symbol", "references", "history", "get_code_at", "search_code",
)


def _keys(*names: str) -> Callable[[Any], None]:
    def check(out: Any) -> None:
        items = out if isinstance(out, list) else [out]
        assert items, "expected at least one item"
        for item in items:
            assert set(names) <= set(item), (set(names) - set(item))
    return check


CASES: list[tuple[str, dict[str, Any], Callable[[Any], None]]] = [
    ("search", {"query": "evaluate on save"}, _keys("id", "type", "label", "snippet", "score")),
    ("get_node", {"id": fx.EVAL_SAVE}, _keys("id", "type", "properties", "links")),
    ("callers", {"functionId": fx.EVAL_CODE, "depth": 2}, _keys("id", "label", "depth", "callSiteLines", "confidence")),
    ("callees", {"functionId": fx.EVAL_CODE}, _keys("id", "label", "depth", "callSiteLines", "confidence")),
    ("impact", {"ids": [fx.EVAL_CODE]}, _keys("functions", "files", "tests", "components")),
    ("criticality", {"ids": [fx.SEND]}, _keys("id", "pageRank", "callerCount", "transitiveCallerCount",
                                               "criticalityPercentile")),
    ("shortest_path", {"fromId": fx.M1, "toId": fx.EVAL_CODE}, _keys("found", "nodes", "links")),
    ("decisions_for", {"ids": [fx.EVAL_SAVE]}, _keys("decisionId", "statement", "status", "quote", "source", "scope",
                                                     "constrains")),
    ("related_work", {"ids": [fx.EVAL_SAVE]}, _keys("id", "type", "title", "state", "url", "at")),
    ("tests_for", {"ids": [fx.PRETTY]}, _keys("testId", "label", "method", "confidence")),
    ("owners", {"ids": [fx.SEND]}, _keys("personId", "name", "basis", "score")),
    ("procedures_for", {"ids": [fx.EVAL_CODE]}, _keys("procedureId", "title", "testCommand", "coChangedPaths",
                                                       "steps")),
    ("get_code", {"id": fx.EVAL_CODE}, _keys("id", "path", "startLine", "endLine", "language", "code", "snapshot")),
    ("get_code_range", {"path": "src/evaluate.ts", "startLine": 6, "endLine": 11},
     _keys("path", "startLine", "endLine", "code", "snapshot")),
    ("file_outline", {"path": "src/connector.ts"}, _keys("path", "language", "classes", "functions", "imports",
                                                          "snapshot")),
    ("find_symbol", {"name": "evaluateCode"}, _keys("id", "qualifiedName", "path", "startLine", "signature",
                                                     "snapshot")),
    ("references", {"id": fx.EVAL_CODE}, _keys("callerId", "callerQualifiedName", "path", "line", "snippet")),
    ("history", {"id": fx.FORMAT}, _keys("commitSha", "shortSha", "subject", "author", "authoredAt", "changeType",
                                          "linesChanged")),
    ("search_code", {"query": "prettyPrint"}, _keys("id", "path", "startLine", "endLine", "snippet", "score")),
]


def test_tool_names_are_exactly_bc4() -> None:
    """B-AC-18: the registry has exactly the 20 tools of B.C4, in order."""
    assert TOOL_NAMES == BC4


@pytest.mark.parametrize(("name", "args", "check"), CASES, ids=[c[0] for c in CASES])
async def test_each_tool_returns_documented_shape(tool_ctx: ToolContext, name: str, args: dict[str, Any],
                                                  check: Callable[[Any], None]) -> None:
    """B-AC-19: each tool returns its documented shape on the fixture graph."""
    out = await call_tool(tool_ctx, name, args)
    assert not (isinstance(out, dict) and "error" in out), out
    check(out)


async def test_every_call_emits_called_and_result_with_node_ids(tool_ctx: ToolContext, events: EventLog) -> None:
    """B-AC-21: every call emits tool.called then tool.result with the node ids returned."""
    out = await call_tool(tool_ctx, "callers", {"functionId": fx.EVAL_CODE, "depth": 1})
    called, result = events.events
    assert called[0] == "tool.called" and result[0] == "tool.result"
    assert called[1]["tool"] == "callers" and called[1]["by"] == "investigator"
    assert called[1]["args"] == {"functionId": fx.EVAL_CODE, "depth": 1}
    assert result[1]["callId"] == called[1]["callId"] and result[1]["ok"] is True
    assert set(result[1]["nodeIds"]) == {c["id"] for c in out}
    assert result[1]["summary"] == "4 callers" and isinstance(result[1]["durationMs"], int)
    assert set(result[1]["nodeIds"]) <= tool_ctx.returned_ids
    bad = await call_tool(tool_ctx, "get_node", {"id": "nope"})
    assert bad["error"]["code"] == "invalid_input"
    assert events.of("tool.result")[-1]["ok"] is False and events.of("tool.result")[-1]["error"]


async def test_limits_and_errors_never_raise(tool_ctx: ToolContext) -> None:
    """B-AC-19: limits are enforced (depth <= 3, limit <= 20, 400 lines) and errors come back as data."""
    assert (await call_tool(tool_ctx, "callers", {"functionId": fx.EVAL_CODE, "depth": 5}))["error"]["code"] == \
        "invalid_input"
    assert (await call_tool(tool_ctx, "search", {"query": "x", "limit": 50}))["error"]["code"] == "invalid_input"
    big = await call_tool(tool_ctx, "get_code_range", {"path": "src/evaluate.ts", "startLine": 1, "endLine": 500})
    assert big["error"]["code"] == "invalid_input"
    assert (await call_tool(tool_ctx, "nope", {}))["error"]["code"] == "unknown_tool"
    assert (await call_tool(tool_ctx, "get_node", {"id": fx.FN + "src/x.ts::missing"}))["error"]["code"] == "not_found"
    assert (await call_tool(tool_ctx, "callers", {"functionId": fx.EVAL_FILE}))["error"]["code"] == "invalid_input"
    assert (await call_tool(tool_ctx, "search", {"query": "x", "extra": 1}))["error"]["code"] == "invalid_input"


async def test_no_secrets_and_bodies_truncated(tool_ctx: ToolContext, small_graph: Any) -> None:
    """B-AC-19: secret-looking properties are never returned; text above 4,000 characters is truncated."""
    small_graph.query("MATCH (f:CodeFunction {id: $id}) SET f.apiToken = 'tok-123456', f.clientSecret = 's3cr3t', "
                      "f.body = $body", {"id": fx.EVAL_CODE, "body": "x" * 9000})
    out = await call_tool(tool_ctx, "get_node", {"id": fx.EVAL_CODE})
    props = out["properties"]
    assert "apiToken" not in props and "clientSecret" not in props
    assert len(props["body"]) < 4100 and props["body"].startswith("x" * 4000)
    assert "truncated" in props["body"]
    assert len(out["links"]["outgoing"]) <= 50 and len(out["links"]["incoming"]) <= 50


async def test_get_node_links(tool_ctx: ToolContext) -> None:
    """B-AC-19: get_node lists outgoing and incoming links with type, endpoint, method and confidence."""
    out = await call_tool(tool_ctx, "get_node", {"id": fx.D_SAVE})
    outgoing = {(lk["type"], lk["toId"]) for lk in out["links"]["outgoing"]}
    assert ("CONSTRAINS", fx.EVAL_SAVE) in outgoing and ("EXTRACTED_FROM", fx.M1) in outgoing
    assert all({"type", "toId", "toType", "method", "confidence"} <= set(lk) for lk in out["links"]["outgoing"])


async def test_decisions_for_excludes_superseded_by_default(tool_ctx: ToolContext) -> None:
    """B-AC-19: includeSuperseded defaults to false."""
    plain = await call_tool(tool_ctx, "decisions_for", {"ids": [fx.SHOW]})
    every = await call_tool(tool_ctx, "decisions_for", {"ids": [fx.SHOW], "includeSuperseded": True})
    assert [d["decisionId"] for d in plain] == [fx.D_OUTPUT]
    assert {d["decisionId"] for d in every} == {fx.D_OUTPUT, fx.D_INLINE}


async def test_code_tools_serve_the_snapshot(tool_ctx: ToolContext) -> None:
    """B-AC-70: code tools return line-numbered source from the graph snapshot with the snapshot sha."""
    code = await call_tool(tool_ctx, "get_code", {"id": fx.EVAL_SAVE})
    assert code["snapshot"] == HEAD and code["path"] == "src/evaluate.ts"
    assert (code["startLine"], code["endLine"]) == (25, 30)
    assert code["code"].splitlines()[0] == "   25  export async function evaluateOnSave(session: ReplSession, document: string) {"
    rng = await call_tool(tool_ctx, "get_code_range", {"path": "src/evaluate.ts", "startLine": 13, "endLine": 15})
    assert rng["code"].splitlines() == [
        "   13  export function formatEvalResult(raw: string): string {",
        "   14    return prettyPrint(raw);",
        "   15  }",
    ]
    whole = await call_tool(tool_ctx, "get_code", {"id": fx.EVAL_FILE})
    assert whole["startLine"] == 1 and whole["endLine"] == 30
    # A file without stored text is rebuilt from its functions, classes and chunks.
    printer = await call_tool(tool_ctx, "get_code_range", {"path": "src/printer.ts", "startLine": 3, "endLine": 6})
    assert "prettyPrint" in printer["code"]


async def test_file_outline_find_symbol_references_search_code(tool_ctx: ToolContext) -> None:
    """B-AC-70: outline, symbol lookup stages, call sites with context and code search."""
    outline = await call_tool(tool_ctx, "file_outline", {"path": "src/connector.ts"})
    assert [c["name"] for c in outline["classes"]] == ["ReplSession"]
    assert [m["name"] for m in outline["classes"][0]["methods"]] == ["eval", "close"]
    assert [f["qualifiedName"] for f in outline["functions"]] == ["connect", "disconnect", "sendMessage"]
    ev = await call_tool(tool_ctx, "file_outline", {"path": "src/evaluate.ts"})
    assert {i["target"] for i in ev["imports"]} == {"src/connector.ts", "src/printer.ts", "src/results/output.ts",
                                                    "src/settings.ts"}
    exact = await call_tool(tool_ctx, "find_symbol", {"name": "evaluateCode"})
    assert [s["id"] for s in exact] == [fx.EVAL_CODE]
    any_case = await call_tool(tool_ctx, "find_symbol", {"name": "EVALUATECODE"})
    assert [s["id"] for s in any_case] == [fx.EVAL_CODE]
    suffix = await call_tool(tool_ctx, "find_symbol", {"name": "eval", "kind": "function"})
    assert fx.REPL_EVAL in {s["id"] for s in suffix}
    cls = await call_tool(tool_ctx, "find_symbol", {"name": "ReplSession", "kind": "class"})
    assert [s["id"] for s in cls] == [fx.REPL_CLASS]
    refs = await call_tool(tool_ctx, "references", {"id": fx.EVAL_CODE})
    save = next(r for r in refs if r["callerId"] == fx.EVAL_SAVE)
    assert save["line"] == 29 and save["path"] == "src/evaluate.ts"
    assert save["snippet"].splitlines()[0].startswith("   27") and "evaluateCode(session, document)" in save["snippet"]
    assert fx.LEGACY not in {r["callerId"] for r in refs}
    found = await call_tool(tool_ctx, "search_code", {"query": "prettyPrint", "pathPrefix": "src/printer"})
    assert found and all(r["path"].startswith("src/printer") for r in found)
    assert all(r["snapshot"] == HEAD for r in found)


async def test_differing_files_are_marked(small_graph: Any, events: EventLog) -> None:
    """B-AC-80 (code-tool part): files that differ on the target branch are marked in code-tool responses."""
    ctx = ToolContext(ws=small_graph.workspace_id, store=small_graph, emit=events, by="pi",
                      snapshot_sha="abc1234", differing_paths=frozenset({"src/evaluate.ts"}))
    code = await call_tool(ctx, "get_code", {"id": fx.EVAL_CODE})
    assert code["differs"] is True and code["snapshot"] == "abc1234" and "target branch" in code["note"]
    other = await call_tool(ctx, "get_code", {"id": fx.SEND})
    assert "differs" not in other
    sym = await call_tool(ctx, "find_symbol", {"name": "evaluateOnSave"})
    assert sym[0]["differs"] is True
    assert events.of("tool.called")[0]["by"] == "pi"


async def test_history_follows_renames(tool_ctx: ToolContext) -> None:
    """B-AC-82 (graph part): history lists commits newest first, including those before a rename."""
    out = await call_tool(tool_ctx, "history", {"id": fx.FORMAT})
    assert [(h["shortSha"], h["name"], h["changeType"]) for h in out] == [
        ("f1xa000", "formatEvalResult", "added"),
        ("f1xa000", "formatResult", "deleted"),
        ("f1xa000", "formatResult", "added"),
    ]
    assert [h["authoredAt"] for h in out] == ["2026-05-10T09:00:00Z", "2026-05-10T09:00:00Z", "2026-01-15T10:00:00Z"]
    assert out[0]["prNumber"] == 103 and out[1]["renamed"] is True
    limited = await call_tool(tool_ctx, "history", {"id": fx.FORMAT, "limit": 1})
    assert len(limited) == 1
