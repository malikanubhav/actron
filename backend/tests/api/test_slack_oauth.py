# ruff: noqa: F811
"""Slack OAuth install ("Add to Slack"): B-AC-88, B-AC-89."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select

from actron.db.crypto import decrypt_secret
from actron.db.models import Connection, Workspace
from actron.integrations import slack_oauth
from actron.integrations.slack_common import BOT_SCOPES
from tests.integration.slack.fake_slack import FakeSlack
from tests.integration.slack.slack_fixtures import _fresh_engines, fake_slack, ws_env  # noqa: F401


@pytest.fixture
def paused(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    async def fake(ws: str, flag: bool) -> None:
        calls.append((ws, flag))

    monkeypatch.setattr(slack_oauth, "set_schedule_paused", fake)
    return calls


@pytest.fixture
def bare_ws(db_session: Any) -> Iterator[str]:
    """A workspace with no Slack team yet (like the dev workspace)."""
    ws = f"dev-{uuid.uuid4().hex[:8]}"
    db_session.add(Workspace(id=ws, name="Dev", graph_name=f"actron_{ws}".replace("-", "_")))
    db_session.commit()
    yield ws
    db_session.rollback()
    db_session.execute(delete(Workspace).where(Workspace.id == ws))
    db_session.commit()


def make_app(workspace: str) -> FastAPI:
    app = FastAPI()
    app.include_router(slack_oauth.router)

    async def actor() -> slack_oauth.Actor:
        return slack_oauth.Actor("user-1", workspace)

    app.dependency_overrides[slack_oauth.get_actor] = actor
    return app


@pytest_asyncio.fixture
async def client_for() -> AsyncIterator[Any]:
    clients: list[httpx.AsyncClient] = []

    def make(workspace: str) -> httpx.AsyncClient:
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_app(workspace)), base_url="https://actron.test"
        )
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


async def start(client: httpx.AsyncClient) -> str:
    r = await client.get("/api/slack/install")
    assert r.status_code == 302
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def conn_for(db: Any, ws: str) -> Connection | None:
    db.expire_all()
    return db.execute(
        select(Connection).where(Connection.workspace_id == ws, Connection.provider == "slack")
    ).scalar_one_or_none()


async def test_B_AC_88_install_redirects_to_slack_with_scopes_and_single_use_state(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, redis_client: Any
) -> None:
    """B-AC-88"""
    r = await client_for(bare_ws).get("/api/slack/install")
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert (
        f"{loc.scheme}://{loc.netloc}{loc.path}"
        == f"http://127.0.0.1:{fake_slack.port}/oauth/v2/authorize"
    )
    q = parse_qs(loc.query, keep_blank_values=True)
    assert q["client_id"] == ["client-1"]
    assert q["scope"][0].split(",") == list(BOT_SCOPES)
    assert q["user_scope"] == [""]
    assert q["redirect_uri"] == ["https://actron.test/api/slack/oauth/callback"]
    state = q["state"][0]
    assert len(state) >= 43  # 32 random bytes, url-safe
    ttl = redis_client.ttl(f"slack:oauth:state:{state}")
    assert 0 < ttl <= 600


async def test_install_uses_the_real_authorize_host_by_default(
    fake_slack: FakeSlack,
    bare_ws: str,
    client_for: Any,
    monkeypatch: pytest.MonkeyPatch,
    redis_client: Any,
) -> None:
    from actron.config import get_settings

    monkeypatch.setenv("SLACK_API_URL", "https://slack.com/api/")
    get_settings.cache_clear()
    r = await client_for(bare_ws).get("/api/slack/install")
    assert r.headers["location"].startswith("https://slack.com/oauth/v2/authorize?")


async def test_install_not_configured_is_404(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from actron.config import get_settings

    monkeypatch.delenv("SLACK_CLIENT_ID")
    monkeypatch.setenv("SLACK_CLIENT_ID", "")
    get_settings.cache_clear()
    r = await client_for(bare_ws).get("/api/slack/install")
    assert (
        r.status_code == 404 and r.json()["detail"]["error"]["code"] == "slack_oauth_not_configured"
    )


async def test_B_AC_89_callback_stores_encrypted_installation_and_adopts_team(
    fake_slack: FakeSlack,
    bare_ws: str,
    client_for: Any,
    db_session: Any,
    paused: list[tuple[str, bool]],
    redis_client: Any,
) -> None:
    """B-AC-89: valid state and code; workspace without a team adopts the Slack team."""
    c = client_for(bare_ws)
    state = await start(c)
    r = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    assert r.status_code == 302 and r.headers["location"] == "/app/connect?slack=connected"
    token_call = fake_slack.of("oauth.v2.access")[0].params
    assert (
        token_call["code"] == "abc"
        and token_call["redirect_uri"] == "https://actron.test/api/slack/oauth/callback"
    )
    assert (
        token_call["client_id"] == "client-1" and token_call["client_secret"] == "client-secret-1"
    )

    conn = conn_for(db_session, bare_ws)
    assert conn is not None and conn.status == "connected"
    assert conn.secret_encrypted and fake_slack.oauth_token.encode() not in bytes(
        conn.secret_encrypted
    )
    assert decrypt_secret(bytes(conn.secret_encrypted)) == {"bot_token": fake_slack.oauth_token}
    assert conn.secret_last4 == fake_slack.oauth_token[-4:]
    assert conn.config["teamId"] == "T123" and conn.config["botUserId"] == "UBOT"
    assert conn.config["installedBy"] == "UINSTALLER" and "chat:write" in conn.config["scopes"]
    db_session.expire_all()
    assert db_session.get(Workspace, bare_ws).slack_team_id == "T123"
    assert paused == [(bare_ws, False)]


async def test_B_AC_89_state_is_single_use(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, paused: Any, redis_client: Any
) -> None:
    c = client_for(bare_ws)
    state = await start(c)
    first = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    again = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    assert first.headers["location"] == "/app/connect?slack=connected"
    assert again.headers["location"] == "/app/connect?slack_error=expired"
    assert len(fake_slack.of("oauth.v2.access")) == 1


async def test_B_AC_89_missing_unknown_and_expired_state(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, db_session: Any, redis_client: Any
) -> None:
    c = client_for(bare_ws)
    for params in ({"code": "abc"}, {"code": "abc", "state": "nope"}):
        r = await c.get("/api/slack/oauth/callback", params=params)
        assert r.headers["location"] == "/app/connect?slack_error=expired"
    state = await start(c)
    redis_client.delete(f"slack:oauth:state:{state}")  # what Redis does after 10 minutes
    r = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "/app/connect?slack_error=expired"
    assert fake_slack.of("oauth.v2.access") == [] and conn_for(db_session, bare_ws) is None


async def test_B_AC_89_access_denied(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, db_session: Any, redis_client: Any
) -> None:
    c = client_for(bare_ws)
    state = await start(c)
    r = await c.get("/api/slack/oauth/callback", params={"error": "access_denied", "state": state})
    assert r.headers["location"] == "/app/connect?slack_error=cancelled"
    assert (
        conn_for(db_session, bare_ws) is None
        and redis_client.get(f"slack:oauth:state:{state}") is None
    )


async def test_B_AC_89_different_team_is_refused_and_nothing_stored(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, client_for: Any, db_session: Any, paused: Any
) -> None:
    fake_slack.team_id = "TOTHER"
    before = conn_for(db_session, ws_env.ws)
    assert before is not None
    old_secret = bytes(before.secret_encrypted or b"")
    c = client_for(ws_env.ws)
    state = await start(c)
    r = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "/app/connect?slack_error=different_team"
    after = conn_for(db_session, ws_env.ws)
    assert (
        after is not None
        and bytes(after.secret_encrypted or b"") == old_secret
        and after.config["teamId"] == "T123"
    )
    assert paused == []


async def test_team_already_used_by_another_workspace_is_refused(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, bare_ws: str, client_for: Any, db_session: Any
) -> None:
    c = client_for(bare_ws)  # fake team T123 already belongs to ws_env.ws
    state = await start(c)
    r = await c.get("/api/slack/oauth/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "/app/connect?slack_error=different_team"
    assert conn_for(db_session, bare_ws) is None


async def test_slack_refusing_the_code_redirects_with_failed(
    fake_slack: FakeSlack, bare_ws: str, client_for: Any, db_session: Any
) -> None:
    fake_slack.oauth_error = "invalid_code"
    c = client_for(bare_ws)
    state = await start(c)
    r = await c.get("/api/slack/oauth/callback", params={"code": "bad", "state": state})
    assert r.headers["location"] == "/app/connect?slack_error=failed"
    assert conn_for(db_session, bare_ws) is None
