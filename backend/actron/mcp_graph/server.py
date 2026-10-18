"""The MCP graph server (spec B, B4) built with the official MCP Python SDK.

Verified against the installed SDK (`mcp` 2.3.0, 17 Oct 2026): the v1 `FastMCP` class is now
`mcp.server.mcpserver.MCPServer`; `mcp.Client(server)` connects in-process; `Client(url or transport)`
speaks Streamable HTTP; tools receive the HTTP request headers through `Context.headers`.

Two ways in:
- in-process, for the investigator: `async with graph_client(tool_ctx) as client: ...`;
- Streamable HTTP at `/mcp` on `ACTRON_MCP_PORT` (internal network only), for Pi. Every request must carry
  `X-Actron-Run: <token>`; the token maps to one workspace through the Redis key `mcp:run:<token>`
  (written by `register_run_token`). Unknown or expired tokens get 401 before the MCP layer runs, and a
  tool call can only ever read the token's own workspace graph.
"""

from __future__ import annotations

import inspect
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from actron.logging import get_logger
from actron.mcp_graph.tools import TOOLS, EventSink, ToolContext, ToolSpec, call_tool

log = get_logger(__name__)

RUN_HEADER = "X-Actron-Run"
RUN_KEY = "mcp:run:{token}"
DEFAULT_TOKEN_TTL_S = 4 * 3600
INSTRUCTIONS = (
    "Read-only tools over the team's history graph (code, git, GitHub, Slack, Linear, decisions). "
    "Start with search, then get_node, decisions_for, callers, impact, related_work, tests_for and owners. "
    "Code tools serve source from the graph snapshot; each response names the snapshot commit."
)

ContextResolver = Callable[[Context], Awaitable[ToolContext]]


class Unauthorized(Exception):
    """The request has no valid run token."""


def _make_tool_fn(spec: ToolSpec, resolve: ContextResolver) -> Callable[..., Awaitable[str]]:
    """A function whose signature is the tool's input model, so the SDK publishes the same JSON schema."""

    async def fn(ctx: Context, **kwargs: Any) -> str:
        try:
            tool_ctx = await resolve(ctx)
        except Unauthorized as exc:
            return json.dumps({"error": {"code": "unauthorized", "message": str(exc)}})
        args = {k: v for k, v in kwargs.items() if v is not None}
        result = await call_tool(tool_ctx, spec.name, args)
        return json.dumps(result, default=str)

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    annotations: dict[str, Any] = {"ctx": Context, "return": str}
    for name, info in spec.input_model.model_fields.items():
        meta = [*info.metadata, Field(description=info.description)] if info.description else list(info.metadata)
        ann: Any = Annotated[(info.annotation, *meta)] if meta else info.annotation
        default = inspect.Parameter.empty if info.is_required() else info.default
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=ann, default=default))
        annotations[name] = ann
    fn.__signature__ = inspect.Signature(params, return_annotation=str)  # type: ignore[attr-defined]
    fn.__annotations__ = annotations
    fn.__name__ = spec.name
    fn.__doc__ = spec.description
    return fn


def build_server(resolve: ContextResolver, *, name: str = "actron-graph") -> MCPServer:
    """An MCP server exposing the 20 tools of B.C4; `resolve` maps each request to its ToolContext."""
    server: MCPServer = MCPServer(name=name, instructions=INSTRUCTIONS, version="1")
    for spec in TOOLS.values():
        server.add_tool(_make_tool_fn(spec, resolve), name=spec.name, description=spec.description,
                        structured_output=False)
    return server


def server_for(tool_ctx: ToolContext) -> MCPServer:
    """In-process server bound to one run's context (the investigator)."""

    async def resolve(_: Context) -> ToolContext:
        return tool_ctx

    return build_server(resolve)


def _parse(result: Any) -> Any:
    texts = [getattr(c, "text", None) for c in (getattr(result, "content", None) or [])]
    text = next((t for t in texts if isinstance(t, str)), None)
    if text is None:
        return {"error": {"code": "empty", "message": "The tool returned no content"}}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # SDK-level failures (for example schema validation) come back as plain text with is_error set.
        return {"error": {"code": "invalid_input" if getattr(result, "is_error", False) else "invalid_output",
                          "message": text}}


@dataclass
class GraphClient:
    """A thin wrapper over the SDK client: list tools (as MCP and as LLM function schemas) and call them."""

    client: Any
    tools: list[dict[str, Any]] = field(default_factory=list)

    async def list_tools(self) -> list[dict[str, Any]]:
        res = await self.client.list_tools()
        self.tools = [{"name": t.name, "description": t.description or "", "inputSchema": t.input_schema}
                      for t in res.tools]
        return self.tools

    async def function_schemas(self) -> list[dict[str, Any]]:
        """The tools in the OpenAI/LiteLLM `tools` format used by `agent_completion`."""
        tools = self.tools or await self.list_tools()
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["inputSchema"]}} for t in tools]

    async def call(self, name: str, args: Mapping[str, Any] | None = None) -> Any:
        res = await self.client.call_tool(name, dict(args or {}))
        return _parse(res)


