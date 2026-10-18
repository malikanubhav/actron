"""Fixtures shared by W6 tests (API, service, integration). Import the names you need into a test module.

- `w6`: a fresh workspace (owner user, membership) in the per-session test database; Redis db from
  ACTRON_TEST_REDIS_DB; the workspace graph is dropped afterwards.
- `gateway`: a FakeGateway installed as the service's workflow gateway (records starts, signals, schedules).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio

from actron.flow import service


@dataclass
class FakeGateway:
    started: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    signals: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    schedules: list[tuple[str, str, str]] = field(default_factory=list)
    syncs: list[tuple[str, str, str]] = field(default_factory=list)
    state_view: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_signals: int = 0
    fail_start: bool = False
    on_signal: Any = None

    async def start_request(self, ws: str, request_id: str, inp: dict[str, Any]) -> None:
        if self.fail_start:
            raise RuntimeError("temporal down")
        self.started.append((ws, request_id, inp))

    async def signal(self, request_id: str, name: str, payload: dict[str, Any]) -> None:
        if self.fail_signals > 0:
            self.fail_signals -= 1
            raise RuntimeError("temporal down")
        self.signals.append((request_id, name, payload))
        if self.on_signal is not None:
            await self.on_signal(request_id, name, payload)

    async def query_state(self, request_id: str) -> dict[str, Any] | None:
        return self.state_view.get(request_id)

    async def start_source_sync(self, ws: str, source: str, mode: str) -> str:
        wf = f"sync:{ws}:{source}:{mode}:{len(self.syncs)}"
        self.syncs.append((ws, source, mode))
        return wf

    async def ensure_schedule(self, ws: str, source: str) -> None:
        self.schedules.append(("ensure", ws, source))

    async def trigger_schedule(self, ws: str, source: str) -> None:
        self.schedules.append(("trigger", ws, source))

    async def pause_schedule(self, ws: str, source: str) -> None:
        self.schedules.append(("pause", ws, source))

    async def delete_schedule(self, ws: str, source: str) -> None:
        self.schedules.append(("delete", ws, source))


@dataclass
class W6Env:
    ws: str
    owner_id: str
    db_url: str

    def add_user(self, name: str, *, role: str | None = "member", slack_user_id: str | None = None) -> str:
        from sqlalchemy import select

        from actron.db import models as m
        from actron.db.session import session_scope

        with session_scope() as s:
            user = s.scalar(select(m.User).where(m.User.slack_user_id == slack_user_id)) if slack_user_id else None
            if user is None:
                user = m.User(name=name, slack_user_id=slack_user_id)
                s.add(user)
                s.flush()
            if role and s.get(m.Membership, (user.id, self.ws)) is None:
                s.add(m.Membership(user_id=user.id, workspace_id=self.ws, role=role))
            return str(user.id)

    def set_settings(self, **values: Any) -> None:
        from actron.db import models as m
        from actron.db.session import session_scope

        with session_scope() as s:
            row = s.get(m.Workspace, self.ws)
            assert row is not None
            row.settings = {**(row.settings or {}), **values}

    def actor(self, user_id: str | None = None, surface: str = "ui") -> service.Actor:
        return service.Actor(user_id=user_id or self.owner_id, surface=surface)  # type: ignore[arg-type]

    def events(self, request_id: str) -> list[Any]:
        from actron.flow.events import load_request_events

        return load_request_events(self.ws, request_id)

    def types(self, request_id: str) -> list[str]:
        return [e.type for e in self.events(request_id)]


@pytest_asyncio.fixture
async def stack(w6: W6Env, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Real workflow + activities on a time-skipping server. GitHub and Linear are not connected unless a test
    patches `_github_cfg` / `_linear_cfg`; the investigator is a scripted stand-in (`stack.investigate`)."""
    import sys
    import types

    from temporalio.testing import WorkflowEnvironment

    from actron.activities import request as acts
    from tests.api._wf_harness import Fakes, RealStack, fake_investigation

    monkeypatch.setattr(acts, "_github_cfg", lambda ws: {})
    monkeypatch.setattr(acts, "_linear_cfg", lambda ws: {})
    mod = types.ModuleType("actron.flow.investigate")
    mod.investigate = fake_investigation()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "actron.flow.investigate", mod)
    env = await WorkflowEnvironment.start_time_skipping()
    rs = RealStack(env.client, Fakes())
    rs.module = mod  # type: ignore[attr-defined]
    rs.env = env  # type: ignore[attr-defined]
    try:
        async with rs:
            yield rs
    finally:
        service.set_gateway(None)
        await env.shutdown()


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    fake = FakeGateway()
    service.set_gateway(fake)
    try:
        yield fake
    finally:
        service.set_gateway(None)


@pytest_asyncio.fixture
async def w6(db_url: str, redis_url: str, gateway: FakeGateway) -> AsyncIterator[W6Env]:
    from actron.db import models as m
    from actron.db.session import session_scope
    from actron.flow.events import reset_redis_clients

    reset_redis_clients()
    ws = f"t{uuid.uuid4().hex[:10]}"
    with session_scope() as s:
        s.add(m.Workspace(id=ws, name="Test team", graph_name=f"actron_{ws}", settings={}))
        owner = m.User(name="Owner")
        s.add(owner)
        s.flush()
        s.add(m.Membership(user_id=owner.id, workspace_id=ws, role="owner"))
        owner_id = str(owner.id)
    try:
        yield W6Env(ws=ws, owner_id=owner_id, db_url=db_url)
    finally:
        try:
            from actron.graph.store import _STORES, store_for

            store = store_for(ws)
            store.drop()
            _STORES.pop(store.graph_name, None)
        except Exception:
            pass
