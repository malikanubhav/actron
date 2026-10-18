"""Slack bot: buttons, modal, thread replies, channel messages, uninstall (B-AC-53, B-AC-54, B-AC-91)."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from actron.db.models import Connection
from actron.integrations import slack_bot, slack_oauth
from tests.integration.slack.slack_fixtures import Bot
from tests.unit.slack.views import HASH, SHA, make_view


async def seed(bot: Bot, state: str = "Needs your input", **over: Any) -> str:
    rid, _ = bot.env.make_request(state)
    bot.flow.views[rid] = make_view(state, id=rid, **over)
    return rid


async def test_B_AC_53_answer_button_calls_service_with_right_arguments(bot: Bot) -> None:
    """B-AC-53"""
    rid = await seed(bot)
    r = await bot.click(f"answer:{rid}:q1:yes", trigger="t1")
    assert r.status_code == 200
    await slack_bot.drain()
    (call,) = bot.flow.of("answer")
    assert (call["ws"], call["request_id"], call["question_id"], call["value"]) == (
        bot.env.ws,
        rid,
        "q1",
        "yes",
    )
    assert (
        call["actor"]["slackUserId"] == bot.env.requester_slack
        and call["actor"]["surface"] == "slack"
    )
    assert call["idempotency_key"] == f"slack:t1:answer:{rid}:q1:yes"


async def test_answer_value_may_contain_colons(bot: Bot) -> None:
    rid = await seed(bot)
    await bot.click(f"answer:{rid}:target_branch:release:2.3")
    await slack_bot.drain()
    assert bot.flow.of("answer")[0]["value"] == "release:2.3"


async def test_select_menu_answer_uses_the_chosen_option(bot: Bot) -> None:
    rid = await seed(bot)
    await bot.click(
        f"answer:{rid}:target_branch:~select",
        type="static_select",
        selected_option={"value": "branch-3", "text": {"type": "plain_text", "text": "x"}},
    )
    await slack_bot.drain()
    assert bot.flow.of("answer")[0]["value"] == "branch-3"


async def test_indexed_answer_id_resolves_through_the_request_view(bot: Bot) -> None:
    rid = await seed(bot)
    await bot.click(f"answer:{rid}:q1:#1")
    await slack_bot.drain()
    assert bot.flow.of("answer")[0]["value"] == "no"


async def test_B_AC_53_approve_ticket_carries_the_hash(bot: Bot) -> None:
    rid = await seed(bot, "Awaiting approval")
    await bot.click(f"approve_ticket:{rid}:{HASH}")
    await slack_bot.drain()
    (call,) = bot.flow.of("approve")
    assert (call["kind"], call["revision_hash"], call["head_sha"]) == ("ticket", HASH, None)


async def test_B_AC_53_approve_pr_carries_the_head_sha(bot: Bot) -> None:
    rid = await seed(bot, "PR ready for review")
    await bot.click(f"approve_pr:{rid}:{SHA}")
    await slack_bot.drain()
    (call,) = bot.flow.of("approve")
    assert (call["kind"], call["revision_hash"], call["head_sha"]) == ("pr", None, SHA)


async def test_B_AC_53_duplicate_delivery_does_nothing_twice(bot: Bot) -> None:
    rid = await seed(bot, "Awaiting approval")
    for _ in range(3):
        await bot.click(f"approve_ticket:{rid}:{HASH}", trigger="same-trigger")
    await slack_bot.drain()
    assert len(bot.flow.of("approve")) == 1


async def test_close_pr_and_retry_buttons(bot: Bot) -> None:
    rid = await seed(bot, "PR ready for review")
    await bot.click(f"close_pr:{rid}")
    await bot.click(f"retry:{rid}")
    await slack_bot.drain()
    assert bot.flow.names() == ["close_pr", "retry"]
    assert bot.flow.of("close_pr")[0]["request_id"] == rid


async def test_open_button_is_acknowledged_and_does_nothing(bot: Bot) -> None:
    rid = await seed(bot)
    r = await bot.click(f"open:{rid}", url="https://actron.test/app/requests/x")
    await slack_bot.drain()
    assert r.status_code == 200 and bot.flow.names() == [] and bot.fake.calls == []


async def test_refused_approval_tells_only_the_clicker(bot: Bot) -> None:
    rid = await seed(bot, "Awaiting approval")
    bot.flow.result = {
        "status": "refused",
        "reason": "stale_revision",
        "state": "Awaiting approval",
    }
    await bot.click(f"approve_ticket:{rid}:{HASH}")
    await slack_bot.drain()
    (eph,) = bot.fake.of("chat.postEphemeral")
    assert eph.params["user"] == bot.env.requester_slack and "ticket changed" in eph.params["text"]
    assert bot.fake.of("chat.postMessage") == []


async def test_service_error_is_reported_not_raised(bot: Bot) -> None:
    rid = await seed(bot)

    async def boom(ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    bot.flow.answer = boom  # type: ignore[method-assign]
    r = await bot.click(f"answer:{rid}:q1:yes")
    await slack_bot.drain()
    assert r.status_code == 200 and len(bot.fake.of("chat.postEphemeral")) == 1


async def test_B_AC_54_request_changes_opens_modal_and_submission_sends_feedback(bot: Bot) -> None:
    """B-AC-54"""
    rid = await seed(bot, "PR ready for review")
    await bot.click(f"request_changes:{rid}", trigger="modal-trigger")
    (opened,) = bot.fake.of("views.open")
    view = opened.params["view"]
    assert opened.params["trigger_id"] == "modal-trigger"
    assert (
        view["type"] == "modal"
        and view["callback_id"] == "request_changes"
        and view["private_metadata"] == rid
    )
    assert view["blocks"][0]["element"]["type"] == "plain_text_input"

    submitted = {
        "type": "view_submission",
        "view": {
            "id": "V1",
            "type": "modal",
            "callback_id": "request_changes",
            "private_metadata": rid,
            "state": {
                "values": {
                    "feedback": {"text": {"type": "plain_text_input", "value": "Rename the helper"}}
                }
            },
        },
    }
    r = await bot.interaction(submitted, trigger="submit-trigger")
    assert r.status_code == 200
    await slack_bot.drain()
    (call,) = bot.flow.of("feedback")
    assert (call["request_id"], call["text"], call["head_sha"]) == (rid, "Rename the helper", SHA)


async def test_B_AC_54_empty_modal_is_rejected_with_a_field_error(bot: Bot) -> None:
    rid = await seed(bot, "PR ready for review")
    submitted = {
        "type": "view_submission",
        "view": {
            "id": "V2",
            "type": "modal",
            "callback_id": "request_changes",
            "private_metadata": rid,
            "state": {
                "values": {"feedback": {"text": {"type": "plain_text_input", "value": "  "}}}
            },
        },
    }
    r = await bot.interaction(submitted)
    assert json.loads(r.text) == {
        "response_action": "errors",
        "errors": {"feedback": "Write what should change."},
    }
    await slack_bot.drain()
    assert bot.flow.of("feedback") == []


def reply(
    bot: Bot, text: str, *, user: str | None = None, thread: str = "1700000000.000100", **extra: Any
) -> dict[str, Any]:
    return {
        "type": "message",
        "user": user or bot.env.requester_slack,
        "channel": "C1",
        "ts": "1700000500.000100",
        "thread_ts": thread,
        "text": text,
        **extra,
    }


async def test_B_AC_54_numbered_reply_answers_a_text_question(bot: Bot) -> None:
    """B-AC-54: a thread reply starting with the question number answers that text question."""
    rid = await seed(bot)
    await bot.event(reply(bot, "3 GBP and EUR only"))
    await slack_bot.drain()
    (call,) = bot.flow.of("answer")
    assert (call["request_id"], call["question_id"], call["value"]) == (
        rid,
        "q3",
        "GBP and EUR only",
    )


async def test_numbered_reply_matches_a_choice_by_label(bot: Bot) -> None:
    rid = await seed(bot)
    await bot.event(reply(bot, "1. Yes, keep Finance-only"))
    await slack_bot.drain()
    assert (
        bot.flow.of("answer")[0]["value"] == "yes" and bot.flow.of("answer")[0]["request_id"] == rid
    )


async def test_numbered_reply_to_a_choice_with_no_match_gets_a_hint(bot: Bot) -> None:
    await seed(bot)
    await bot.event(reply(bot, "1 maybe"))
    await slack_bot.drain()
    assert bot.flow.of("answer") == [] and len(bot.fake.of("chat.postEphemeral")) == 1


async def test_ordinary_thread_chatter_is_ignored(bot: Bot) -> None:
    await seed(bot)
    await bot.event(reply(bot, "thanks, looking now"))
    await bot.event(reply(bot, "9 not a question"))
    await slack_bot.drain()
    assert bot.flow.names() == []


async def test_feedback_prefix_sends_pr_feedback(bot: Bot) -> None:
    rid = await seed(bot, "PR ready for review")
    await bot.event(reply(bot, "feedback: please add a test for the empty case"))
    await slack_bot.drain()
    (call,) = bot.flow.of("feedback")
    assert (call["request_id"], call["text"], call["head_sha"]) == (
        rid,
        "please add a test for the empty case",
        SHA,
    )


async def test_bot_and_other_thread_messages_are_ignored(bot: Bot) -> None:
    await seed(bot)
    await bot.event(reply(bot, "3 sneaky", bot_id="B9"))
    await bot.event(reply(bot, "3 other thread", thread="1.1"))
    await bot.event(reply(bot, "3 edited", subtype="message_changed"))
    await slack_bot.drain()
    assert bot.flow.names() == []


async def test_B_AC_53_duplicate_message_event_answers_once(bot: Bot) -> None:
    await seed(bot)
    for _ in range(2):
        await bot.event(reply(bot, "3 GBP"), event_id="EvSame")
    await slack_bot.drain()
    assert len(bot.flow.of("answer")) == 1


@pytest.fixture
def ingest(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    mod = types.ModuleType("actron.connectors.slack")

    async def handle_message_event(ws: str, event: dict[str, Any]) -> None:
        seen.append((ws, event))

    mod.handle_message_event = handle_message_event  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "actron.connectors.slack", mod)
    return seen


async def test_messages_in_allowed_channels_feed_ingestion(
    bot: Bot, ingest: list[tuple[str, dict[str, Any]]]
) -> None:
    await bot.event(
        {"type": "message", "user": "UX", "channel": "C1", "ts": "1.2", "text": "hello"}
    )
    await bot.event(
        {"type": "message", "user": "UX", "channel": "C9", "ts": "1.3", "text": "elsewhere"}
    )
    await slack_bot.drain()
    assert [(w, e["ts"]) for w, e in ingest] == [(bot.env.ws, "1.2")]


async def test_thread_reply_in_allowed_channel_answers_and_is_ingested(
    bot: Bot, ingest: list[tuple[str, dict[str, Any]]]
) -> None:
    await seed(bot)
    await bot.event(reply(bot, "3 GBP"))
    await slack_bot.drain()
    assert len(bot.flow.of("answer")) == 1 and len(ingest) == 1


async def test_missing_ingestion_module_is_not_an_error(
    bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "actron.connectors.slack", None)  # import raises ImportError
    r = await bot.event(
        {"type": "message", "user": "UX", "channel": "C1", "ts": "1.2", "text": "hello"}
    )
    await slack_bot.drain()
    assert r.status_code == 200


@pytest.fixture
def paused(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    async def fake(ws: str, flag: bool) -> None:
        calls.append((ws, flag))

    monkeypatch.setattr(slack_oauth, "set_schedule_paused", fake)
    return calls


def conn(bot: Bot) -> Connection:
    bot.env.db.expire_all()
    return bot.env.db.query(Connection).filter_by(workspace_id=bot.env.ws, provider="slack").one()


async def test_B_AC_91_app_uninstalled_disconnects_and_pauses(
    bot: Bot, paused: list[tuple[str, bool]]
) -> None:
    """B-AC-91"""
    await bot.event({"type": "app_uninstalled"})
    await slack_bot.drain()
    c = conn(bot)
    assert c.status == "disconnected" and c.secret_encrypted is None
    assert paused == [(bot.env.ws, True)]


async def test_B_AC_91_tokens_revoked_for_the_bot_disconnects(
    bot: Bot, paused: list[tuple[str, bool]]
) -> None:
    await bot.event({"type": "tokens_revoked", "tokens": {"oauth": ["U1"], "bot": ["UBOT"]}})
    await slack_bot.drain()
    assert conn(bot).status == "disconnected" and paused == [(bot.env.ws, True)]


async def test_tokens_revoked_for_users_only_keeps_the_connection(
    bot: Bot, paused: list[tuple[str, bool]]
) -> None:
    await bot.event({"type": "tokens_revoked", "tokens": {"oauth": ["U1"], "bot": []}})
    await slack_bot.drain()
    assert conn(bot).status == "connected" and paused == []
