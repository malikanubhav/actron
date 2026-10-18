"""A general fake Slack Web API server (ASGI), shared by the connector tests and the bot tests (W9).

Everything is synthetic, in memory, and recorded:
- `calls` lists every method call with its parameters (chat.postMessage, chat.update, conversations.open ...).
- `auth.test` answers with the token's scopes in the `x-oauth-scopes` header.
- `oauth.v2.access` exchanges a code registered with `add_oauth_code`.
- `ratelimit(method, retry_after)` and `fail(method, error)` inject errors.

In process:  `httpx.AsyncClient(transport=fake.transport(), base_url="http://fake.slack/api/")`.
Over a port: `with fake.serve() as url:` (uvicorn in a thread; for slack_sdk clients).
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

BASE = "http://fake.slack/api/"


@dataclass
class Injected:
    method: str
    kind: str  # "ratelimit" | "error"
    value: Any
    times: int = 1


@dataclass
class FakeToken:
    team_id: str
    user_id: str
    bot_id: str
    scopes: list[str]
    kind: str = "bot"


class FakeSlack:
    def __init__(self, *, team_id: str = "T0001", team_name: str = "Northwind Labs", domain: str = "northwind",
                 bot_user: str = "UBOT", scopes: list[str] | None = None) -> None:
        self.team = {"id": team_id, "name": team_name, "domain": domain}
        self.bot_user = bot_user
        self.users: dict[str, dict[str, Any]] = {}
        self.channels: dict[str, dict[str, Any]] = {}
        self.members: dict[str, list[str]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.injected: list[Injected] = []
        self.tokens: dict[str, FakeToken] = {}
        self.app_tokens: dict[str, bool] = {}
        self.oauth_codes: dict[str, dict[str, Any]] = {}
        self.dm_channels: dict[str, str] = {}
        self._clock = 1_760_000_000.0
        self._counter = 0
        all_scopes = scopes if scopes is not None else [
            "app_mentions:read", "channels:history", "channels:read", "chat:write", "commands",
            "groups:history", "groups:read", "im:write", "reactions:read", "team:read", "users:read",
            "users:read.email"]
        self.add_token("xoxb-test-token", all_scopes)
        self.add_user(bot_user, "actron", "Actron", is_bot=True)
        self.app = Starlette(routes=[Route("/api/{method}", self._handle, methods=["POST", "GET"])])

    # Setup
    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self.app)

    def serve(self, port: int = 0) -> contextlib.AbstractContextManager[str]:
        """Run on a real port for the duration of a `with` block; yields the Web API base URL."""
        return serve(self, port)

    def add_token(self, token: str, scopes: list[str], *, kind: str = "bot") -> None:
        self.tokens[token] = FakeToken(self.team["id"], self.bot_user, "BBOT", scopes, kind)

    def add_app_token(self, token: str, *, valid: bool = True) -> None:
        self.app_tokens[token] = valid

    def add_oauth_code(self, code: str, *, token: str = "xoxb-oauth-token", scopes: list[str] | None = None) -> None:
        sc = scopes if scopes is not None else self.tokens["xoxb-test-token"].scopes
        self.add_token(token, sc)
        self.oauth_codes[code] = {
            "ok": True, "access_token": token, "token_type": "bot", "scope": ",".join(sc),
            "bot_user_id": self.bot_user, "app_id": "A0001",
            "team": {"id": self.team["id"], "name": self.team["name"]},
            "authed_user": {"id": "UINSTALLER"},
        }

    def add_user(self, uid: str, name: str, real_name: str = "", *, email: str | None = None,
                 is_bot: bool = False, deleted: bool = False, title: str = "") -> None:
        profile: dict[str, Any] = {"display_name": name, "real_name": real_name or name, "title": title,
                                   "image_72": f"https://avatars.example/{uid}"}
        if email:
            profile["email"] = email
        self.users[uid] = {"id": uid, "team_id": self.team["id"], "name": name, "real_name": real_name or name,
                           "deleted": deleted, "is_bot": is_bot, "profile": profile}

    def add_channel(self, cid: str, name: str, *, is_private: bool = False, is_member: bool = True,
                    members: list[str] | None = None, archived: bool = False, topic: str = "",
                    purpose: str = "") -> None:
        self.channels[cid] = {
            "id": cid, "name": name, "is_channel": not is_private, "is_private": is_private,
            "is_archived": archived, "is_member": is_member, "topic": {"value": topic},
            "purpose": {"value": purpose}, "num_members": len(members or []), "created": 1_700_000_000,
        }
        self.members[cid] = list(members or [])
        self.messages.setdefault(cid, [])

    def next_ts(self) -> str:
        self._clock += 1.0
        self._counter += 1
        return f"{int(self._clock)}.{self._counter:06d}"

    def add_message(self, channel: str, text: str, *, user: str | None = "U1", ts: str | None = None,
                    thread_ts: str | None = None, reactions: list[dict[str, Any]] | None = None,
                    files: list[dict[str, Any]] | None = None, subtype: str | None = None,
                    bot_id: str | None = None, edited_ts: str | None = None) -> str:
        ts = ts or self.next_ts()
        msg: dict[str, Any] = {"type": "message", "ts": ts, "text": text, "team": self.team["id"]}
        if user:
            msg["user"] = user
        if thread_ts:
            msg["thread_ts"] = thread_ts
        if reactions:
            msg["reactions"] = reactions
        if files:
            msg["files"] = files
        if subtype:
            msg["subtype"] = subtype
        if bot_id:
            msg["bot_id"] = bot_id
        if edited_ts:
            msg["edited"] = {"user": user, "ts": edited_ts}
        self.messages.setdefault(channel, []).append(msg)
        if thread_ts and thread_ts != ts:
            parent = self.find(channel, thread_ts)
            if parent is not None:
                parent["reply_count"] = int(parent.get("reply_count", 0)) + 1
                parent["latest_reply"] = ts
                parent["thread_ts"] = thread_ts
        return ts

    def find(self, channel: str, ts: str) -> dict[str, Any] | None:
        for m in self.messages.get(channel, []):
            if m["ts"] == ts:
                return m
        return None

    def edit_message(self, channel: str, ts: str, text: str) -> str:
        m = self.find(channel, ts)
        assert m is not None
        edited = self.next_ts()
        m["text"] = text
        m["edited"] = {"user": m.get("user"), "ts": edited}
        return edited

    def delete_message(self, channel: str, ts: str) -> None:
        self.messages[channel] = [m for m in self.messages[channel] if m["ts"] != ts]

    def ratelimit(self, method: str, retry_after: int, times: int = 1) -> None:
        self.injected.append(Injected(method, "ratelimit", retry_after, times))

    def fail(self, method: str, error: str, times: int = 1, **extra: Any) -> None:
        self.injected.append(Injected(method, "error", (error, extra), times))

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [p for m, p in self.calls if m == method]

    # Serving
    async def _params(self, request: Request) -> dict[str, Any]:
        raw = await request.body()
        ctype = request.headers.get("content-type", "")
        if "json" in ctype:
            data = json.loads(raw or b"{}")
            return dict(data)
        return {k: v[0] for k, v in parse_qs(raw.decode()).items()}

    async def _handle(self, request: Request) -> Response:
        method = request.path_params["method"]
        params = await self._params(request)
        self.calls.append((method, params))
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        for inj in list(self.injected):
            if inj.method == method:
                inj.times -= 1
                if inj.times <= 0:
                    self.injected.remove(inj)
                if inj.kind == "ratelimit":
                    return JSONResponse({"ok": False, "error": "ratelimited"}, status_code=429,
                                        headers={"Retry-After": str(inj.value)})
                error, extra = inj.value
                return JSONResponse({"ok": False, "error": error, **extra})
        if method == "oauth.v2.access":
            code = params.get("code", "")
            if code in self.oauth_codes:
                return JSONResponse(self.oauth_codes.pop(code))
            return JSONResponse({"ok": False, "error": "invalid_code"})
        if method == "apps.connections.open":
            if self.app_tokens.get(token):
                # Real Slack puts the app token's own scopes in the header of this answer.
                return JSONResponse({"ok": True, "url": "wss://fake.slack/link/?ticket=t"},
                                    headers={"x-oauth-scopes": "connections:write"})
            return JSONResponse({"ok": False, "error": "not_allowed_token_type" if token else "not_authed"})
        info = self.tokens.get(token)
        if info is None:
            return JSONResponse({"ok": False, "error": "invalid_auth" if token else "not_authed"})
        handler = getattr(self, "_m_" + method.replace(".", "_"), None)
        if handler is None:
            return JSONResponse({"ok": False, "error": "unknown_method"})
        needed = _SCOPES.get(method)
        if needed and needed not in info.scopes:
            return JSONResponse({"ok": False, "error": "missing_scope", "needed": needed,
                                 "provided": ",".join(info.scopes)}, headers=_scope_header(info))
        body = handler(params, info)
        return JSONResponse(body, headers=_scope_header(info))

    # Methods
    def _m_auth_test(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        return {"ok": True, "url": f"https://{self.team['domain']}.slack.com/", "team": self.team["name"],
                "team_id": self.team["id"], "user": "actron", "user_id": t.user_id, "bot_id": t.bot_id}

    def _m_team_info(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        return {"ok": True, "team": dict(self.team)}

    @staticmethod
    def _slice(items: list[Any], p: dict[str, Any]) -> tuple[list[Any], str]:
        limit = int(p.get("limit", 100))
        start = int(p["cursor"]) if p.get("cursor") else 0
        chunk = items[start : start + limit]
        nxt = str(start + limit) if start + limit < len(items) else ""
        return chunk, nxt

    def _m_users_list(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        chunk, nxt = self._slice(list(self.users.values()), p)
        return {"ok": True, "members": chunk, "response_metadata": {"next_cursor": nxt}}

    def _m_conversations_list(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        items = list(self.channels.values())
        if str(p.get("exclude_archived", "false")).lower() == "true":
            items = [c for c in items if not c["is_archived"]]
        chunk, nxt = self._slice(items, p)
        return {"ok": True, "channels": chunk, "response_metadata": {"next_cursor": nxt}}

    def _m_conversations_members(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        cid = p.get("channel", "")
        if cid not in self.channels:
            return {"ok": False, "error": "channel_not_found"}
        chunk, nxt = self._slice(self.members.get(cid, []), p)
        return {"ok": True, "members": chunk, "response_metadata": {"next_cursor": nxt}}

    def _readable(self, p: dict[str, Any]) -> dict[str, Any] | None:
        ch = self.channels.get(p.get("channel", ""))
        if ch is None:
            return {"ok": False, "error": "channel_not_found"}
        if not ch["is_member"]:
            return {"ok": False, "error": "not_in_channel"}
        return None

    def _m_conversations_history(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        err = self._readable(p)
        if err:
            return err
        cid = p["channel"]
        oldest = float(p["oldest"]) if p.get("oldest") else 0.0
        inclusive = str(p.get("inclusive", "false")).lower() == "true"
        msgs = [m for m in self.messages[cid]
                if not (m.get("thread_ts") and m["thread_ts"] != m["ts"])
                and (float(m["ts"]) > oldest or (inclusive and float(m["ts"]) == oldest))]
        msgs.sort(key=lambda m: float(m["ts"]), reverse=True)
        chunk, nxt = self._slice(msgs, p)
        return {"ok": True, "messages": chunk, "has_more": bool(nxt), "response_metadata": {"next_cursor": nxt}}

    def _m_conversations_replies(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        err = self._readable(p)
        if err:
            return err
        cid, ts = p["channel"], p["ts"]
        thread = [m for m in self.messages[cid] if m["ts"] == ts or m.get("thread_ts") == ts]
        thread.sort(key=lambda m: float(m["ts"]))
        chunk, nxt = self._slice(thread, p)
        return {"ok": True, "messages": chunk, "has_more": bool(nxt), "response_metadata": {"next_cursor": nxt}}

    def _m_chat_getPermalink(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        ts = p["message_ts"].replace(".", "")
        return {"ok": True, "permalink": f"https://{self.team['domain']}.slack.com/archives/{p['channel']}/p{ts}"}

    def _m_chat_postMessage(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        cid = p.get("channel", "")
        if cid not in self.channels and cid not in self.dm_channels.values():
            return {"ok": False, "error": "channel_not_found"}
        ch = self.channels.get(cid)
        if ch is not None and not ch["is_member"]:
            return {"ok": False, "error": "not_in_channel"}
        ts = self.add_message(cid, p.get("text", ""), user=t.user_id, thread_ts=p.get("thread_ts"),
                              bot_id=t.bot_id, subtype=None)
        msg = self.find(cid, ts)
        assert msg is not None
        if p.get("blocks"):
            msg["blocks"] = p["blocks"] if not isinstance(p["blocks"], str) else json.loads(p["blocks"])
        return {"ok": True, "channel": cid, "ts": ts, "message": dict(msg)}

    def _m_chat_update(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        cid, ts = p.get("channel", ""), p.get("ts", "")
        msg = self.find(cid, ts)
        if msg is None:
            return {"ok": False, "error": "message_not_found"}
        if "text" in p:
            msg["text"] = p["text"]
        if p.get("blocks"):
            msg["blocks"] = p["blocks"] if not isinstance(p["blocks"], str) else json.loads(p["blocks"])
        msg["edited"] = {"user": t.user_id, "ts": self.next_ts()}
        return {"ok": True, "channel": cid, "ts": ts, "text": msg["text"]}

    def _m_conversations_open(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        users = str(p.get("users", ""))
        cid = self.dm_channels.setdefault(users, f"D{len(self.dm_channels) + 1:04d}")
        self.messages.setdefault(cid, [])
        return {"ok": True, "channel": {"id": cid}}

    def _m_users_info(self, p: dict[str, Any], t: FakeToken) -> dict[str, Any]:
        user = self.users.get(p.get("user", ""))
        return {"ok": True, "user": user} if user else {"ok": False, "error": "user_not_found"}


_SCOPES = {
    "users.list": "users:read", "team.info": "team:read", "chat.postMessage": "chat:write",
    "chat.update": "chat:write", "conversations.open": "im:write",
}


def _scope_header(t: FakeToken) -> dict[str, str]:
    return {"x-oauth-scopes": ",".join(t.scopes), "x-accepted-oauth-scopes": ""}


@contextlib.contextmanager
def serve(fake: FakeSlack, port: int = 0) -> Iterator[str]:
    """Run the fake on a real port (uvicorn in a thread). Yields the Web API base URL."""
    import socket

    import uvicorn

    if port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    config = uvicorn.Config(fake.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/api/"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def channel_with_history(fake: FakeSlack, cid: str = "C1", name: str = "eng", n: int = 5) -> list[str]:
    """Helper for tests: a channel with `n` plain messages; returns their ts values."""
    fake.add_channel(cid, name, members=["U1", "U2"])
    return [fake.add_message(cid, f"message {i}", user="U1") for i in range(n)]
