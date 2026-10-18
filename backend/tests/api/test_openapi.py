"""OpenAPI generation (spec B, B12): the document builds and lists every B.C7 route (B-AC-61)."""

from __future__ import annotations

import json
from typing import Any

import httpx

B_C7_ROUTES = [
    ("get", "/api/auth/slack/start"), ("get", "/api/auth/slack/callback"), ("post", "/api/auth/dev-login"),
    ("post", "/api/auth/logout"), ("get", "/api/me"), ("get", "/api/connectors"),
    ("post", "/api/connectors/{provider}/validate"), ("get", "/api/connectors/{provider}/options"),
    ("get", "/api/connectors/{provider}/checks"), ("get", "/api/connections"), ("post", "/api/connections"),
    ("patch", "/api/connections/{conn_id}"), ("delete", "/api/connections/{conn_id}"),
    ("post", "/api/connections/{conn_id}/sync"), ("post", "/api/connections/{conn_id}/reset-cursor"),
    ("get", "/api/ingestion/status"), ("get", "/api/ingestion/runs"), ("post", "/api/requests"), ("post", "/api/ask"),
    ("get", "/api/requests"), ("get", "/api/requests/{request_id}"), ("get", "/api/requests/{request_id}/events"),
    ("get", "/api/requests/{request_id}/replay"), ("get", "/api/public/replays/{request_id}"),
    ("post", "/api/requests/{request_id}/answers"), ("post", "/api/requests/{request_id}/ticket/revisions"),
    ("get", "/api/requests/{request_id}/ticket/revisions"), ("post", "/api/requests/{request_id}/approvals"),
    ("post", "/api/requests/{request_id}/feedback"), ("post", "/api/requests/{request_id}/cancel"),
    ("post", "/api/requests/{request_id}/retry"), ("post", "/api/requests/{request_id}/close-pr"),
    ("get", "/api/requests/{request_id}/pr/diff"), ("get", "/api/requests/{request_id}/builds/{build_id}/log"),
    ("get", "/api/graph/subgraph"), ("get", "/api/graph/nodes/{node_id}"),
    ("get", "/api/graph/nodes/{node_id}/neighbours"), ("get", "/api/graph/search"), ("get", "/api/graph/path"),
    ("get", "/api/graph/sample"), ("get", "/api/graph/stats"), ("get", "/api/graph/quick/{tool}"),
    ("get", "/api/stream"), ("get", "/api/notifications"), ("post", "/api/notifications/{notification_id}/read"),
    ("get", "/api/settings"), ("put", "/api/settings"), ("post", "/api/settings/budget"), ("get", "/api/health"),
    ("get", "/api/slack/install"), ("get", "/api/slack/oauth/callback"), ("post", "/webhooks/github"),
]


async def test_openapi_lists_every_route(anon: httpx.AsyncClient) -> None:
    """B-AC-61: /api/openapi.json generates and contains every B.C7 route."""
    r = await anon.get("/api/openapi.json")
    assert r.status_code == 200
    spec: dict[str, Any] = r.json()
    for method, path in B_C7_ROUTES:
        assert method in spec["paths"].get(path, {}), (method, path)
    for name in ("RequestDetail", "RequestSummary", "ActionResult", "Revision", "Build", "Evidence", "Question"):
        assert name in spec["components"]["schemas"], name
    json.dumps(spec)


async def test_slack_http_routes_mounted(anon: httpx.AsyncClient) -> None:
    """W9: Slack events, commands and interactions are mounted (an unsigned call is refused, not 404)."""
    for path in ("/slack/events", "/slack/commands", "/slack/interactions"):
        r = await anon.post(path, content=b"{}")
        assert r.status_code != 404, path
