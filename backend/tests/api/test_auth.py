"""Auth (spec B, B12): dev login only outside prod (B-AC-58), sessions, logout, /api/me, Slack start."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from actron.config import get_settings
from tests.api._fixtures import W6Env
from tests.api.conftest import Api


async def test_dev_login_sets_cookies_and_me(anon: httpx.AsyncClient, w6: W6Env) -> None:
    """B-AC-58: dev login works in dev; it sets HttpOnly session and CSRF cookies; /api/me answers."""
    r = await anon.post("/api/auth/dev-login", json={"name": "Dana Dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["workspace"]["id"] == "dev" and body["user"]["name"] == "Dana Dev"
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("actron_session="))
    assert "HttpOnly" in session and "SameSite=lax" in session
    assert any(c.startswith("actron_csrf=") for c in cookies)
    me = await anon.get("/api/me")
    assert me.status_code == 200
    data = me.json()
    assert data["user"]["name"] == "Dana Dev" and data["workspace"]["id"] == "dev"
    assert data["env"] == "dev" and data["csrfToken"] == anon.cookies.get("actron_csrf")
    again = await anon.post("/api/auth/dev-login", json={"name": "Dana Dev"})
    assert again.json()["user"]["userId"] == body["user"]["userId"]


async def test_dev_login_uses_the_configured_dev_workspace(anon: httpx.AsyncClient, w6: W6Env,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """B-AC-58: ACTRON_DEV_WORKSPACE picks the workspace dev login creates (the e2e stack keeps its data apart)."""
    monkeypatch.setenv("ACTRON_DEV_WORKSPACE", "e2e-check")
    get_settings.cache_clear()
    try:
        r = await anon.post("/api/auth/dev-login", json={"name": "Erin Eto"})
        assert r.status_code == 200 and r.json()["workspace"]["id"] == "e2e-check"
        assert (await anon.get("/api/me")).json()["workspace"]["role"] == "owner"
    finally:
        monkeypatch.delenv("ACTRON_DEV_WORKSPACE")
        get_settings.cache_clear()


async def test_dev_login_validation(anon: httpx.AsyncClient) -> None:
    assert (await anon.post("/api/auth/dev-login", json={"name": ""})).status_code == 422


async def test_dev_login_absent_in_prod(monkeypatch: pytest.MonkeyPatch, w6: W6Env) -> None:
    """B-AC-58: in prod the dev login route is not registered (404)."""
    from actron.api.app import create_app

    settings = get_settings().model_copy(update={"ACTRON_ENV": "prod"})
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/dev-login", json={"name": "x"})
    assert r.status_code == 404
    assert "/api/auth/dev-login" not in app.openapi()["paths"]


async def test_me_requires_session(anon: httpx.AsyncClient) -> None:
    r = await anon.get("/api/me")
    assert r.status_code == 401 and r.json() == {"error": {"code": "unauthenticated", "message": "Sign in to continue."}}


async def test_logout_ends_session(api: Api) -> None:
    assert (await api.get("/api/me")).status_code == 200
    r = await api.post("/api/auth/logout")
    assert r.status_code == 204
    assert (await api.get("/api/me")).status_code == 401


async def test_slack_start_not_configured_404(anon: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """B.C7: without Slack client id and secret, sign-in start answers 404."""
    import actron.api.auth as auth

    monkeypatch.setattr(auth, "get_settings",
                        lambda: get_settings().model_copy(update={"SLACK_CLIENT_ID": None, "SLACK_CLIENT_SECRET": None}))
    assert (await anon.get("/api/auth/slack/start")).status_code == 404


async def test_slack_start_redirects(anon: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """B12: start redirects to Slack's OIDC authorize URL with scopes openid profile email and a state."""
    import actron.api.auth as auth

    monkeypatch.setattr(auth, "get_settings", lambda: get_settings().model_copy(
        update={"SLACK_CLIENT_ID": "cid", "SLACK_CLIENT_SECRET": "csecret", "ACTRON_PUBLIC_URL": "https://a.example"}))
    r = await anon.get("/api/auth/slack/start?next=/app/inbox")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://slack.com/openid/connect/authorize?")
    assert "scope=openid+profile+email" in loc and "client_id=cid" in loc
    assert "redirect_uri=https%3A%2F%2Fa.example%2Fapi%2Fauth%2Fslack%2Fcallback" in loc


async def test_slack_callback_bad_state(anon: httpx.AsyncClient) -> None:
    r = await anon.get("/api/auth/slack/callback?code=x&state=unknown")
    assert r.status_code == 302 and r.headers["location"] == "/app/signin?error=slack"


async def test_slack_callback_signs_in(anon: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, w6: W6Env) -> None:
    """B12: a valid callback creates the session and redirects to `next`."""
    import uuid

    import actron.api.auth as auth

    monkeypatch.setattr(auth, "get_settings", lambda: get_settings().model_copy(
        update={"SLACK_CLIENT_ID": "cid", "SLACK_CLIENT_SECRET": "cs"}))
    team = f"T{uuid.uuid4().hex[:8]}"

    async def exchange(code: str) -> dict[str, Any]:
        return {"ok": True, "id_token": "tok"}

    def verify(token: str, nonce: str | None) -> dict[str, Any]:
        return {"https://slack.com/team_id": team, "https://slack.com/team_name": "Acme Eng",
                "https://slack.com/user_id": f"U{team}", "name": "Ada", "email": "ada@example.com"}

    monkeypatch.setattr(auth, "exchange_code", exchange)
    monkeypatch.setattr(auth, "verify_id_token", verify)
    start = await anon.get("/api/auth/slack/start?next=/app/inbox")
    state = start.headers["location"].split("state=")[1].split("&")[0]
    r = await anon.get(f"/api/auth/slack/callback?code=abc&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/app/inbox"
    me = (await anon.get("/api/me")).json()
    assert me["user"]["name"] == "Ada" and me["workspace"]["role"] == "owner"
    reuse = await anon.get(f"/api/auth/slack/callback?code=abc&state={state}")
    assert reuse.headers["location"] == "/app/signin?error=slack"
