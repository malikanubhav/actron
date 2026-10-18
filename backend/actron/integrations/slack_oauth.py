"""Slack OAuth install ("Add to Slack"), the PostgreSQL installation store and disconnect handling (spec B, B11a).

Routes (FastAPI `router`): GET /api/slack/install and GET /api/slack/oauth/callback.
The installation is the `connections` row with provider `slack`; the bot token is stored encrypted as
`{"bot_token": ...}` (the same shape the token form uses, so `app_token` can sit beside it).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import secrets
import time
from dataclasses import dataclass
from logging import Logger
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from slack_sdk.oauth.installation_store.async_installation_store import AsyncInstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation
from sqlalchemy import select

from actron.config import get_settings
from actron.db.crypto import encrypt_secret, last4
from actron.db.models import Connection, Workspace
from actron.db.session import async_session
from actron.integrations.slack_common import (
    BOT_SCOPES,
    OAUTH_CALLBACK_PATH,
    BotCredentials,
    credentials_for_team,
    log,
    redis_client,
    secret_dict,
    web_client,
    workspace_for_team,
)

STATE_TTL_SECONDS = 600
STATE_PREFIX = "slack:oauth:state:"
CONNECT = "/app/connect"

router = APIRouter()


# ---------------------------------------------------------------- team and schedule helpers


class TeamMismatch(Exception):
    """The Slack team does not belong to this Actron workspace."""


async def ensure_team(ws: str, team_id: str) -> None:
    """A workspace with no team adopts the first one it connects; after that only that team is accepted.

    Token-form connections should call this too (W3 / W6), with the team from `auth.test`."""
    async with async_session() as session:
        row = (
            await session.execute(select(Workspace).where(Workspace.id == ws))
        ).scalar_one_or_none()
        if row is None:
            raise TeamMismatch(f"workspace {ws} does not exist")
        if row.slack_team_id == team_id:
            return
        if row.slack_team_id is not None:
            raise TeamMismatch(
                "This workspace is already connected to a different Slack workspace."
            )
        other = (
            await session.execute(select(Workspace.id).where(Workspace.slack_team_id == team_id))
        ).scalar_one_or_none()
        if other is not None:
            raise TeamMismatch(
                "That Slack workspace is already connected to another Actron workspace."
            )
        row.slack_team_id = team_id


async def set_schedule_paused(ws: str, paused: bool) -> None:
    """Pause or resume the Slack catch-up schedule. Best effort; Temporal being down only logs."""
    try:
        from temporalio.client import Client

        from actron.workflows import schedules

        s = get_settings()
        client = await asyncio.wait_for(
            Client.connect(s.TEMPORAL_ADDRESS, namespace=s.TEMPORAL_NAMESPACE), timeout=5
        )
        sid = schedules.schedule_id(ws, "slack")
        if paused:
            await schedules.pause_schedule(client, sid, "slack disconnected")
        else:
            await schedules.unpause_schedule(client, sid, "slack reconnected")
    except Exception:
        log.warning("could not change the slack schedule for %s", ws, exc_info=True)


async def save_installation(
    ws: str,
    *,
    team_id: str,
    team_name: str | None,
    bot_token: str,
    bot_user_id: str | None,
    bot_id: str | None,
    scopes: list[str],
    installed_by: str | None,
    enterprise_id: str | None,
    app_id: str | None = None,
) -> None:
    config = {
        "teamId": team_id,
        "teamName": team_name,
        "botUserId": bot_user_id,
        "botId": bot_id,
        "scopes": scopes,
        "installedBy": installed_by,
        "enterpriseId": enterprise_id,
        "appId": app_id,
    }
    async with async_session() as session:
        conn = (
            await session.execute(
                select(Connection).where(
                    Connection.workspace_id == ws, Connection.provider == "slack"
                )
            )
        ).scalar_one_or_none()
        if conn is None:
            conn = Connection(workspace_id=ws, provider="slack", config={})
            session.add(conn)
        existing = secret_dict(conn.secret_encrypted)
        conn.config = {**(conn.config or {}), **config}
        conn.secret_encrypted = encrypt_secret({**existing, "bot_token": bot_token})
        conn.secret_last4 = last4(bot_token)
        conn.status = "connected"


async def disconnect_team(team_id: str | None, *, reason: str = "uninstalled") -> list[str]:
    """Mark the team's Slack connection disconnected, drop the dead bot token, pause its schedule (B-AC-91)."""
    if not team_id:
        return []
    done: list[str] = []
    async with async_session() as session:
        rows = (
            (await session.execute(select(Connection).where(Connection.provider == "slack")))
            .scalars()
            .all()
        )
        team_of = {
            w.id: w.slack_team_id
            for w in (await session.execute(select(Workspace))).scalars().all()
        }
        for conn in rows:
            if (conn.config or {}).get("teamId") != team_id and team_of.get(
                conn.workspace_id
            ) != team_id:
                continue
            rest = {k: v for k, v in secret_dict(conn.secret_encrypted).items() if k != "bot_token"}
            conn.secret_encrypted = encrypt_secret(rest) if rest else None
            conn.secret_last4 = None
            conn.status = "disconnected"
            conn.config = {**(conn.config or {}), "disconnectedReason": reason}
            done.append(conn.workspace_id)
    for ws in done:
        await set_schedule_paused(ws, True)
    return done


