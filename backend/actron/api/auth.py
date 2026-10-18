"""Sign in (spec B, B12, B12a): Slack OpenID Connect, dev login (not registered in prod), logout, `GET /api/me`.

Slack OIDC endpoints and claim names are taken from the spec and are marked unverified in BUILD-LOG.md
(the docs could not be fetched during the build):
authorize `https://slack.com/openid/connect/authorize`, token `https://slack.com/api/openid.connect.token`,
keys `https://slack.com/openid/connect/keys`, issuer `https://slack.com`, claims `https://slack.com/team_id`,
`https://slack.com/team_name`, `https://slack.com/user_id`, `email`, `name`, `picture`.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from actron.api.deps import (
    SESSION_COOKIE,
    ApiError,
    Ctx,
    clear_session_cookies,
    create_session,
    current,
    delete_session,
    set_session_cookies,
)
from actron.config import get_settings
from actron.db import models as m
from actron.db.session import session_scope
from actron.flow.events import redis_client
from actron.graph import ids
from actron.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["auth"])
dev_router = APIRouter(tags=["auth"])

AUTHORIZE_URL = "https://slack.com/openid/connect/authorize"
TOKEN_URL = "https://slack.com/api/openid.connect.token"
JWKS_URL = "https://slack.com/openid/connect/keys"
ISSUER = "https://slack.com"
TEAM_ID_CLAIM = "https://slack.com/team_id"
TEAM_NAME_CLAIM = "https://slack.com/team_name"
USER_ID_CLAIM = "https://slack.com/user_id"
STATE_TTL_S = 600
DEV_WORKSPACE = "dev"


class PersonRefOut(BaseModel):
    personId: str | None
    userId: str | None
    name: str
    avatarUrl: str | None


class WorkspaceOut(BaseModel):
    id: str
    name: str


class DevLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DevLoginOut(BaseModel):
    user: PersonRefOut
    workspace: WorkspaceOut


class MeUser(PersonRefOut):
    email: str | None
    slackUserId: str | None


class MeWorkspace(WorkspaceOut):
    role: str


class MeOut(BaseModel):
    user: MeUser
    workspace: MeWorkspace
    csrfToken: str
    env: str
    devFixtures: bool


def _redirect_uri() -> str:
    base = (get_settings().ACTRON_PUBLIC_URL or "http://localhost:3000").rstrip("/")
    return f"{base}/api/auth/slack/callback"


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/app"


@router.get("/api/auth/slack/start", status_code=302, responses={404: {"description": "Slack sign-in not configured"}})
async def slack_start(next: str | None = None) -> Response:
    s = get_settings()
    if not (s.SLACK_CLIENT_ID and s.SLACK_CLIENT_SECRET):
        raise ApiError(404, "not_configured", "Sign in with Slack is not configured.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    await redis_client().set(f"oidc:{state}", json.dumps({"next": _safe_next(next), "nonce": nonce}), ex=STATE_TTL_S)
    query = urlencode({"response_type": "code", "scope": "openid profile email", "client_id": s.SLACK_CLIENT_ID,
                       "state": state, "nonce": nonce, "redirect_uri": _redirect_uri()})
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)


async def exchange_code(code: str) -> dict[str, Any]:
    """POST the code to Slack's token endpoint. Returns the JSON body (`ok`, `id_token`, ...)."""
    s = get_settings()
    last: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(TOKEN_URL, data={"client_id": s.SLACK_CLIENT_ID,
                                                       "client_secret": s.SLACK_CLIENT_SECRET, "code": code,
                                                       "redirect_uri": _redirect_uri()})
                body: dict[str, Any] = r.json()
                return body
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(0.5 * 2**attempt)
    raise RuntimeError(f"slack token exchange failed: {type(last).__name__}")


def verify_id_token(id_token: str, nonce: str | None) -> dict[str, Any]:
    """Check the ID token's signature (Slack JWKS), audience, issuer and nonce."""
    import jwt

    s = get_settings()
    key = jwt.PyJWKClient(JWKS_URL, timeout=10).get_signing_key_from_jwt(id_token)
    claims: dict[str, Any] = jwt.decode(id_token, key.key, algorithms=["RS256"], audience=s.SLACK_CLIENT_ID,
                                        issuer=ISSUER)
    if nonce and claims.get("nonce") not in (None, nonce):
        raise ValueError("nonce mismatch")
    return claims


def _unique_slug(s: Any, name: str) -> str:
    base = ids.slugify(name) or "team"
    slug, i = base, 2
    while s.get(m.Workspace, slug) is not None:
        slug = f"{base}-{i}"
        i += 1
    return slug


