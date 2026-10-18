"""CSRF and rate limit (spec B, B12): missing or wrong token -> 403 on every state-changing route (B-AC-59)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.conftest import Api

EXEMPT = {"/api/auth/dev-login", "/api/auth/logout", "/webhooks/github"}


def _write_routes(app: Any) -> list[tuple[str, str]]:
    out = []
    for raw_path, ops in app.openapi()["paths"].items():
        if not raw_path.startswith("/api") or raw_path in EXEMPT:
            continue
        zero = "00000000-0000-0000-0000-000000000000"
        path = raw_path.replace("{request_id}", "req_x").replace("{conn_id}", zero)
        path = path.replace("{notification_id}", zero).replace("{provider}", "github")
        for method in {m.upper() for m in ops} & {"POST", "PUT", "PATCH", "DELETE"}:
            out.append((method, path))
    return sorted(out)


async def test_every_write_route_needs_csrf(app: Any, api: Api) -> None:
    """B-AC-59: each state-changing /api route refuses a missing and a wrong CSRF token with 403."""
    routes = _write_routes(app)
    assert len(routes) >= 18
    for method, path in routes:
        r = await api.client.request(method, path, json={})
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "csrf"
        r = await api.client.request(method, path, json={}, headers={"X-CSRF-Token": "wrong"})
        assert r.status_code == 403, (method, path)


async def test_csrf_header_must_match_cookie(api: Api) -> None:
    api.client.cookies.set("actron_csrf", "other")
    r = await api.client.post("/api/requests", json={"text": "hello world"}, headers={"X-CSRF-Token": "other"})
    assert r.status_code == 403


@pytest.mark.parametrize("n", [61])
async def test_rate_limit_60_writes_per_minute(api: Api, n: int) -> None:
    """B12: the 61st write in a minute is refused with 429."""
    codes = [(await api.post("/api/requests", {"text": "x"})).status_code for _ in range(n)]
    assert codes[:60] == [422] * 60
    assert codes[60] == 429
