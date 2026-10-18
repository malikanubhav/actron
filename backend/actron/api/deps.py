"""API dependencies (spec B, B12): errors, sessions, CSRF, rate limit, Idempotency-Key, current user."""

from __future__ import annotations

import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from actron.config import get_settings
from actron.flow.events import redis_client
from actron.flow.service import Actor

SESSION_COOKIE = "actron_session"
CSRF_COOKIE = "actron_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_S = 7 * 24 * 3600
WRITES_PER_MINUTE = 60
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(error_body(code, message, details), status_code=status)


@dataclass(frozen=True)
class Ctx:
    """The signed-in user and workspace for one request."""

    user_id: str
    ws: str
    csrf: str
    name: str = ""
    role: str = "member"
    slack_user_id: str | None = None
    idempotency_key: str | None = None

    def actor(self) -> Actor:
        return Actor(user_id=self.user_id, slack_user_id=self.slack_user_id, surface="ui", name=self.name)


# Sessions (Redis, 7 days)
async def create_session(user_id: str, ws: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    await redis_client().set(f"session:{token}", json.dumps({"userId": user_id, "ws": ws, "csrf": csrf,
                                                             "createdAt": int(time.time())}), ex=SESSION_TTL_S)
    return token, csrf


async def load_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    raw = await redis_client().get(f"session:{token}")
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def delete_session(token: str | None) -> None:
    if token:
        await redis_client().delete(f"session:{token}")


def set_session_cookies(response: Any, token: str, csrf: str) -> None:
    secure = get_settings().ACTRON_ENV == "prod"
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_S, httponly=True, samesite="lax", secure=secure,
                        path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_TTL_S, httponly=False, samesite="lax", secure=secure,
                        path="/")


def clear_session_cookies(response: Any) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _user_info(user_id: str, ws: str) -> tuple[str, str | None, str] | None:
    from actron.db import models as m
    from actron.db.session import session_scope

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    with session_scope() as s:
        user = s.get(m.User, uid)
        membership = s.get(m.Membership, (uid, ws))
        if user is None or membership is None:
            return None
        return user.name, user.slack_user_id, membership.role


async def current(request: Request) -> Ctx:
    """Any signed-in route. 401 without a valid session."""
    import asyncio

    data = await load_session(request.cookies.get(SESSION_COOKIE))
    if data is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    info = await asyncio.to_thread(_user_info, str(data["userId"]), str(data["ws"]))
    if info is None:
        raise ApiError(401, "unauthenticated", "Your session is no longer valid. Sign in again.")
    name, slack_id, role = info
    key = request.headers.get("Idempotency-Key")
    if key is not None and not (1 <= len(key) <= 200):
        raise ApiError(422, "invalid_idempotency_key", "Idempotency-Key must be 1 to 200 characters.")
    return Ctx(user_id=str(data["userId"]), ws=str(data["ws"]), csrf=str(data["csrf"]), name=name, role=role,
               slack_user_id=slack_id, idempotency_key=key)


async def writer(request: Request) -> Ctx:
    """State-changing routes: session + CSRF double submit + 60 writes per minute per user."""
    ctx = await current(request)
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not secrets.compare_digest(header, cookie) or \
            not secrets.compare_digest(header, ctx.csrf):
        raise ApiError(403, "csrf", "The request is missing a valid CSRF token. Reload the page and try again.")
    minute = int(time.time() // 60)
    key = f"rl:{ctx.user_id}:{minute}"
    client = redis_client()
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 70)
    if count > WRITES_PER_MINUTE:
        raise ApiError(429, "rate_limited", "Too many changes in a minute. Wait a moment and try again.")
    return ctx


async def current_actor(request: Request) -> dict[str, Any]:
    """For W9's Slack OAuth routes: the signed-in user and workspace (401 otherwise)."""
    ctx = await current(request)
    return {"user_id": ctx.user_id, "workspace_id": ctx.ws, "role": ctx.role}


async def once(ctx: Ctx, scope: str, fn: Any) -> dict[str, Any]:
    """Run a non-service write once per Idempotency-Key (the stored body is returned on a repeat)."""
    from actron.flow.service import idempotent

    key = f"{ctx.user_id}:{scope}:{ctx.idempotency_key}" if ctx.idempotency_key else None
    return await idempotent(ctx.ws, key, fn)


async def owner(request: Request) -> Ctx:
    ctx = await writer(request)
    if ctx.role != "owner":
        raise ApiError(403, "not_owner", "Only the workspace owner can change this.")
    return ctx