# ---------------------------------------------------------------- installation store


class PgInstallationStore(AsyncInstallationStore):
    """Bolt's installation store interface on top of the `connections` table (bot-scope installs only)."""

    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger or log

    @property
    def logger(self) -> Logger:
        return self._logger

    async def async_save(self, installation: Installation) -> None:
        ws = installation.custom_values.get("workspace_id") if installation.custom_values else None
        ws = ws or await workspace_for_team(installation.team_id)
        if not ws or not installation.team_id or not installation.bot_token:
            raise ValueError("an installation needs a workspace, a team id and a bot token")
        await ensure_team(str(ws), installation.team_id)
        await save_installation(
            str(ws),
            team_id=installation.team_id,
            team_name=installation.team_name,
            bot_token=installation.bot_token,
            bot_user_id=installation.bot_user_id,
            bot_id=installation.bot_id,
            scopes=list(installation.bot_scopes or []),
            installed_by=installation.user_id,
            enterprise_id=installation.enterprise_id,
            app_id=installation.app_id,
        )

    async def async_save_bot(self, bot: Bot) -> None:
        await self.async_save(
            Installation(
                app_id=bot.app_id,
                enterprise_id=bot.enterprise_id,
                team_id=bot.team_id,
                team_name=bot.team_name,
                bot_token=bot.bot_token,
                bot_id=bot.bot_id,
                bot_user_id=bot.bot_user_id,
                bot_scopes=bot.bot_scopes,
                user_id="",
                custom_values=bot.custom_values,
            )
        )

    async def async_find_bot(
        self,
        *,
        enterprise_id: str | None,
        team_id: str | None,
        is_enterprise_install: bool | None = False,
    ) -> Bot | None:
        creds = await credentials_for_team(team_id)
        return None if creds is None else _bot(creds, enterprise_id)

    async def async_find_installation(
        self,
        *,
        enterprise_id: str | None,
        team_id: str | None,
        user_id: str | None = None,
        is_enterprise_install: bool | None = False,
    ) -> Installation | None:
        creds = await credentials_for_team(team_id)
        if creds is None:
            return None
        return Installation(
            enterprise_id=enterprise_id,
            team_id=creds.team_id,
            bot_token=creds.token,
            bot_id=creds.bot_id,
            bot_user_id=creds.bot_user_id,
            user_id=user_id or "",
            installed_at=time.time(),
        )

    async def async_delete_bot(self, *, enterprise_id: str | None, team_id: str | None) -> None:
        await disconnect_team(team_id)

    async def async_delete_installation(
        self, *, enterprise_id: str | None, team_id: str | None, user_id: str | None = None
    ) -> None:
        await disconnect_team(team_id)

    async def async_delete_all(self, *, enterprise_id: str | None, team_id: str | None) -> None:
        await disconnect_team(team_id)


def _bot(creds: BotCredentials, enterprise_id: str | None) -> Bot:
    return Bot(
        enterprise_id=enterprise_id,
        team_id=creds.team_id,
        bot_token=creds.token,
        bot_id=creds.bot_id or "",
        bot_user_id=creds.bot_user_id or "",
        installed_at=time.time(),
    )


# ---------------------------------------------------------------- actor dependency


@dataclass(frozen=True)
class Actor:
    user_id: str
    workspace_id: str


def _pick(obj: Any, *names: str) -> Any:
    for n in names:
        value = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if value is not None:
            return value
    return None


async def get_actor(request: Request) -> Actor:
    """The signed-in Actron user and workspace. Resolved lazily from `actron.api.deps.current_actor` (W6);
    override with `app.dependency_overrides[slack_oauth.get_actor]` in tests or if the signature differs."""
    try:
        deps = importlib.import_module("actron.api.deps")
        fn = deps.current_actor
    except (ImportError, AttributeError):
        raise HTTPException(
            501,
            detail={"error": {"code": "auth_unavailable", "message": "Sign-in is not available."}},
        ) from None
    params = list(inspect.signature(fn).parameters)
    if len(params) > 1:
        raise HTTPException(
            501,
            detail={
                "error": {
                    "code": "auth_unavailable",
                    "message": "current_actor needs dependencies; override slack_oauth.get_actor.",
                }
            },
        )
    result = fn(request) if params else fn()
    if inspect.isawaitable(result):
        result = await result
    user = _pick(result, "user_id", "userId", "id")
    if user is None:
        user = _pick(_pick(result, "user"), "id", "user_id")
    ws = _pick(result, "workspace_id", "workspaceId")
    if ws is None:
        ws = _pick(_pick(result, "workspace"), "id")
    if user is None or ws is None:
        raise HTTPException(
            401, detail={"error": {"code": "unauthenticated", "message": "Sign in first."}}
        )
    return Actor(str(user), str(ws))


