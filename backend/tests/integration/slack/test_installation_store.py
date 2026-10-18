"""PostgreSQL installation store and bot token resolution (B-AC-89, B-AC-90, B-AC-91)."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from slack_sdk.oauth.installation_store.models.installation import Installation
from sqlalchemy import select

from actron.config import get_settings
from actron.db.crypto import decrypt_secret, encrypt_secret
from actron.db.models import Connection, Workspace
from actron.integrations import slack_bot, slack_oauth
from actron.integrations.slack_common import credentials_for_team, credentials_for_workspace
from actron.integrations.slack_oauth import PgInstallationStore, TeamMismatch, ensure_team
from tests.integration.slack.fake_slack import FakeSlack


@pytest.fixture(autouse=True)
def _no_temporal(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    async def fake(ws: str, flag: bool) -> None:
        calls.append((ws, flag))

    monkeypatch.setattr(slack_oauth, "set_schedule_paused", fake)
    return calls


def installation(
    ws: str, team: str = "T123", token: str = "xoxb-new-token-5555", **kw: Any
) -> Installation:
    return Installation(
        team_id=team,
        team_name="Acme",
        bot_token=token,
        bot_id="B1",
        bot_user_id="UBOT",
        bot_scopes=["chat:write", "commands"],
        user_id="UINST",
        installed_at=time.time(),
        custom_values={"workspace_id": ws},
        **kw,
    )


async def test_B_AC_89_save_stores_encrypted_token_and_config(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    store = PgInstallationStore()
    await store.async_save(installation(ws_env.ws))
    ws_env.db.expire_all()
    row = ws_env.db.execute(
        select(Connection).where(
            Connection.workspace_id == ws_env.ws, Connection.provider == "slack"
        )
    ).scalar_one()
    assert b"xoxb-new-token-5555" not in bytes(row.secret_encrypted)
    assert decrypt_secret(bytes(row.secret_encrypted)) == {"bot_token": "xoxb-new-token-5555"}
    assert row.secret_last4 == "5555" and row.status == "connected"
    assert (
        row.config["teamId"] == "T123"
        and row.config["botUserId"] == "UBOT"
        and row.config["scopes"] == ["chat:write", "commands"]
    )
    assert row.config["installedBy"] == "UINST"


async def test_save_keeps_an_app_token_stored_beside_the_bot_token(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    row.secret_encrypted = encrypt_secret(
        {"bot_token": "xoxb-old-token-1111", "app_token": "xapp-keep-me-1234"}
    )
    ws_env.db.commit()
    await PgInstallationStore().async_save(installation(ws_env.ws))
    ws_env.db.expire_all()
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    assert decrypt_secret(bytes(row.secret_encrypted)) == {
        "bot_token": "xoxb-new-token-5555",
        "app_token": "xapp-keep-me-1234",
    }


async def test_find_bot_and_installation_by_team(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    store = PgInstallationStore()
    bot = await store.async_find_bot(enterprise_id=None, team_id="T123")
    assert bot is not None and bot.bot_token == ws_env.token and bot.bot_user_id == "UBOT"
    inst = await store.async_find_installation(enterprise_id=None, team_id="T123")
    assert inst is not None and inst.bot_token == ws_env.token
    assert await store.async_find_bot(enterprise_id=None, team_id="TNOPE") is None
    assert await store.async_find_installation(enterprise_id=None, team_id=None) is None


async def test_B_AC_90_authorize_resolves_token_by_team_without_env_token(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    """B-AC-90: no SLACK_BOT_TOKEN is set; the token comes from the stored installation."""
    assert get_settings().SLACK_BOT_TOKEN is None
    res = await slack_bot.authorize(enterprise_id=None, team_id="T123", user_id="U1")
    assert res is not None and res.bot_token == ws_env.token and res.bot_user_id == "UBOT"
    assert await slack_bot.authorize(enterprise_id=None, team_id="TNOPE") is None
    creds = await credentials_for_workspace(ws_env.ws)
    assert creds is not None and creds.token == ws_env.token and creds.team_id == "T123"


async def test_env_bot_token_is_only_a_fallback(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-env-fallback-0000")
    get_settings.cache_clear()
    res = await slack_bot.authorize(enterprise_id=None, team_id="T123")
    assert res is not None and res.bot_token == ws_env.token  # a stored installation always wins
    other = await slack_bot.authorize(enterprise_id=None, team_id="TNOPE")
    assert other is not None and other.bot_token == "xoxb-env-fallback-0000"
    assert fake_slack.of("auth.test")  # bot ids learned once from auth.test


async def test_disconnected_connection_is_not_used(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    await PgInstallationStore().async_delete_all(enterprise_id=None, team_id="T123")
    assert await credentials_for_team("T123") is None
    assert await credentials_for_workspace(ws_env.ws) is None


async def test_B_AC_91_delete_marks_disconnected_and_pauses_schedule(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, _no_temporal: list[tuple[str, bool]]
) -> None:
    """B-AC-91"""
    await PgInstallationStore().async_delete_bot(enterprise_id=None, team_id="T123")
    ws_env.db.expire_all()
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    assert (
        row.status == "disconnected" and row.secret_encrypted is None and row.secret_last4 is None
    )
    assert row.config["teamId"] == "T123"  # kept so the Connect screen can show what was connected
    assert _no_temporal == [(ws_env.ws, True)]


async def test_disconnect_keeps_the_app_token(
    fake_slack: FakeSlack, ws_env: SimpleNamespace
) -> None:
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    row.secret_encrypted = encrypt_secret(
        {"bot_token": "xoxb-old-token-1111", "app_token": "xapp-keep-me-1234"}
    )
    ws_env.db.commit()
    await slack_oauth.disconnect_team("T123")
    ws_env.db.expire_all()
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    assert decrypt_secret(bytes(row.secret_encrypted)) == {"app_token": "xapp-keep-me-1234"}


async def test_save_without_a_workspace_is_refused(
    fake_slack: FakeSlack, db_session: Any, redis_client: Any
) -> None:
    inst = installation("x")
    inst.custom_values = {}
    inst.team_id = "T-nobody-" + uuid.uuid4().hex[:6]
    with pytest.raises(ValueError):
        await PgInstallationStore().async_save(inst)


async def test_ensure_team_adopts_then_refuses_other_teams(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, db_session: Any
) -> None:
    other = f"dev-{uuid.uuid4().hex[:8]}"
    db_session.add(Workspace(id=other, name="Dev", graph_name=f"actron_{other}".replace("-", "_")))
    db_session.commit()
    try:
        await ensure_team(other, "TNEW" + other[-6:])  # adopts
        await ensure_team(other, "TNEW" + other[-6:])  # same team again is fine
        with pytest.raises(TeamMismatch):
            await ensure_team(other, "TELSE")
        with pytest.raises(TeamMismatch):
            await ensure_team(other, ws_env.team)  # belongs to another Actron workspace
        with pytest.raises(TeamMismatch):
            await ensure_team("no-such-workspace", "T1")
    finally:
        db_session.rollback()
        db_session.query(Workspace).filter_by(id=other).delete()
        db_session.commit()


def _only_slack_connection(db: Any, keep_ws: str | None) -> None:
    """The test database is shared by the session; drop Slack connections other tests left behind."""
    for row in db.execute(select(Connection).where(Connection.provider == "slack")).scalars():
        if row.workspace_id != keep_ws:
            db.delete(row)
    db.commit()


async def test_run_socket_mode_returns_without_an_app_token(
    fake_slack: FakeSlack, db_session: Any
) -> None:
    _only_slack_connection(db_session, None)
    await slack_bot.run_socket_mode()


async def test_run_socket_mode_uses_the_stored_app_token(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Socket Mode is started with the connection's app-level token (the websocket itself is not opened here)."""
    row = ws_env.db.execute(
        select(Connection).where(Connection.workspace_id == ws_env.ws)
    ).scalar_one()
    row.secret_encrypted = encrypt_secret(
        {"bot_token": ws_env.token, "app_token": "xapp-stored-app-4321"}
    )
    ws_env.db.commit()
    _only_slack_connection(ws_env.db, ws_env.ws)
    seen: dict[str, Any] = {}

    class FakeHandler:
        def __init__(self, app: Any, token: str, web_client: Any = None) -> None:
            seen.update(
                token=token,
                base_url=web_client.base_url,
                verify=app._request_verification_enabled
                if hasattr(app, "_request_verification_enabled")
                else None,
            )

        async def start_async(self) -> None:
            seen["started"] = True

        async def close_async(self) -> None:
            seen["closed"] = True

    monkeypatch.setattr(slack_bot, "AsyncSocketModeHandler", FakeHandler)
    slack_bot.reset_apps()
    await slack_bot.run_socket_mode()
    assert seen["token"] == "xapp-stored-app-4321" and seen["started"] and seen["closed"]
    assert seen["base_url"] == fake_slack.api_url
