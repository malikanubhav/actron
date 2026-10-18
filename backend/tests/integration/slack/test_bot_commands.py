"""Slack bot: /actron, /actron ask and mentions (B-AC-51, B-AC-53 duplicates)."""

from __future__ import annotations

import time

from actron.db.models import Request, User
from actron.integrations import slack_bot
from tests.integration.slack.slack_fixtures import Bot, status_ts_of


async def test_B_AC_51_command_acks_within_3s_creates_request_posts_ack_and_stores_ts(
    bot: Bot,
) -> None:
    """B-AC-51: the ack is measured while Slack's chat.postMessage is slow; the work happens after it."""
    bot.fake.post_delay = 1.2
    started = time.monotonic()
    resp = await bot.command("add a retry to the invoice export")
    elapsed = time.monotonic() - started
    assert resp.status_code == 200 and elapsed < 1.0, elapsed
    assert bot.flow.names() == []  # handed off, not done inline

    await slack_bot.drain()
    (call,) = bot.flow.of("create_request")
    assert call["text"] == "add a retry to the invoice export" and call["kind_hint"] is None
    assert (
        call["actor"]["slackUserId"] == bot.env.requester_slack
        and call["actor"]["surface"] == "slack"
    )
    assert call["slack"]["channel"] == "C1" and call["idempotency_key"].startswith("slack:cmd:")

    posts = bot.fake.of("chat.postMessage")
    assert len(posts) == 2
    root, ack = posts
    assert "asked Actron" in root.params["text"]
    assert ack.params["thread_ts"] == "1700000001.000100"  # the root message's ts
    assert ack.params["text"] == "On it. Investigating your request."
    assert all(
        p.token == bot.env.token for p in posts
    )  # token resolved from the stored installation

    rid = next(iter(bot.flow.views))
    assert status_ts_of(bot.env, rid) == "1700000002.000100"
    assert call["slack"]["threadTs"] == "1700000001.000100"


async def test_actor_row_is_created_on_first_contact(bot: Bot) -> None:
    new_user = "UNEW" + bot.env.tag
    await bot.command("something", user=new_user)
    await slack_bot.drain()
    bot.env.db.expire_all()
    row = bot.env.db.query(User).filter_by(slack_user_id=new_user).one()
    assert bot.flow.of("create_request")[0]["actor"]["userId"] == str(row.id)
    assert row.name == "Priya" and row.email == "p@acme.test"
    assert bot.fake.of("users.info")


async def test_ask_starts_question_mode(bot: Bot) -> None:
    await bot.command("ask why are exports Finance-only?")
    await slack_bot.drain()
    call = bot.flow.of("create_request")[0]
    assert call["kind_hint"] == "question" and call["text"] == "why are exports Finance-only?"


async def test_empty_command_gets_usage_only_to_the_user(bot: Bot) -> None:
    resp = await bot.command("   ")
    assert resp.status_code == 200
    await slack_bot.drain()
    assert bot.flow.names() == []
    (reply,) = bot.fake.of("response_url")
    assert reply.params["response_type"] == "ephemeral" and "/actron" in reply.params["text"]


async def test_B_AC_53_duplicate_command_delivery_creates_one_request(bot: Bot) -> None:
    """B-AC-53: Slack delivering the same trigger twice does nothing twice."""
    await bot.command("do it", trigger="same.1")
    await bot.command("do it", trigger="same.1")
    await slack_bot.drain()
    assert len(bot.flow.of("create_request")) == 1
    assert len(bot.fake.of("chat.postMessage")) == 2


async def test_unknown_team_is_told_to_connect(bot: Bot) -> None:
    await bot.command("do it", team="TUNKNOWN")
    await slack_bot.drain()
    assert bot.flow.names() == []


async def test_bot_not_in_channel_gets_an_invite_hint(bot: Bot) -> None:
    bot.fake.fail_post_with = "not_in_channel"
    await bot.command("do it")
    await slack_bot.drain()
    assert bot.flow.names() == []
    (reply,) = bot.fake.of("response_url")
    assert "/invite @Actron" in reply.params["text"]


async def test_app_mention_starts_a_request_in_the_mention_thread(bot: Bot) -> None:
    ev = {
        "type": "app_mention",
        "user": bot.env.requester_slack,
        "channel": "C1",
        "ts": "1699999999.000200",
        "text": "<@UBOT> add a retry to the invoice export",
    }
    r = await bot.event(ev, event_id="EvMention1")
    assert r.status_code == 200
    await bot.event(ev, event_id="EvMention1")  # Slack retry
    await slack_bot.drain()
    (call,) = bot.flow.of("create_request")
    assert call["text"] == "add a retry to the invoice export"
    assert call["slack"] == {"channel": "C1", "threadTs": "1699999999.000200"}
    (post,) = bot.fake.of("chat.postMessage")
    assert post.params["thread_ts"] == "1699999999.000200"


async def test_mention_inside_a_thread_uses_that_thread(bot: Bot) -> None:
    ev = {
        "type": "app_mention",
        "user": bot.env.requester_slack,
        "channel": "C1",
        "ts": "5.5",
        "thread_ts": "1.1",
        "text": "<@UBOT> ask what did we decide about exports?",
    }
    await bot.event(ev)
    await slack_bot.drain()
    call = bot.flow.of("create_request")[0]
    assert call["slack"]["threadTs"] == "1.1" and call["kind_hint"] == "question"


async def test_create_request_failure_is_reported_in_the_thread(bot: Bot) -> None:
    async def boom(ws, kw):  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    bot.flow.on_create = boom
    await bot.command("do it")
    await slack_bot.drain()
    texts = [p.params["text"] for p in bot.fake.of("chat.postMessage")]
    assert slack_bot.START_FAILED in texts
    assert bot.env.db.query(Request).filter_by(workspace_id=bot.env.ws).count() == 0