@asynccontextmanager
async def graph_client(tool_ctx: ToolContext) -> AsyncIterator[GraphClient]:
    """In-process MCP client for one run (the investigator). Tool events go to `tool_ctx.emit`."""
    from mcp import Client

    async with Client(server_for(tool_ctx)) as client:
        yield GraphClient(client)


# ------------------------------------------------------------------------------------------- run tokens


@dataclass(frozen=True)
class RunInfo:
    ws: str
    request_id: str | None = None
    snapshot_sha: str | None = None
    differing_paths: tuple[str, ...] = ()
    by: str = "pi"


def _redis(url: str | None = None) -> Any:
    import redis.asyncio as aioredis

    from actron.config import get_settings

    return aioredis.Redis.from_url(url or get_settings().REDIS_URL, decode_responses=True)


async def register_run_token(
    ws: str,
    ttl: int = DEFAULT_TOKEN_TTL_S,
    *,
    request_id: str | None = None,
    snapshot_sha: str | None = None,
    differing_paths: Sequence[str] = (),
    by: str = "pi",
    redis: Any | None = None,
) -> str:
    """Issue a token that lets an MCP client read workspace `ws` for `ttl` seconds."""
    token = secrets.token_urlsafe(24)
    value = json.dumps({"ws": ws, "requestId": request_id, "snapshotSha": snapshot_sha,
                        "differingPaths": list(differing_paths), "by": by})
    client = redis or _redis()
    try:
        await client.set(RUN_KEY.format(token=token), value, ex=int(ttl))
    finally:
        if redis is None:
            await client.aclose()
    return token


async def revoke_run_token(token: str, *, redis: Any | None = None) -> None:
    client = redis or _redis()
    try:
        await client.delete(RUN_KEY.format(token=token))
    finally:
        if redis is None:
            await client.aclose()


async def resolve_run_token(token: str | None, *, redis: Any | None = None) -> RunInfo | None:
    if not token or len(token) > 200:
        return None
    client = redis or _redis()
    try:
        raw = await client.get(RUN_KEY.format(token=token))
    finally:
        if redis is None:
            await client.aclose()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return RunInfo(ws=str(raw))  # a bare workspace id
    if not isinstance(data, dict) or not data.get("ws"):
        return None
    return RunInfo(ws=str(data["ws"]), request_id=data.get("requestId"), snapshot_sha=data.get("snapshotSha"),
                   differing_paths=tuple(data.get("differingPaths") or ()), by=str(data.get("by") or "pi"))


def _default_emit(info: RunInfo) -> EventSink | None:
    """Events for HTTP tool calls go to the request's journal through W6's service, when it exists."""
    if not info.request_id:
        return None
    try:
        from actron.flow import service
    except ImportError:
        return None
    emit_fn = getattr(service, "emit", None)
    if emit_fn is None:
        return None
    request_id = info.request_id

    async def sink(type: str, payload: dict[str, Any], *, actor: str = "actron", surface: str = "system") -> None:
        await emit_fn(info.ws, request_id, type, payload, actor=actor, surface=surface)

    return sink


def http_app(
    *,
    redis: Any | None = None,
    store_for: Callable[[str], Any] | None = None,
    emit_for: Callable[[RunInfo], EventSink | None] = _default_emit,
    allowed_hosts: Sequence[str] = ("worker:*", "worker", "127.0.0.1:*", "localhost:*"),
) -> Starlette:
    """The Streamable HTTP app (mounted at `/mcp`) with the run-token check."""
    if store_for is None:
        from actron.graph.store import store_for as default_store_for

        store_for = default_store_for
    get_store = store_for

    async def resolve(ctx: Context) -> ToolContext:
        headers = {k.lower(): v for k, v in (ctx.headers or {}).items()}
        info = await resolve_run_token(headers.get(RUN_HEADER.lower()), redis=redis)
        if info is None:
            raise Unauthorized("A valid X-Actron-Run token is required")
        return ToolContext(ws=info.ws, store=get_store(info.ws), emit=emit_for(info), run_token=None,
                           snapshot_sha=info.snapshot_sha, differing_paths=frozenset(info.differing_paths),
                           by="pi" if info.by == "pi" else "investigator")

    server = build_server(resolve)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=list(allowed_hosts),
                                         allowed_origins=[])
    inner = server.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True,
                                       transport_security=security, host="0.0.0.0")
    inner.add_middleware(_RunTokenMiddleware, redis=redis)
    return inner


class _RunTokenMiddleware:
    """Rejects HTTP requests without a valid run token before the MCP layer sees them."""

    def __init__(self, app: ASGIApp, redis: Any | None = None) -> None:
        self.app = app
        self.redis = redis

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = None
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == RUN_HEADER.lower():
                token = value.decode("latin-1")
                break
        if await resolve_run_token(token, redis=self.redis) is None:
            response = JSONResponse({"error": {"code": "unauthorized",
                                               "message": "A valid X-Actron-Run token is required"}},
                                    status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


async def serve_http(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Run the HTTP transport (the worker calls this; port ACTRON_MCP_PORT, internal network only)."""
    import uvicorn

    from actron.config import get_settings

    config = uvicorn.Config(http_app(), host=host, port=port or get_settings().ACTRON_MCP_PORT, log_level="info")
    await uvicorn.Server(config).serve()