def sign_in_slack_user(claims: dict[str, Any]) -> tuple[str, str]:
    """B12a: find or create the workspace for the Slack team (first user owner, later users member)."""
    team_id = str(claims.get(TEAM_ID_CLAIM) or "")
    team_name = str(claims.get(TEAM_NAME_CLAIM) or team_id or "Team")
    slack_user = str(claims.get(USER_ID_CLAIM) or claims.get("sub") or "")
    if not team_id or not slack_user:
        raise ValueError("ID token has no team or user")
    prefix = get_settings().FALKORDB_GRAPH_PREFIX
    with session_scope() as s:
        ws = s.scalar(select(m.Workspace).where(m.Workspace.slack_team_id == team_id))
        created = False
        if ws is None:
            slug = _unique_slug(s, team_name)
            ws = m.Workspace(id=slug, name=team_name, slack_team_id=team_id, graph_name=ids.graph_name(prefix, slug),
                             settings={})
            s.add(ws)
            s.flush()
            created = True
        user = s.scalar(select(m.User).where(m.User.slack_user_id == slack_user))
        if user is None:
            user = m.User(slack_user_id=slack_user)
            s.add(user)
        user.name = str(claims.get("name") or user.name or slack_user)
        user.email = claims.get("email") or user.email
        user.avatar_url = claims.get("picture") or user.avatar_url
        s.flush()
        if s.get(m.Membership, (user.id, ws.id)) is None:
            s.add(m.Membership(user_id=user.id, workspace_id=ws.id, role="owner" if created else "member"))
        return str(user.id), ws.id


@router.get("/api/auth/slack/callback", status_code=302)
async def slack_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    fail = RedirectResponse("/app/signin?error=slack", status_code=302)
    if error or not code or not state:
        return fail
    client = redis_client()
    raw = await client.get(f"oidc:{state}")
    await client.delete(f"oidc:{state}")
    if not raw:
        return fail
    stored = json.loads(raw)
    try:
        body = await exchange_code(code)
        if not body.get("ok") or not body.get("id_token"):
            return fail
        claims = await asyncio.to_thread(verify_id_token, str(body["id_token"]), stored.get("nonce"))
        user_id, ws = await asyncio.to_thread(sign_in_slack_user, claims)
    except Exception as exc:
        log.warning("slack sign-in failed", extra={"error": type(exc).__name__})
        return fail
    token, csrf = await create_session(user_id, ws)
    response = RedirectResponse(_safe_next(stored.get("next")), status_code=302)
    set_session_cookies(response, token, csrf)
    return response


def dev_sign_in(name: str) -> tuple[str, str, str]:
    """Create or join the development workspace (`dev`, or ACTRON_DEV_WORKSPACE, which the e2e stack sets so its
    graph and Redis channels never meet the development data); the first user becomes its owner."""
    settings = get_settings()
    prefix, ws_id = settings.FALKORDB_GRAPH_PREFIX, settings.ACTRON_DEV_WORKSPACE
    with session_scope() as s:
        ws = s.get(m.Workspace, ws_id)
        created = False
        if ws is None:
            ws = m.Workspace(id=ws_id, name="Development", graph_name=ids.graph_name(prefix, ws_id), settings={})
            s.add(ws)
            s.flush()
            created = True
        user = s.scalar(
            select(m.User).join(m.Membership, m.Membership.user_id == m.User.id)
            .where(m.Membership.workspace_id == ws_id, m.User.name == name, m.User.slack_user_id.is_(None))
            .limit(1))
        if user is None:
            user = m.User(name=name)
            s.add(user)
            s.flush()
            has_owner = s.scalar(select(m.Membership).where(m.Membership.workspace_id == ws_id,
                                                            m.Membership.role == "owner").limit(1))
            s.add(m.Membership(user_id=user.id, workspace_id=ws_id,
                               role="owner" if created or has_owner is None else "member"))
        return str(user.id), ws_id, ws.name


@dev_router.post("/api/auth/dev-login", response_model=DevLoginOut)
async def dev_login(body: DevLoginIn) -> Response:
    if get_settings().ACTRON_ENV == "prod":
        raise ApiError(404, "not_found", "Not found.")
    user_id, ws, ws_name = await asyncio.to_thread(dev_sign_in, body.name.strip())
    token, csrf = await create_session(user_id, ws)
    out = DevLoginOut(user=PersonRefOut(personId=None, userId=user_id, name=body.name.strip(), avatarUrl=None),
                      workspace=WorkspaceOut(id=ws, name=ws_name))
    response = JSONResponse(out.model_dump())
    set_session_cookies(response, token, csrf)
    return response


@router.post("/api/auth/logout", status_code=204)
async def logout(request: Request) -> Response:
    await delete_session(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


def _me(ctx: Ctx) -> MeOut:
    with session_scope() as s:
        import uuid

        user = s.get(m.User, uuid.UUID(ctx.user_id))
        ws = s.get(m.Workspace, ctx.ws)
        assert user is not None and ws is not None
        settings = get_settings()
        return MeOut(
            user=MeUser(personId=None, userId=str(user.id), name=user.name, avatarUrl=user.avatar_url, email=user.email,
                        slackUserId=user.slack_user_id),
            workspace=MeWorkspace(id=ws.id, name=ws.name, role=ctx.role),
            csrfToken=ctx.csrf,
            env="prod" if settings.ACTRON_ENV == "prod" else "dev",
            devFixtures=settings.NEXT_PUBLIC_ACTRON_DEV_FIXTURES == "1",
        )


@router.get("/api/me", response_model=MeOut)
async def me(ctx: Ctx = Depends(current)) -> MeOut:
    return await asyncio.to_thread(_me, ctx)
