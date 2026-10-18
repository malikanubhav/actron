"""The fake Jev behaves like the documented API (https://docs.typesafe.ai/api.md, read 17 Oct 2026).

A-AC-79, A-AC-80: request validation, error codes and the answer shape the client parses.
"""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.jev import FakeJev

URL = "https://api.typesafe.ai/v1/systemone"
AUTH = {"Authorization": "Bearer k"}


def _post(fake: FakeJev, body: object, headers: dict[str, str] | None = None) -> httpx.Response:
    with httpx.Client(transport=httpx.MockTransport(fake.handle)) as c:
        return c.post(URL, json=body, headers=headers if headers is not None else AUTH)


def test_documented_answer_shapes() -> None:
    """A-AC-79: noul -> noul; choice -> choice, probabilities, confidence; score -> score, legend, probabilities."""
    body = {
        "model": "jev-1.13.0",
        "state": "Help! My payouts have been failing for 3 days.",
        "questions": {
            "is_urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
            "department": {
                "type": "choice",
                "instructions": "Which team?",
                "criteria": {"billing": "Payments", "technical": "Bugs", "sales": None},
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated?",
                "criteria": ["Calm", "Frustrated", "Very angry"],
            },
        },
    }
    resp = _post(FakeJev(noul=0.95, choice="billing", score=1.0), body)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"model", "answers", "usage"}
    assert set(data["usage"]) == {"input_tokens", "output_tokens"}
    assert data["answers"]["is_urgent"] == {"type": "noul", "noul": 0.95}
    choice = data["answers"]["department"]
    assert (
        set(choice) == {"type", "choice", "probabilities", "confidence"}
        and choice["choice"] == "billing"
    )
    assert sum(choice["probabilities"].values()) == pytest.approx(1.0)
    score = data["answers"]["frustration"]
    assert set(score) == {"type", "score", "legend", "probabilities", "confidence"}
    assert score["legend"] == {"0": "Calm", "1": "Frustrated", "2": "Very angry"}


@pytest.mark.parametrize(
    ("body", "headers", "status"),
    [
        (
            {"model": "m", "state": "s", "questions": {"q": {"type": "noul", "instructions": "?"}}},
            {},
            401,
        ),
        ({"state": "s", "questions": {"q": {"type": "noul", "instructions": "?"}}}, AUTH, 422),
        ({"model": "m", "state": "s", "questions": {}}, AUTH, 422),
        (
            {
                "model": "m",
                "state": "s",
                "questions": {"q": {"type": "maybe", "instructions": "?"}},
            },
            AUTH,
            422,
        ),
        (
            {
                "model": "m",
                "state": "s",
                "questions": {"q": {"type": "choice", "instructions": "?", "criteria": ["a"]}},
            },
            AUTH,
            422,
        ),
        (
            {
                "model": "m",
                "state": "s",
                "questions": {
                    "q": {"type": "score", "instructions": "?", "criteria": ["only one"]}
                },
            },
            AUTH,
            422,
        ),
    ],
)
def test_documented_errors(body: object, headers: dict[str, str], status: int) -> None:
    """A-AC-80: 401 without a key; 422 for invalid questions (as documented)."""
    assert _post(FakeJev(), body, headers).status_code == status


def test_scripted_statuses_and_retry_after() -> None:
    """A-AC-80: scripted 429/529 responses carry Retry-After when configured."""
    fake = FakeJev(statuses=[429, 529], retry_after="2")
    body = {"model": "m", "state": "s", "questions": {"q": {"type": "noul", "instructions": "?"}}}
    r1, r2, r3 = (_post(fake, body) for _ in range(3))
    assert (r1.status_code, r2.status_code, r3.status_code) == (429, 529, 200)
    assert r1.headers["retry-after"] == "2"