# ---------------------------------------------------------------- routes


def oauth_enabled() -> bool:
    s = get_settings()
    return bool(s.SLACK_CLIENT_ID and s.SLACK_CLIENT_SECRET)


def authorize_base() -> str:
    api = get_settings().SLACK_API_URL.rstrip("/")
    site = api[: -len("/api")] if api.endswith("/api") else api
    return f"{site}/oauth/v2/authorize"


def redirect_uri(request: Request) -> str:
    base = get_settings().ACTRON_PUBLIC_URL or str(request.base_url)
    return base.rstrip("/") + OAUTH_CALLBACK_PATH


def _back(query: str) -> RedirectResponse:
    return RedirectResponse(f"{CONNECT}?{query}", status_code=302)


@router.get("/api/slack/install")
async def install(request: Request, actor: Actor = Depends(get_actor)) -> RedirectResponse:
    if not oauth_enabled():
        raise HTTPException(
            404,
            detail={
                "error": {
                    "code": "slack_oauth_not_configured",
                    "message": "Add to Slack is not set up. Use the token form.",
                }
            },
        )
    state = secrets.token_urlsafe(32)
    async with redis_client() as r:
        await r.set(
            STATE_PREFIX + state,
            json.dumps({"userId": actor.user_id, "workspaceId": actor.workspace_id}),
            ex=STATE_TTL_SECONDS,
        )
    query = urlencode(
        {
            "client_id": get_settings().SLACK_CLIENT_ID,
            "scope": ",".join(BOT_SCOPES),
            "user_scope": "",
            "redirect_uri": redirect_uri(request),
            "state": state,
        }
    )
    return RedirectResponse(f"{authorize_base()}?{query}", status_code=302)


async def _take_state(state: str | None) -> dict[str, Any] | None:
    if not state:
        return None
    async with redis_client() as r:
        raw = await r.getdel(STATE_PREFIX + state)
    if not raw:
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


async def exchange_code(code: str, redirect: str) -> dict[str, Any]:
    """POST oauth.v2.access with a timeout and two retries on network errors and 5xx."""
    s = get_settings()
    url = s.SLACK_API_URL.rstrip("/") + "/oauth.v2.access"
    form = {
        "client_id": s.SLACK_CLIENT_ID,
        "client_secret": s.SLACK_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect,
    }
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(3):
            try:
                resp = await client.post(url, data=form)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("slack 5xx", request=resp.request, response=resp)
                data = resp.json()
                return (
                    dict(data) if isinstance(data, dict) else {"ok": False, "error": "bad_response"}
                )
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                last = exc
                await asyncio.sleep(0.4 * 2**attempt)
    raise RuntimeError(f"oauth.v2.access failed: {last}")


@router.get("/api/slack/oauth/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    saved = await _take_state(state)  # single use: deleted even when the user cancelled
    if saved is None:
        return _back("slack_error=expired")
    if error:
        return _back("slack_error=cancelled" if error == "access_denied" else "slack_error=failed")
    if not code:
        return _back("slack_error=failed")
    ws = str(saved["workspaceId"])
    try:
        data = await exchange_code(code, redirect_uri(request))
    except RuntimeError:
        log.warning("slack oauth exchange failed", exc_info=True)
        return _back("slack_error=failed")
    token = data.get("access_token")
    team = data.get("team") or {}
    if not data.get("ok") or not token or not team.get("id"):
        log.warning("slack oauth refused: %s", data.get("error"))
        return _back("slack_error=failed")
    try:
        await ensure_team(ws, str(team["id"]))
    except TeamMismatch as exc:
        log.info("slack install refused: %s", exc)
        return _back("slack_error=different_team")
    bot_id: str | None = None
    try:  # best effort: the bot id lets Bolt ignore our own messages
        who = await web_client(str(token)).auth_test()
        bot_id = who.get("bot_id")
    except Exception:
        log.info("auth.test after install failed", exc_info=True)
    await save_installation(
        ws,
        team_id=str(team["id"]),
        team_name=team.get("name"),
        bot_token=str(token),
        bot_user_id=data.get("bot_user_id"),
        bot_id=bot_id,
        scopes=[x for x in str(data.get("scope", "")).split(",") if x],
        installed_by=(data.get("authed_user") or {}).get("id"),
        enterprise_id=(data.get("enterprise") or {}).get("id"),
        app_id=data.get("app_id"),
    )
    await set_schedule_paused(ws, False)
    return _back("slack=connected")
