"""Streamable HTTP transport for Pi (spec B, B4). B-AC-22, B-AC-20 over HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from actron.mcp_graph import server as srv
from actron.mcp_graph.tools import TOOL_NAMES
from tests.integration.graph import fixture_graph as fx
from tests.integration.mcp.conftest import EventLog

pytestmark = pytest.mark.integration

COMPOSE = Path(__file__).resolve().parents[4] / "infra" / "compose.yaml"
MCP_PORT = 8765


@pytest.fixture
async def aredis(redis_url: str) -> AsyncIterator[Any]:
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def app(small_graph: Any, aredis: Any, events: EventLog) -> Any:
    return srv.http_app(redis=aredis, store_for=lambda ws: small_graph, emit_for=lambda info: events)


async def test_http_requires_a_run_token(app: Any) -> None:
    """B-AC-22: the HTTP endpoint refuses requests without a valid X-Actron-Run token (401)."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), \
            httpx.AsyncClient(transport=transport, base_url="http://worker:8765") as client:
        none = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        bad = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                headers={srv.RUN_HEADER: "not-a-token"})
    assert none.status_code == 401 and none.json()["error"]["code"] == "unauthorized"
    assert bad.status_code == 401


async def test_http_sdk_client_lists_and_calls_tools(app: Any, small_graph: Any, aredis: Any,
                                                     events: EventLog) -> None:
    """B-AC-22: an MCP client on the internal network (Host `worker:8765`) lists the tools and calls one;
    the call is scoped to the token's workspace and emits events marked `by: pi`."""
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    token = await srv.register_run_token(small_graph.workspace_id, 60, request_id="req_pi",
                                         snapshot_sha="abc1234", differing_paths=["src/evaluate.ts"], redis=aredis)
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), headers={srv.RUN_HEADER: token},
                              base_url="http://worker:8765")
    async with app.router.lifespan_context(app), \
            Client(streamable_http_client("http://worker:8765/mcp", http_client=http)) as client:
        listed = await client.list_tools()
        res = await client.call_tool("get_code", {"id": fx.EVAL_CODE})
    assert [t.name for t in listed.tools] == list(TOOL_NAMES)
    import json

    out = json.loads(res.content[0].text)
    assert out["snapshot"] == "abc1234" and out["differs"] is True
    called = events.of("tool.called")
    assert called and called[-1]["by"] == "pi" and called[-1]["tool"] == "get_code"


async def test_http_rejects_unknown_host(app: Any, small_graph: Any, aredis: Any) -> None:
    """B-AC-22: DNS-rebinding protection only accepts the internal host names."""
    token = await srv.register_run_token(small_graph.workspace_id, 60, redis=aredis)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), \
            httpx.AsyncClient(transport=transport, base_url="http://evil.example:8765") as client:
        res = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                headers={srv.RUN_HEADER: token, "Accept": "application/json, text/event-stream"})
    assert res.status_code in (400, 403, 421)


def _published_ports(service: dict[str, Any]) -> list[str]:
    out = []
    for p in service.get("ports") or []:
        out.append(str(p["published"]) if isinstance(p, dict) and "published" in p else str(p))
    return out


def test_compose_keeps_mcp_port_internal() -> None:
    """B-AC-22: no service publishes port 8765 to the host; the worker joins the build network as `worker`."""
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services: dict[str, Any] = data["services"]
    for name, service in services.items():
        for port in _published_ports(service):
            assert str(MCP_PORT) not in port, f"{name} publishes {port}"
    worker = services["worker"]
    networks = worker.get("networks") or {}
    assert "actron-build" in networks
    assert "worker" in (networks["actron-build"] or {}).get("aliases", [])
    for name, service in services.items():
        for port in _published_ports(service):
            # Anything that is published is bound to the loopback interface only.
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"
