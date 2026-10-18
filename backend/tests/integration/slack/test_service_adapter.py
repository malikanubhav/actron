"""The adapter between the Slack code and actron.flow.service (W6): only accepted keywords are passed."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from actron.integrations.slack_common import ServiceAdapter


class InvalidTransition(Exception):
    pass


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    mod = types.ModuleType("actron.flow.service")

    async def create_request(ws: str, text: str, actor: dict[str, Any]) -> dict[str, Any]:
        calls.append(("create_request", (ws, text), {"actor": actor}))
        return {"request": {"id": "req_1", "state": "Investigating"}}

    async def answer(ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        calls.append(("answer", (ws, request_id), kw))
        return {"status": "accepted", "reason": None}

    def approve(ws: str, request_id: str, kind: str, head_sha: str | None = None) -> dict[str, Any]:
        calls.append(("approve", (ws, request_id), {"kind": kind, "head_sha": head_sha}))
        raise InvalidTransition("no")

    async def get_request_view(ws: str, request_id: str) -> dict[str, Any]:
        return {"id": request_id}

    mod.create_request = create_request  # type: ignore[attr-defined]
    mod.answer = answer  # type: ignore[attr-defined]
    mod.approve = approve  # type: ignore[attr-defined]
    mod.get_request_view = get_request_view  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "actron.flow.service", mod)
    return calls


async def test_unknown_keywords_are_dropped_and_results_unwrapped(service: list[Any]) -> None:
    svc = ServiceAdapter()
    view = await svc.create_request(
        "ws", text="hi", kind_hint=None, actor={"a": 1}, slack={"channel": "C"}, idempotency_key="k"
    )
    assert view == {"id": "req_1", "state": "Investigating"}
    assert service[0] == ("create_request", ("ws", "hi"), {"actor": {"a": 1}})


async def test_var_keyword_functions_get_everything(service: list[Any]) -> None:
    out = await ServiceAdapter().answer(
        "ws", "r", question_id="q1", value="yes", actor={}, idempotency_key="k"
    )
    assert out["status"] == "accepted" and service[0][2]["idempotency_key"] == "k"


async def test_known_refusals_become_refused_results(service: list[Any]) -> None:
    out = await ServiceAdapter().approve(
        "ws", "r", kind="pr", revision_hash=None, head_sha="abc", actor={}, idempotency_key="k"
    )
    assert out == {"status": "refused", "reason": "invalid_transition", "state": None}
    assert service[0][2] == {"kind": "pr", "head_sha": "abc"}


async def test_get_request_view_passes_through(service: list[Any]) -> None:
    assert await ServiceAdapter().get_request_view("ws", "req_9") == {"id": "req_9"}


def test_arguments_bind_to_the_real_flow_service_signatures() -> None:
    """Every call the bot makes must bind to W6's actual functions (checked without calling them)."""
    pytest.importorskip("actron.flow.service")
    import importlib

    mod = importlib.import_module("actron.flow.service")
    adapter = ServiceAdapter()
    actor = {"userId": "u", "slackUserId": "U1", "surface": "slack", "name": "Priya"}
    cases: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
        (
            "create_request",
            (),
            {
                "text": "hello",
                "kind_hint": None,
                "actor": actor,
                "slack": {"channel": "C", "threadTs": "1.1"},
                "idempotency_key": "k",
            },
        ),
        (
            "answer",
            ("r",),
            {"question_id": "q", "value": "v", "actor": actor, "idempotency_key": "k"},
        ),
        (
            "approve",
            ("r",),
            {
                "kind": "pr",
                "revision_hash": None,
                "head_sha": "abc",
                "actor": actor,
                "idempotency_key": "k",
            },
        ),
        (
            "feedback",
            ("r",),
            {"text": "t", "head_sha": "abc", "actor": actor, "idempotency_key": "k"},
        ),
        ("cancel", ("r",), {"reason": None, "actor": actor, "idempotency_key": "k"}),
        ("retry", ("r",), {"actor": actor, "idempotency_key": "k"}),
        ("close_pr", ("r",), {"reason": "x", "actor": actor, "idempotency_key": "k"}),
    ]
    import inspect

    for name, args, kwargs in cases:
        fn = getattr(mod, name)
        typed = adapter._typed(mod, kwargs)
        use = {k: v for k, v in typed.items() if k in inspect.signature(fn).parameters}
        inspect.signature(fn).bind(
            "ws", *args, **use
        )  # raises TypeError when a required argument is missing
    typed = adapter._typed(mod, cases[0][2])
    assert type(typed["actor"]).__name__ == "Actor" and typed["actor"].slack_user_id == "U1"
    assert type(typed["slack"]).__name__ == "SlackRef" and typed["source"] == "slack"
