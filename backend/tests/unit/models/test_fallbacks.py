"""A-AC-80, A-AC-81: Jev retries and typed errors; LLM fallback with JSON validation; stub last."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from actron import models
from actron.models import jev
from actron.models.questions import j4_check_link
from tests.fakes.jev import FakeJev, SleepRecorder
from tests.fakes.llm import FakeLLM


async def test_429_twice_then_ok(jev_on: Callable[..., FakeJev], jev_sleeps: SleepRecorder) -> None:
    """A-AC-80: 429, 429, 200 succeeds after backoff 0.5 s then 1 s."""
    fake = jev_on(statuses=[429, 429], noul=0.9)
    j = await models.check_link("q", "c")
    assert fake.calls == 3 and j.provider == "jev" and j.probability == pytest.approx(0.9)
    assert jev_sleeps.delays == [0.5, 1.0]


async def test_529_twice_then_ok(jev_on: Callable[..., FakeJev], jev_sleeps: SleepRecorder) -> None:
    """A-AC-80: 529 is retried like 429."""
    fake = jev_on(statuses=[529, 529], noul=0.2)
    j = await models.judge_link("t", models.Candidate(kind="file", name="a.ts"))
    assert fake.calls == 3 and j.provider == "jev"
    assert jev_sleeps.delays == [0.5, 1.0]


async def test_retry_after_is_honoured_up_to_4s(
    jev_on: Callable[..., FakeJev], jev_sleeps: SleepRecorder
) -> None:
    """A-AC-80: Retry-After raises the wait, capped at 4 s."""
    jev_on(statuses=[429, 429], retry_after="30")
    await models.check_link("q", "c")
    assert jev_sleeps.delays == [4.0, 4.0]


async def test_four_attempts_then_rate_limited(
    jev_on: Callable[..., FakeJev], jev_sleeps: SleepRecorder
) -> None:
    """A-AC-80: at most 4 attempts, then a typed error."""
    fake = jev_on(statuses=[429, 429, 429, 429, 429])
    with pytest.raises(jev.JevRateLimited):
        await jev.ask(j4_check_link("q", "c"))
    assert fake.calls == 4 and jev_sleeps.delays == [0.5, 1.0, 2.0]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, jev.JevBadRequest),
        (401, jev.JevAuthError),
        (413, jev.JevPayloadTooLarge),
        (415, jev.JevUnsupportedMediaType),
        (422, jev.JevValidationError),
    ],
)
async def test_typed_errors_not_retried(
    jev_on: Callable[..., FakeJev], status: int, error: type[Exception]
) -> None:
    """A-AC-80: 400/401/413/415/422 raise typed errors without retry."""
    fake = jev_on(statuses=[status])
    with pytest.raises(error):
        await jev.ask(j4_check_link("q", "c"))
    assert fake.calls == 1


async def test_timeout_is_typed(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-80: a timeout raises JevTimeout."""
    jev_on()

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    jev.set_transport(httpx.MockTransport(boom))
    with pytest.raises(jev.JevTimeout):
        await jev.ask(j4_check_link("q", "c"))


async def test_422_falls_back_to_llm(
    jev_on: Callable[..., FakeJev], llm_on: Callable[..., FakeLLM], usage_rows: list[Any]
) -> None:
    """A-AC-80: a 422 from Jev falls back to the LLM with the same question."""
    jev_on(statuses=[422])
    fake = llm_on([json.dumps({"answers": {"supported": {"type": "noul", "noul": 0.83}}})])
    j = await models.check_link("quote", "claim")
    assert (
        j.provider == "llm"
        and j.probability == pytest.approx(0.83)
        and j.model == "groq/fake-decision"
    )
    assert len(fake.calls) == 1
    prompt = fake.calls[0]["messages"][0]["content"]
    assert '"supported"' in prompt and "Does `quote` support `claim` exactly as stated?" in prompt
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert [(r.provider, r.ok) for r in usage_rows] == [("jev", False), ("llm", True)]


