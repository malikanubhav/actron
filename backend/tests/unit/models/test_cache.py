"""A-AC-83: cache hits skip the network and are logged with `cached: true`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from actron import models
from actron.models import cache
from actron.models.questions import j4_check_link
from tests.fakes.jev import FakeJev
from tests.fakes.llm import FakeLLM


def test_key_format() -> None:
    """A-AC-83: key is model:<job>:<sha256(model + canonical(state) + canonical(questions))>."""
    ask = j4_check_link("q", "c")
    key = cache.key_for("check_link", "jev:jev-1.13.0", ask.state, ask.questions)
    expected = hashlib.sha256(
        ("jev:jev-1.13.0" + cache.canonical(ask.state) + cache.canonical(ask.questions)).encode()
    ).hexdigest()
    assert key == f"model:check_link:{expected}"
    assert cache.canonical({"b": 1, "a": 2}) == '{"a":2,"b":1}'


async def test_jev_hit_skips_network(
    jev_on: Callable[..., FakeJev], redis_client: Any, usage_rows: list[Any]
) -> None:
    """A-AC-83: the second identical call is served from Redis (TTL 7 days)."""
    cache.set_enabled(True)
    fake = jev_on(noul=0.77)
    first = await models.check_link("quote", "claim")
    second = await models.check_link("quote", "claim")
    assert fake.calls == 1
    assert not first.cached and second.cached and second.probability == first.probability
    assert [r.cached for r in usage_rows] == [False, True]
    [key] = redis_client.keys("model:check_link:*")
    assert 0 < redis_client.ttl(key) <= 7 * 24 * 3600
    await models.check_link("other quote", "claim")
    assert fake.calls == 2


async def test_llm_answers_cached_errors_not(
    llm_on: Callable[..., FakeLLM], redis_client: Any
) -> None:
    """A-AC-83: LLM judgments are cached; failures are not."""
    cache.set_enabled(True)
    fake = llm_on([RuntimeError("down")])
    stubbed = await models.check_link("q", "c")
    assert stubbed.stub and redis_client.keys("model:*") == []
    fake.replies = [json.dumps({"answers": {"supported": {"noul": 0.6}}})]
    a = await models.check_link("q", "c")
    b = await models.check_link("q", "c")
    assert not a.cached and b.cached and b.provider == "llm"
