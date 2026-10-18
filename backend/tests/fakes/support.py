"""Fixtures shared by the W3 tests (import them into a test module with `from tests.fakes.support import *`)."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest

from actron.connectors import common
from actron.graph import ids

__all__ = ["drive", "fake_github", "fake_linear", "fake_slack", "ingest_worker", "pg_ws", "save_conn", "store", "temporal", "ws"]


@pytest.fixture
def pg_ws(db_url: str) -> str:
    """A workspace row in PostgreSQL (needed by cursors, runs and events)."""
    from actron.db.models import Workspace
    from actron.db.session import session_scope

    slug = "t" + secrets.token_hex(5)
    with session_scope() as session:
        session.add(Workspace(id=slug, name=slug, graph_name=ids.graph_name("actron", slug)))
    return slug


@pytest.fixture
def ws(pg_ws: str, falkordb_url: str) -> Iterator[str]:
    """Workspace with a PostgreSQL row; its graph is dropped afterwards."""
    from actron.graph import store as store_mod

    yield pg_ws
    from actron.config import get_settings

    name = ids.graph_name(get_settings().FALKORDB_GRAPH_PREFIX, pg_ws)
    st = store_mod._STORES.pop(name, None)
    if st is not None:
        st.drop()
        st.close()


@pytest.fixture
def store(ws: str) -> Any:
    from actron.graph.store import store_for

    return store_for(ws)


@pytest.fixture
def fake_github() -> Iterator[Any]:
    from tests.fakes.github import FakeGithub

    fake = FakeGithub()
    common.set_transport("github", fake.transport())
    yield fake
    common.set_transport("github", None)


@pytest.fixture
def fake_slack() -> Iterator[Any]:
    from tests.fakes.slack import FakeSlack

    fake = FakeSlack()
    common.set_transport("slack", fake.transport())
    yield fake
    common.set_transport("slack", None)


@pytest.fixture
def fake_linear() -> Iterator[Any]:
    from tests.fakes.linear import FakeLinear

    fake = FakeLinear()
    common.set_transport("linear", fake.transport())
    yield fake
    common.set_transport("linear", None)


# A synchronous stand-in for SourceSyncWorkflow: the same loop without Temporal.
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class Driven:
    cursor: dict[str, Any]
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    pages: int = 0
    links_missing: int = 0
    meta: list[dict[str, Any]] = field(default_factory=list)


async def drive(module: Any, ws: str, config: dict[str, Any], cursor: dict[str, Any] | None = None,
                steps: list[str] | None = None, max_pages: int = 500) -> Driven:
    import asyncio

    out = Driven(cursor=dict(cursor or {}))
    for step in steps or list(module.STEPS):
        token: str | None = None
        while True:
            batch = await module.fetch_page(ws, step, out.cursor, token, config)
            res = await asyncio.to_thread(module.write_batch, ws, step, batch)
            out.pages += 1
            assert out.pages < max_pages, "runaway paging"
            out.cursor = common.merge_cursor(out.cursor, batch.cursor_update)
            out.counts = common.add_counts(out.counts, res.counts)
            out.errors.extend(batch.errors)
            out.errors.extend(res.errors)
            out.links_missing += res.links_missing
            out.changed.extend(res.changed_ids)
            out.meta.append(batch.meta)
            if batch.partial_reason:
                out.partial.append(batch.partial_reason)
            token = batch.next_page_token
            if token is None:
                break
    return out


# Temporal (real server): a client, and a worker on a private task queue so no other worker takes the tasks.
@pytest.fixture
async def temporal(temporal_address: str) -> Any:
    from temporalio.client import Client

    from actron.config import get_settings

    return await Client.connect(temporal_address, namespace=get_settings().TEMPORAL_NAMESPACE)


@pytest.fixture
async def ingest_worker(temporal: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Runs SourceSyncWorkflow with the real activities, plus a recording stand-in for W4's LinkingWorkflow."""
    import uuid

    from temporalio.worker import Worker

    from actron.activities import ingest as acts
    from actron.workflows.source_sync import SourceSyncWorkflow
    from tests.fakes.linking_stub import FakeLinking

    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr(acts, "TASK_QUEUE", f"ingest-t-{suffix}")
    monkeypatch.setattr(acts, "LINK_QUEUE", f"link-t-{suffix}")
    monkeypatch.setattr(acts, "_CLIENT", temporal)
    linked: list[tuple[str, list[str]]] = []

    async with (
        Worker(temporal, task_queue=acts.TASK_QUEUE, workflows=[SourceSyncWorkflow], activities=acts.ACTIVITIES),
        Worker(temporal, task_queue=acts.LINK_QUEUE, workflows=[FakeLinking]),
    ):
        yield {"client": temporal, "linked": linked, "acts": acts, "suffix": suffix}


@pytest.fixture
def save_conn(pg_ws: str) -> Any:
    """Insert a connection row with an encrypted secret."""
    from actron.db.crypto import encrypt_secret
    from actron.db.models import Connection
    from actron.db.session import session_scope

    def save(provider: str, config: dict[str, Any], secret: dict[str, Any] | None = None) -> None:
        with session_scope() as session:
            session.add(Connection(workspace_id=pg_ws, provider=provider, status="connected", config=config,
                                   secret_encrypted=encrypt_secret(secret) if secret else None))

    return save
