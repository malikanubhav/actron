"""A-AC-85: `model_calls` rows record provider, model, tokens, latency and flags on every path."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from actron import models
from actron.models import cache, usage
from tests.fakes.jev import FakeJev
from tests.fakes.llm import FakeLLM


async def test_rows_for_each_path(
    jev_on: Callable[..., FakeJev],
    llm_on: Callable[..., FakeLLM],
    usage_rows: list[Any],
    redis_client: Any,
) -> None:
    """A-AC-85: jev ok, jev error, llm, cached and stub rows."""
    cache.set_enabled(True)
    fake = jev_on(noul=0.5)
    await models.check_link("q", "c", ws="ws1", request_id="req_1")
    await models.check_link("q", "c", ws="ws1")
    fake.statuses = [401]
    llm_on([json.dumps({"answers": {"supported": {"noul": 0.9}}})])
    await models.check_link("q2", "c", ws="ws1")
    by = [(r.provider, r.cached, r.stub, r.ok) for r in usage_rows]
    assert by == [
        ("jev", False, False, True),
        ("jev", True, False, True),
        ("jev", False, False, False),
        ("llm", False, False, True),
    ]
    first = usage_rows[0]
    assert first.job == "check_link" and first.model == "jev-1.13.0"
    assert first.workspace_id == "ws1" and first.request_id == "req_1"
    assert first.input_tokens > 0 and first.output_tokens == 10 and first.latency_ms >= 0
    assert first.cost_usd == pytest.approx(first.input_tokens * 0.042 / 1_000_000, abs=1e-8)
    assert usage_rows[2].error and "JevAuthError" in usage_rows[2].error
    llm_row = usage_rows[3]
    assert (llm_row.input_tokens, llm_row.output_tokens) == (
        50,
        20,
    ) and llm_row.model == "groq/fake-decision"


async def test_stub_row(usage_rows: list[Any]) -> None:
    """A-AC-85: a stub writes a row with stub=true and zero cost."""
    await models.classify_request("x", ws="ws2")
    [row] = usage_rows
    assert row.stub and row.provider == "stub" and row.cost_usd == 0.0 and row.workspace_id == "ws2"


def test_price_table() -> None:
    """A-AC-85: cost from the price table (USD per million tokens)."""
    assert usage.cost_for("jev-1.13.0", 1_000_000, 500) == pytest.approx(0.042)
    assert usage.cost_for("anthropic/claude-sonnet-4-5", 1000, 1000) == pytest.approx(0.018)
    assert usage.cost_for("openrouter/meta-llama/llama-3.3-70b-instruct:free", 10**6, 10**6) == 0.0
    assert usage.cost_for("unknown/model", 10**6, 10**6) == 0.0


async def test_rows_in_postgres_and_spent_today(db_url: str) -> None:
    """A-AC-85 and B12a: the default sink writes `model_calls`; spent_today sums today's cost."""
    usage.set_sink(None)
    ws = f"ws-usage-{datetime.now(UTC).timestamp():.0f}"
    await usage.record(
        usage.UsageRow(
            job="check_link",
            provider="jev",
            model="jev-1.13.0",
            workspace_id=ws,
            input_tokens=2_000_000,
            output_tokens=5,
            latency_ms=12,
        )
    )
    await usage.record(
        usage.UsageRow(
            job="write_ticket", provider="stub", model="stub", workspace_id=ws, stub=True
        )
    )
    from sqlalchemy import select

    from actron.db.models import ModelCall
    from actron.db.session import session_scope

    with session_scope(db_url) as s:
        rows = s.execute(select(ModelCall).where(ModelCall.workspace_id == ws)).scalars().all()
        got = sorted((r.job, r.provider, r.stub, r.input_tokens, r.latency_ms) for r in rows)
    assert got == [
        ("check_link", "jev", False, 2_000_000, 12),
        ("write_ticket", "stub", True, 0, 0),
    ]
    assert usage.spent_today(ws, url=db_url) == pytest.approx(0.084)
