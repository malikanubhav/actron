"""Minimal fake Slack Web API for the W9 tests (until W3's tests/fakes/slack.py is used).

Records every call. Serves auth.test (with x-oauth-scopes), chat.postMessage, chat.update,
chat.postEphemeral, conversations.open, views.open, users.info and oauth.v2.access.
Test data only; nothing here is shipped.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web


@dataclass
class Call:
    method: str
    params: dict[str, Any]
    token: str | None


@dataclass
class FakeSlack:
    team_id: str = "T123"
    team_name: str = "Acme"
    bot_user_id: str = "UBOT"
    scopes: str = "chat:write,commands"
    oauth_token: str = "xoxb-oauth-token-1234"
    oauth_error: str | None = None
    post_delay: float = 0.0
    fail_update_with: str | None = None
    fail_post_with: str | None = None
    calls: list[Call] = field(default_factory=list)
    _ts: int = 0
    runner: web.AppRunner | None = None
    port: int = 0
    users: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/"

    def of(self, method: str) -> list[Call]:
        return [c for c in self.calls if c.method == method]

    def next_ts(self) -> str:
        self._ts += 1
        return f"1700000{self._ts:03d}.000100"

    async def _parse(self, request: web.Request) -> dict[str, Any]:
        if request.content_type == "application/json":
            return dict(await request.json())
        form = await request.post()
        out: dict[str, Any] = {}
        for k, v in form.items():
            s = str(v)
            if k in ("blocks", "attachments", "view") and s[:1] in "[{":
                out[k] = json.loads(s)
            else:
                out[k] = s
        return out

    async def handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        params = {**request.query, **await self._parse(request)}
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ") or params.get("token")
        self.calls.append(Call(method, params, token))
        headers: dict[str, str] = {}
        body: dict[str, Any] = {"ok": True}
        if method == "chat.postMessage":
            if self.post_delay:
                await asyncio.sleep(self.post_delay)
            if self.fail_post_with:
                return web.json_response({"ok": False, "error": self.fail_post_with})
            body.update(ts=self.next_ts(), channel=params.get("channel"))
        elif method == "chat.update":
            if self.fail_update_with:
                return web.json_response({"ok": False, "error": self.fail_update_with})
            body.update(ts=params.get("ts"), channel=params.get("channel"))
        elif method == "chat.postEphemeral":
            body.update(message_ts=self.next_ts())
        elif method == "conversations.open":
            body.update(channel={"id": "D" + str(params.get("users"))})
        elif method == "views.open":
            body.update(view={"id": "V1"})
        elif method == "users.info":
            u = self.users.get(
                str(params.get("user")), {"real_name": "Priya", "profile": {"email": "p@acme.test"}}
            )
            body.update(
                user={
                    "id": params.get("user"),
                    "real_name": u.get("real_name"),
                    "profile": u.get("profile", {}),
                }
            )
        elif method == "auth.test":
            headers["x-oauth-scopes"] = self.scopes
            body.update(
                team_id=self.team_id, team=self.team_name, user_id=self.bot_user_id, bot_id="B1"
            )
        elif method == "oauth.v2.access":
            if self.oauth_error:
                return web.json_response({"ok": False, "error": self.oauth_error})
            body.update(
                access_token=self.oauth_token,
                token_type="bot",
                scope=self.scopes,
                bot_user_id=self.bot_user_id,
                app_id="A1",
                team={"id": self.team_id, "name": self.team_name},
                enterprise=None,
                authed_user={"id": "UINSTALLER"},
                is_enterprise_install=False,
            )
        return web.json_response(body, headers=headers)

    async def handle_response(self, request: web.Request) -> web.Response:
        """A command's response_url (what Bolt's respond() posts to)."""
        self.calls.append(Call("response_url", await self._parse(request), None))
        return web.json_response({"ok": True})

    @property
    def response_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/response/1"

    async def start(self) -> FakeSlack:
        app = web.Application()
        app.router.add_post("/response/{n}", self.handle_response)
        app.router.add_post("/api/{method}", self.handle)
        app.router.add_get("/api/{method}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        return self

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
