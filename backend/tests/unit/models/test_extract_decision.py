"""A-AC-84: `extract_decision` keeps only quotes that are exact substrings of the source text."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from actron import models
from tests.fakes.llm import FakeLLM, json_reply

TEXT = "After the call: we decided to keep format-on-type off by default for Clojure files."
GOOD = json_reply(
    is_decision=True,
    statement="Format on type stays off by default.",
    quote="keep format-on-type off by default",
    scope="formatter",
    status_hint="decided",
)
BAD = json_reply(
    is_decision=True,
    statement="Format on type stays off.",
    quote="keep format on type off by default",
    scope="formatter",
    status_hint="decided",
)


async def test_exact_quote_accepted_with_span(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-84: an exact quote is kept, with its character span."""
    fake = llm_on([GOOD])
    d = await models.extract_decision(TEXT)
    assert d is not None and d.quote == "keep format-on-type off by default"
    assert TEXT[d.quote_span[0] : d.quote_span[1]] == d.quote
    assert d.status_hint == "decided" and d.model == "groq/fake-decision"
    assert fake.calls[0]["response_format"]["type"] == "json_schema"


async def test_paraphrased_quote_retried_then_dropped(
    llm_on: Callable[..., FakeLLM], usage_rows: list[Any]
) -> None:
    """A-AC-84: a non-substring quote gets one retry with a reminder, then the result is dropped."""
    fake = llm_on([BAD, BAD])
    assert await models.extract_decision(TEXT) is None
    assert len(fake.calls) == 2
    assert "exact substring" in fake.calls[1]["messages"][-1]["content"]
    assert all(not r.ok for r in usage_rows)


async def test_retry_fixes_quote(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-84: if the retry copies the words exactly, the decision is kept."""
    llm_on([BAD, GOOD])
    d = await models.extract_decision(TEXT)
    assert d is not None and d.quote in TEXT


async def test_not_a_decision(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-84: is_decision false yields None."""
    llm_on(
        [json_reply(is_decision=False, statement="", quote="", scope="", status_hint="proposed")]
    )
    assert await models.extract_decision("thanks all") is None


def test_find_quote_rules() -> None:
    """A-AC-84: only surrounding whitespace is forgiven."""
    assert models.find_quote("abc def", " def ") == (4, 7)
    assert models.find_quote("abc def", "Def") is None
    assert models.find_quote("abc def", "") is None


async def test_deepseek_gets_json_object_with_the_schema_in_the_prompt(llm_on: Callable[..., FakeLLM]) -> None:
    """DeepSeek rejects `json_schema` response formats, so it is asked for `json_object` and sent the schema."""
    import os

    fake = llm_on([GOOD])
    os.environ["MODEL_DECISION"] = "deepseek/deepseek-flash"
    from actron.config import get_settings

    get_settings.cache_clear()
    d = await models.extract_decision(TEXT)
    assert d is not None and d.quote == "keep format-on-type off by default"
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in fake.calls[0]["messages"][-1]["content"]
