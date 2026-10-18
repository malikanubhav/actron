"""Shared fixtures for the W9 Slack tests: fake Slack server, seeded workspace, fake flow service."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from actron.config import get_settings
from actron.db.crypto import encrypt_secret
from actron.db.models import Connection, Request, User, Workspace
from actron.db.session import reset_engines
from actron.integrations import slack_common
from tests.integration.slack.fake_slack import FakeSlack
from tests.unit.slack.views import make_view

SIGNING_SECRET = "test-signing-secret"


@dataclass
class FakeFlow:
    """Stands in for actron.flow.service."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    views: dict[str, dict[str, Any]] = field(default_factory=dict)
    result: dict[str, Any] = field(
        default_factory=lambda: {"status": "accepted", "reason": None, "state": "Building"}
    )
    on_create: Any = None

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def of(self, name: str) -> list[dict[str, Any]]:
        return [c[1] for c in self.calls if c[0] == name]

    async def create_request(self, ws: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("create_request", {"ws": ws, **kw}))
        assert self.on_create is not None
        return dict(await self.on_create(ws, kw))

    async def get_request_view(self, ws: str, request_id: str) -> dict[str, Any]:
        return dict(self.views[request_id])

    def _record(self, name: str, ws: str, request_id: str, kw: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, {"ws": ws, "request_id": request_id, **kw}))
        return dict(self.result)

    async def answer(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("answer", ws, request_id, kw)

    async def approve(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("approve", ws, request_id, kw)

    async def feedback(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("feedback", ws, request_id, kw)

    async def cancel(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("cancel", ws, request_id, kw)

    async def retry(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("retry", ws, request_id, kw)

    async def close_pr(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return self._record("close_pr", ws, request_id, kw)


@pytest.fixture(autouse=True)
def _fresh_engines() -> Iterator[None]:
    """Async connections are bound to one event loop; start every test with fresh engines."""
    reset_engines()
    yield
    reset_engines()


@pytest_asyncio.fixture
async def fake_slack(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeSlack]:
    fake = await FakeSlack().start()
    monkeypatch.setenv("SLACK_API_URL", fake.api_url)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("SLACK_CLIENT_ID", "client-1")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret-1")
    monkeypatch.setenv("ACTRON_PUBLIC_URL", "https://actron.test")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    get_settings.cache_clear()
    yield fake
    await fake.stop()
    get_settings.cache_clear()


@pytest.fixture
def flow() -> Iterator[FakeFlow]:
    fake = FakeFlow()
    slack_common.set_service(fake)  # type: ignore[arg-type]
    yield fake
    slack_common.set_service(None)


@pytest.fixture
def ws_env(db_session: Any, redis_client: Any) -> Iterator[SimpleNamespace]:
    """A workspace with a Slack team, a requester with a Slack id, one approver and a stored bot token."""
    tag = uuid.uuid4().hex[:8]
    env = SimpleNamespace(
        ws=f"acme-{tag}",
        team="T123",
        requester_slack=f"U1{tag}",
        approver_slack=f"U2{tag}",
        user_id=uuid.uuid4(),
        token="xoxb-stored-token-9876",
        tag=tag,
    )
    db_session.add(
        Workspace(
            id=env.ws,
            name="Acme",
            slack_team_id=env.team,
            graph_name=f"actron_{env.ws}".replace("-", "_"),
            settings={"approvers": [env.approver_slack]},
        )
    )
    db_session.add(User(id=env.user_id, slack_user_id=env.requester_slack, name="Priya"))
    db_session.flush()
    db_session.add(
        Connection(
            workspace_id=env.ws,
            provider="slack",
            status="connected",
            config={"teamId": env.team, "botUserId": "UBOT", "channels": ["C1"]},
            secret_encrypted=encrypt_secret({"bot_token": env.token}),
            secret_last4=env.token[-4:],
        )
    )
    db_session.commit()

    def make_request(
        state: str = "Investigating",
        *,
        channel: str | None = "C1",
        thread_ts: str | None = "1700000000.000100",
        status_ts: str | None = None,
        **over: Any,
    ) -> tuple[str, dict[str, Any]]:
        rid = f"req_01J{uuid.uuid4().hex[:23].upper()}"
        db_session.add(
            Request(
                id=rid,
                workspace_id=env.ws,
                kind="feature",
                title="Export invoices as CSV",
                text="t",
                state=state,
                source="slack",
                requester_user_id=env.user_id,
                slack_channel=channel,
                slack_thread_ts=thread_ts,
                slack_status_ts=status_ts,
                temporal_workflow_id=f"wf-{rid}",
            )
        )
        db_session.commit()
        view = make_view(state, id=rid, **over)
        if channel:
            view["slack"] = {
                "channel": channel,
                "threadTs": thread_ts,
                "permalink": f"https://acme.slack.com/archives/{channel}/p1",
            }
        return rid, view

    env.make_request = make_request
    env.db = db_session
    try:
        yield env
    finally:
        db_session.rollback()
        db_session.execute(delete(Workspace).where(Workspace.id == env.ws))
        db_session.execute(delete(User).where(User.slack_user_id.like(f"%{tag}")))
        db_session.commit()


def status_ts_of(env: SimpleNamespace, rid: str) -> str | None:
    env.db.expire_all()
    row = env.db.get(Request, rid)
    return None if row is None else row.slack_status_ts


# ---------------------------------------------------------------- signed HTTP requests to the bot


def sign(body: bytes, *, ts: int | None = None, secret: str = SIGNING_SECRET) -> dict[str, str]:
    import time

    from slack_sdk.signature import SignatureVerifier

    stamp = str(ts if ts is not None else int(time.time()))
    sig = SignatureVerifier(secret).generate_signature(timestamp=stamp, body=body)
    return {"x-slack-request-timestamp": stamp, "x-slack-signature": str(sig)}


@dataclass
class Bot:
    client: Any
    fake: FakeSlack
    flow: FakeFlow
    env: SimpleNamespace
    counter: int = 0

    async def post(
        self, path: str, body: bytes, content_type: str, *, headers: dict[str, str] | None = None
    ) -> Any:
        h = {"content-type": content_type, **(headers if headers is not None else sign(body))}
        resp = await self.client.post(path, content=body, headers=h)
        await asyncio.sleep(0.05)  # Bolt runs listeners in their own task after it has answered
        return resp

    async def command(
        self,
        text: str,
        *,
        trigger: str | None = None,
        team: str = "T123",
        channel: str = "C1",
        user: str | None = None,
    ) -> Any:
        from urllib.parse import urlencode

        self.counter += 1
        form = {
            "command": "/actron",
            "text": text,
            "team_id": team,
            "channel_id": channel,
            "user_id": user or self.env.requester_slack,
            "trigger_id": trigger or f"trig{self.counter}.1",
            "response_url": self.fake.response_url,
        }
        return await self.post(
            "/slack/commands", urlencode(form).encode(), "application/x-www-form-urlencoded"
        )

    async def event(
        self, event: dict[str, Any], *, event_id: str | None = None, team: str = "T123"
    ) -> Any:
        import json

        self.counter += 1
        payload = {
            "type": "event_callback",
            "team_id": team,
            "event_id": event_id or f"Ev{self.counter}",
            "event": event,
            "authorizations": [{"team_id": team, "user_id": "UBOT", "is_bot": True}],
        }
        return await self.post("/slack/events", json.dumps(payload).encode(), "application/json")

    async def interaction(
        self, payload: dict[str, Any], *, trigger: str | None = None, team: str = "T123"
    ) -> Any:
        import json
        from urllib.parse import urlencode

        self.counter += 1
        full = {
            "team": {"id": team},
            "user": {"id": self.env.requester_slack, "team_id": team},
            "channel": {"id": "C1"},
            "trigger_id": trigger or f"itrig{self.counter}.1",
            **payload,
        }
        return await self.post(
            "/slack/interactions",
            urlencode({"payload": json.dumps(full)}).encode(),
            "application/x-www-form-urlencoded",
        )

    async def click(self, action_id: str, *, trigger: str | None = None, **extra: Any) -> Any:
        return await self.interaction(
            {
                "type": "block_actions",
                "actions": [{"action_id": action_id, "type": "button", **extra}],
            },
            trigger=trigger,
        )


@pytest_asyncio.fixture
async def bot(fake_slack: FakeSlack, flow: FakeFlow, ws_env: SimpleNamespace) -> AsyncIterator[Bot]:
    import httpx
    from fastapi import FastAPI

    from actron.integrations import slack_bot

    async def on_create(ws: str, kw: dict[str, Any]) -> dict[str, Any]:
        rid, view = ws_env.make_request(
            "Investigating", channel=kw["slack"]["channel"], thread_ts=kw["slack"]["threadTs"]
        )
        flow.views[rid] = view
        return view

    flow.on_create = on_create
    app = FastAPI()
    slack_bot.mount(app, slack_bot.create_app(signing_secret=SIGNING_SECRET))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://actron.test"
    ) as client:
        yield Bot(client, fake_slack, flow, ws_env)
        await slack_bot.drain()