async def test_malformed_jev_body_falls_back(
    jev_on: Callable[..., FakeJev], llm_on: Callable[..., FakeLLM]
) -> None:
    """A-AC-80: a 200 with a malformed answer counts as an error and falls back."""
    jev_on(malformed=True)
    llm_on([json.dumps({"answers": {"supported": {"noul": 0.4}}})])
    j = await models.check_link("q", "c")
    assert j.provider == "llm" and j.probability == pytest.approx(0.4)


async def test_no_jev_key_uses_llm_for_every_judgment(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-81: with no Jev key, each judgment job falls back to the LLM and validates its JSON."""

    def reply(call: dict[str, Any]) -> str:
        payload = json.loads(call["messages"][0]["content"].split("Input:\n", 1)[1])
        answers: dict[str, Any] = {}
        for qid, q in payload["questions"].items():
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.66}
            elif q["type"] == "choice":
                first = next(iter(q["criteria"]))
                answers[qid] = {
                    "type": "choice",
                    "choice": first,
                    "probabilities": {first: 0.9},
                    "confidence": 0.8,
                }
            else:
                answers[qid] = {
                    "type": "score",
                    "score": 1.0,
                    "probabilities": {"1": 1.0},
                    "confidence": 0.5,
                }
        return json.dumps({"answers": answers})

    llm_on(reply)
    cand = models.Candidate(kind="function", name="f")
    results = [
        await models.classify_message("t", "slack", None),
        await models.is_approval("d", "r", False),
        await models.judge_link("t", cand),
        *(await models.judge_links("t", [cand, cand])),
        await models.check_link("q", "c"),
        *(await models.rank_candidates("r", [models.CandidateSummary(id="a", summary="s")])),
        await models.judge_conflict(
            "r", models.DecisionView(statement="s", quote="q", status="approved")
        ),
        await models.classify_request("r"),
        await models.needs_question("s", [], 10.0),
        await models.is_scope_change({}, "d", []),
        await models.feedback_kind("f", {}),
    ]
    assert all(j.provider == "llm" and not j.stub for j in results)
    assert results[0].answer == "decision"
    assert results[1].probability == pytest.approx(0.66)


async def test_invalid_json_retried_once_then_stub(
    llm_on: Callable[..., FakeLLM], usage_rows: list[Any]
) -> None:
    """A-AC-81: invalid JSON -> one retry with a reminder -> stub."""
    fake = llm_on(["not json at all", "still {not json"])
    j = await models.judge_conflict(
        "r", models.DecisionView(statement="s", quote="q", status="approved")
    )
    assert j.stub and j.provider == "stub" and j.answer == "unrelated"
    assert len(fake.calls) == 2
    assert "not valid JSON" in fake.calls[1]["messages"][-1]["content"]
    assert [r.provider for r in usage_rows] == ["llm", "llm", "stub"]


async def test_invalid_option_then_valid(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-81: an option outside the criteria is invalid; the retry's valid answer is used."""
    llm_on(
        [
            json.dumps(
                {"answers": {"kind": {"type": "choice", "choice": "maybe", "probabilities": {}}}}
            ),
            json.dumps(
                {
                    "answers": {
                        "kind": {
                            "type": "choice",
                            "choice": "bug",
                            "probabilities": {"bug": 0.7, "feature": 0.3},
                        }
                    }
                }
            ),
        ]
    )
    j = await models.classify_request("It crashes")
    assert j.answer == "bug" and j.provider == "llm"


async def test_provider_error_moves_to_fallback_model(llm_on: Callable[..., FakeLLM]) -> None:
    """A-AC-81: a provider failure moves along LITELLM_FALLBACKS."""
    fake = llm_on(
        [
            RuntimeError("provider down"),
            json.dumps({"answers": {"supported": {"type": "noul", "noul": 0.7}}}),
        ],
        fallbacks="groq/fake-backup",
    )
    j = await models.check_link("q", "c")
    assert j.model == "groq/fake-backup"
    assert [c["model"] for c in fake.calls] == ["groq/fake-decision", "groq/fake-backup"]
