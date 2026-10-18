"""Slack Web API client (spec A, A9): bot token, cursor paging, rate limits and typed errors.

It speaks the Web API over httpx so tests can point it at an in-process fake server and so the
`x-oauth-scopes` response header (used by the setup checks) is always visible. The Slack bot
(spec B, W9) uses slack_bolt for events and commands; this client is for ingestion and checks.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from actron.config import get_settings
from actron.connectors.common import (
    DEFAULT_TIMEOUT,
    AuthError,
    ProviderError,
    RetryableProviderError,
    TransientError,
    parse_retry_after,
    transport_for,
    with_backoff,
)

AUTH_ERRORS = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "no_permission",
        "org_login_required",
        "invalid_token",
        "missing_scope",
        "not_allowed_token_type",
    }
)
TRANSIENT_ERRORS = frozenset(
    {"fatal_error", "internal_error", "service_unavailable", "request_timeout"}
)


class SlackApiError(ProviderError):
    """Slack answered `ok: false` with an error code other than rate limit or auth."""


class SlackClient:
    def __init__(
        self,
        token: str | None,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        base = (base_url or get_settings().SLACK_API_URL).rstrip("/") + "/"
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(timeout),
            transport=transport or transport_for("slack"),
            headers={"User-Agent": "actron"},
        )
        self.scopes: list[str] = []
        self.last_headers: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SlackClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        token: str | None = None,
        as_json: bool = False,
    ) -> dict[str, Any]:
        """POST one Web API method and return the decoded body when `ok` is true."""
        use_token = token or self.token
        headers = {"Authorization": f"Bearer {use_token}"} if use_token else {}
        data = {k: v for k, v in (params or {}).items() if v is not None}

        async def attempt() -> httpx.Response:
            if as_json:
                response = await self._client.post(method, json=data, headers=headers)
            else:
                form = {
                    k: (json.dumps(v) if isinstance(v, list | dict) else v) for k, v in data.items()
                }
                response = await self._client.post(method, data=form, headers=headers)
            if response.status_code >= 500:
                raise TransientError(f"Slack answered {response.status_code}")
            return response

        response = await with_backoff(attempt)
        self.last_headers = {k.lower(): v for k, v in response.headers.items()}
        scopes = self.last_headers.get("x-oauth-scopes")
        if scopes is not None and token is None:  # a call made with another token (the app token) says nothing about the bot's
            self.scopes = [s.strip() for s in scopes.split(",") if s.strip()]
        if response.status_code == 429:
            delay = parse_retry_after(response.headers.get("retry-after")) or 30.0
            raise RetryableProviderError(
                f"Slack asked us to slow down for {delay:.0f} s",
                retry_after=delay,
                status=429,
                code="ratelimited",
                url=method,
            )
        body: dict[str, Any] = response.json()
        if body.get("ok"):
            return body
        error = str(body.get("error") or "unknown_error")
        if error == "ratelimited":
            delay = parse_retry_after(response.headers.get("retry-after")) or 30.0
            raise RetryableProviderError(
                f"Slack asked us to slow down for {delay:.0f} s",
                retry_after=delay,
                status=response.status_code,
                code=error,
                url=method,
            )
        if error in TRANSIENT_ERRORS:
            raise RetryableProviderError(
                f"Slack had a temporary problem ({error})", retry_after=None, code=error, url=method
            )
        if error in AUTH_ERRORS:
            needed = body.get("needed")
            detail = f" (needed: {needed})" if needed else ""
            raise AuthError(f"Slack refused the token: {error}{detail}", code=error, url=method)
        raise SlackApiError(f"Slack {method} failed: {error}", code=error, url=method)

    async def paginate(
        self, method: str, key: str, params: Mapping[str, Any] | None = None, *, limit: int = 200
    ) -> AsyncIterator[list[dict[str, Any]]]:
        cursor: str | None = None
        while True:
            body = await self.call(method, {**(params or {}), "limit": limit, "cursor": cursor})
            yield list(body.get(key) or [])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                return

    # Calls used by the connector, the forms and the checks
    async def auth_test(self) -> dict[str, Any]:
        return await self.call("auth.test")

    async def team_info(self) -> dict[str, Any]:
        return await self.call("team.info")

    async def users_list(self, cursor: str | None = None, limit: int = 200) -> dict[str, Any]:
        return await self.call("users.list", {"limit": limit, "cursor": cursor})

    async def conversations_list(
        self, cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        return await self.call(
            "conversations.list",
            {
                "types": "public_channel,private_channel",
                "exclude_archived": "false",
                "limit": limit,
                "cursor": cursor,
            },
        )

    async def conversations_members(
        self, channel: str, cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        return await self.call(
            "conversations.members", {"channel": channel, "limit": limit, "cursor": cursor}
        )

    async def conversations_history(
        self, channel: str, *, oldest: str | None, cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        return await self.call(
            "conversations.history",
            {
                "channel": channel,
                "oldest": oldest,
                "limit": limit,
                "inclusive": "false",
                "cursor": cursor,
            },
        )

    async def conversations_replies(
        self, channel: str, ts: str, cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        return await self.call(
            "conversations.replies",
            {"channel": channel, "ts": ts, "limit": limit, "cursor": cursor},
        )

    async def get_permalink(self, channel: str, ts: str) -> str:
        body = await self.call("chat.getPermalink", {"channel": channel, "message_ts": ts})
        return str(body["permalink"])

    async def open_socket_mode(self, app_token: str) -> dict[str, Any]:
        """Open a Socket Mode connection URL. The app-level token needs `connections:write`."""
        return await self.call("apps.connections.open", token=app_token)
