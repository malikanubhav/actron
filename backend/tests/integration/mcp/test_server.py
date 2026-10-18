"""The MCP server through the SDK's own client (spec B, B4). B-AC-18, B-AC-20, B-AC-21."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from actron.mcp_graph import server as srv
from actron.mcp_graph.tools import TOOL_NAMES, TOOLS, ToolContext, call_tool
from tests.integration.graph import fixture_graph as fx
from tests.integration.mcp.conftest import EventLog

pytestmark = pytest.mark.integration


async def test_sdk_client_lists_exactly_the_bc4_tools_with_schemas(tool_ctx: ToolContext) -> None:
    """B-AC-18: the SDK client lists exactly the B.C4 tools; each input schema matches its Pydantic model."""
    async with srv.graph_client(tool_ctx) as client:
        tools = await client.list_tools()
    assert [t["name"] for t in tools] == list(TOOL_NAMES)
    for t in tools:
        model = TOOLS[t["name"]].input_model
        expected = model.model_json_schema()
        schema = t["inputSchema"]
        assert set(schema["properties"]) == set(expected["properties"]), t["name"]
        assert set(schema.get("required", [])) == set(expected.get("required", [])), t["name"]
        assert "for example" in t["description"], t["name"]
    search = next(t for t in tools if t["name"] == "search")["inputSchema"]["properties"]
    assert search["limit"]["maximum"] == 20
    callers = next(t for t in tools if t["name"] == "callers")["inputSchema"]["properties"]
    assert callers["depth"]["maximum"] == 3 and callers["depth"]["minimum"] == 1


async def test_sdk_call_matches_direct_call_and_emits(tool_ctx: ToolContext, events: EventLog) -> None:
    """B-AC-21: a call through the SDK client returns the tool's output and emits both events with node ids."""
    direct = await call_tool(tool_ctx, "decisions_for", {"ids": [fx.EVAL_SAVE]})
    events.events.clear()
    async with srv.graph_client(tool_ctx) as client:
        via_mcp = await client.call("decisions_for", {"ids": [fx.EVAL_SAVE]})
        schemas = await client.function_schemas()
        bad = await client.call("callers", {"functionId": fx.EVAL_CODE, "depth": 9})
    assert via_mcp == direct
    types = [t for t, _ in events.events]
    assert types[:2] == ["tool.called", "tool.result"]
    assert fx.D_SAVE in events.of("tool.result")[0]["nodeIds"]
    assert schemas[0]["type"] == "function" and schemas[0]["function"]["name"] == "search"
    assert "error" in bad


@pytest.fixture
async def aredis(redis_url: str) -> AsyncIterator[Any]:
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def other_graph(falkordb_url: str, ontology: Any) -> Any:
    from actron.graph.store import GraphStore

    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    store = GraphStore(falkordb_url, name, ontology, workspace_id=name)
    store.upsert_nodes("CodeFunction", [{
        "id": "code:fn:other/secret:src/b.ts::evaluateSecretly", "name": "evaluateSecretly",
        "qualifiedName": "evaluateSecretly", "startLine": 1, "endLine": 2, "body": "evaluate secretly",
        "contentHash": "x",
    }])
    store.query("CALL db.idx.fulltext.createNodeIndex('CodeFunction', 'body', 'name', 'qualifiedName')")
    try:
        yield store
    finally:
        store.drop()
        store.close()


async def test_run_token_scopes_to_one_workspace(small_graph: Any, other_graph: Any, aredis: Any) -> None:
    """B-AC-20: a run token for workspace A reads only A; it cannot reach B; no or unknown tokens are refused."""
    stores = {small_graph.workspace_id: small_graph, other_graph.workspace_id: other_graph}
    token_a = await srv.register_run_token(small_graph.workspace_id, 60, request_id="req_a", redis=aredis)
    info = await srv.resolve_run_token(token_a, redis=aredis)
    assert info is not None and info.ws == small_graph.workspace_id and info.request_id == "req_a"
    assert await aredis.ttl(srv.RUN_KEY.format(token=token_a)) > 0

    class FakeContext:
        def __init__(self, token: str | None) -> None:
            self.headers = {srv.RUN_HEADER: token} if token else {}

    resolved: list[ToolContext] = []

    async def resolve(ctx: Any) -> ToolContext:
        token = (ctx.headers or {}).get(srv.RUN_HEADER)
        info = await srv.resolve_run_token(token, redis=aredis)
        if info is None:
            raise srv.Unauthorized("A valid X-Actron-Run token is required")
        tc = ToolContext(ws=info.ws, store=stores[info.ws])
        resolved.append(tc)
        return tc

    server = srv.build_server(resolve)
    search_fn = server._tool_manager.get_tool("search").fn  # the registered tool function
    import json

    out_a = json.loads(await search_fn(ctx=FakeContext(token_a), query="evaluate", types=None, limit=20))
    assert fx.EVAL_CODE in {r["id"] for r in out_a}
    assert all("other/secret" not in r["id"] for r in out_a)
    node_b = json.loads(await server._tool_manager.get_tool("get_node").fn(
        ctx=FakeContext(token_a), id="code:fn:other/secret:src/b.ts::evaluateSecretly"))
    assert node_b["error"]["code"] == "not_found"
    for bad in (None, "not-a-token"):
        refused = json.loads(await search_fn(ctx=FakeContext(bad), query="evaluate", types=None, limit=5))
        assert refused["error"]["code"] == "unauthorized"
    assert {tc.ws for tc in resolved} == {small_graph.workspace_id}
    await srv.revoke_run_token(token_a, redis=aredis)
    assert await srv.resolve_run_token(token_a, redis=aredis) is None
