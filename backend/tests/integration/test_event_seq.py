"""A-AC-9: events.seq is gap-free and strictly increasing per request under 50 concurrent writers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from actron.db.events_seq import RequestNotFound, next_seq, next_seq_async
from actron.db.models import Event, Request, Workspace
from actron.db.session import async_session, session_scope

pytestmark = pytest.mark.integration


@pytest.fixture
def request_ids(db_url: str) -> Iterator[tuple[str, str, str]]:
    ws = f"ws-{uuid.uuid4().hex[:6]}"
    ids = (f"req_{uuid.uuid4().hex[:10]}", f"req_{uuid.uuid4().hex[:10]}")
    with session_scope(db_url) as s:
        s.add(Workspace(id=ws, name="n", graph_name=ws))
        s.flush()
        for rid in ids:
            s.add(
                Request(
                    id=rid,
                    workspace_id=ws,
                    kind="feature",
                    title="t",
                    text="t",
                    state="new",
                    source="ui",
                    temporal_workflow_id="wf",
                )
            )
    yield ws, *ids
    with session_scope(db_url) as s:
        s.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": ws})


def write_event(db_url: str, ws: str, rid: str) -> int:
    with session_scope(db_url) as s:
        seq = next_seq(s, rid)
        s.add(Event(workspace_id=ws, request_id=rid, seq=seq, type="test.event", payload={}))
        return seq


def seqs(db_url: str, rid: str) -> list[int]:
    with session_scope(db_url) as s:
        rows = s.execute(
            text("SELECT seq FROM events WHERE request_id = :r ORDER BY seq"), {"r": rid}
        ).all()
    return [r[0] for r in rows]


def test_fifty_concurrent_writers_are_gap_free_a_ac_9(
    db_url: str, request_ids: tuple[str, str, str]
) -> None:
    """A-AC-9"""
    ws, rid, _ = request_ids
    with ThreadPoolExecutor(max_workers=50) as pool:
        returned = list(pool.map(lambda _: write_event(db_url, ws, rid), range(50)))
    assert sorted(returned) == list(range(1, 51))
    assert seqs(db_url, rid) == list(range(1, 51))


def test_two_requests_have_independent_sequences_a_ac_9(
    db_url: str, request_ids: tuple[str, str, str]
) -> None:
    """A-AC-9"""
    ws, a, b = request_ids
    jobs = [a, b] * 25
    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(lambda rid: write_event(db_url, ws, rid), jobs))
    assert seqs(db_url, a) == list(range(1, 26))
    assert seqs(db_url, b) == list(range(1, 26))


def test_rollback_does_not_leave_a_gap_a_ac_9(
    db_url: str, request_ids: tuple[str, str, str]
) -> None:
    """A-AC-9: a failed writer gives its number back."""
    ws, rid, _ = request_ids
    assert write_event(db_url, ws, rid) == 1
    with pytest.raises(RuntimeError), session_scope(db_url) as s:
        assert next_seq(s, rid) == 2
        raise RuntimeError("writer failed before commit")
    assert write_event(db_url, ws, rid) == 2
    assert seqs(db_url, rid) == [1, 2]


def test_unknown_request_raises_a_ac_9(db_url: str, request_ids: tuple[str, str, str]) -> None:
    """A-AC-9"""
    with pytest.raises(RequestNotFound), session_scope(db_url) as s:
        next_seq(s, "req_missing")


async def test_async_helper_is_gap_free_a_ac_9(
    db_url: str, request_ids: tuple[str, str, str]
) -> None:
    """A-AC-9: the async variant W6 uses in the API."""
    ws, rid, _ = request_ids

    async def one() -> int:
        async with async_session(db_url) as s:
            seq = await next_seq_async(s, rid)
            s.add(Event(workspace_id=ws, request_id=rid, seq=seq, type="test.event", payload={}))
            return seq

    got = await asyncio.gather(*(one() for _ in range(50)))
    assert sorted(got) == list(range(1, 51))
    assert seqs(db_url, rid) == list(range(1, 51))
