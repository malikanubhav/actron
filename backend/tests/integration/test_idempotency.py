"""Idempotency keys (spec B, B1): the same key returns the same result and writes one event (B-AC-2)."""

from __future__ import annotations

import asyncio

import pytest

from actron.flow import service
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401


async def _req(w6: W6Env) -> str:  # noqa: F811
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    return str(view["id"])


async def test_same_key_twice_one_event(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-2: repeating an action with the same key returns the same result and creates one event."""
    rid = await _req(w6)
    first = await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-1")
    second = await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-1")
    assert first == second
    assert w6.types(rid).count("request.cancel_requested") == 1
    assert len(gateway.signals) == 1


async def test_same_key_concurrently_one_event(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-2: a double click (Slack and UI retrying together) still creates one event."""
    rid = await _req(w6)
    results = await asyncio.gather(*[service.cancel(w6.ws, rid, "x", w6.actor(), "idem-2") for _ in range(5)])
    assert all(r == results[0] for r in results)
    assert w6.types(rid).count("request.cancel_requested") == 1
    assert len(gateway.signals) == 1


async def test_errors_are_replayed(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-2: a refused action repeated with the same key gives the same refusal and no extra event."""
    rid = await _req(w6)
    for _ in range(2):
        with pytest.raises(service.Conflict) as exc:
            await service.approve(w6.ws, rid, "pr", "abc", w6.actor(), "idem-3")
        assert exc.value.code == "invalid_transition"
    assert w6.types(rid) == ["request.created"]


async def test_different_keys_two_events(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    rid = await _req(w6)
    await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-4")
    await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-5")
    assert w6.types(rid).count("request.cancel_requested") == 2


async def test_postgres_fallback_when_redis_down(w6: W6Env, gateway: FakeGateway,  # noqa: F811
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """B1: with Redis unavailable, `idempotency_keys` in PostgreSQL keeps actions idempotent."""
    rid = await _req(w6)

    def broken() -> object:
        raise ConnectionError("redis down")

    monkeypatch.setattr(service, "redis_client", broken)
    first = await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-6")
    second = await service.cancel(w6.ws, rid, "x", w6.actor(), "idem-6")
    assert first == second
    assert w6.types(rid).count("request.cancel_requested") == 1
