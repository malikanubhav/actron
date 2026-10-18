"""Slack sender: one status message per request, questions in the thread, DMs only when someone must act."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from actron.integrations import slack_sender
from tests.integration.slack.fake_slack import FakeSlack
from tests.integration.slack.slack_fixtures import FakeFlow, status_ts_of
from tests.unit.slack.views import make_view


def env_(rid: str, typ: str, seq: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": seq,
        "requestId": rid,
        "seq": seq,
        "type": typ,
        "at": "2026-10-18T09:00:00Z",
        "actor": "actron",
        "surface": "system",
        "payload": payload or {},
    }


def state_changed(rid: str, frm: str, to: str, seq: int) -> dict[str, Any]:
    return env_(rid, "request.state_changed", seq, {"from": frm, "to": to, "reason": "test"})


async def test_B_AC_52_status_posted_once_then_updated(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    """B-AC-52: first event posts in the thread and stores the ts; later changes use chat.update."""
    rid, view = ws_env.make_request("Investigating")
    flow.views[rid] = view
    await slack_sender.on_event(ws_env.ws, env_(rid, "request.created", 1))
    posts = fake_slack.of("chat.postMessage")
    assert len(posts) == 1 and posts[0].params["thread_ts"] == "1700000000.000100"
    assert posts[0].token == ws_env.token
    assert (
        posts[0].params["text"] == "On it. Investigating your request."
    )  # the acknowledgement comes first
    ts = status_ts_of(ws_env, rid)
    assert ts

    flow.views[rid] = make_view("Building", id=rid)
    await slack_sender.on_event(ws_env.ws, state_changed(rid, "Awaiting approval", "Building", 2))
    flow.views[rid] = make_view("Building", id=rid, headline="Building. 5 of 14 tests passed.")
    await slack_sender.on_event(ws_env.ws, env_(rid, "tests.result", 3))
    assert len(fake_slack.of("chat.postMessage")) == 1
    updates = fake_slack.of("chat.update")
    assert len(updates) == 2 and all(u.params["ts"] == ts for u in updates)
    assert "5 of 14" in str(updates[-1].params["attachments"])


async def test_unchanged_message_is_not_resent(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, view = ws_env.make_request("Building")
    flow.views[rid] = view
    for seq in (1, 2, 3):
        await slack_sender.on_event(ws_env.ws, env_(rid, "build.started", seq))
    assert len(fake_slack.of("chat.postMessage")) == 1 and fake_slack.of("chat.update") == []


async def test_chatty_events_do_nothing(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, view = ws_env.make_request("Investigating")
    flow.views[rid] = view
    for typ in ("tool.called", "tool.result", "evidence.found", "build.step", "judgment.made"):
        await slack_sender.on_event(ws_env.ws, env_(rid, typ, 1))
    assert fake_slack.calls == []


async def test_lost_status_message_is_reposted(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, view = ws_env.make_request("Building", status_ts="1.1")
    flow.views[rid] = view
    fake_slack.fail_update_with = "message_not_found"
    await slack_sender.on_event(ws_env.ws, env_(rid, "build.started", 1))
    assert len(fake_slack.of("chat.postMessage")) == 1
    assert status_ts_of(ws_env, rid) != "1.1"


async def test_noop_when_slack_not_connected(
    fake_slack: FakeSlack, db_session: Any, redis_client: Any, flow: FakeFlow
) -> None:
    await slack_sender.on_event("no-such-workspace", env_("req_x", "request.created", 1))
    assert fake_slack.calls == []


async def test_errors_are_swallowed(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, _ = ws_env.make_request("Investigating")  # the flow has no view: get_request_view raises
    await slack_sender.on_event(ws_env.ws, env_(rid, "request.created", 1))


async def test_B_AC_90_token_from_stored_connection_without_env_token(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    """B-AC-90: no SLACK_BOT_TOKEN is set; the stored installation's token is used."""
    rid, view = ws_env.make_request("Investigating")
    flow.views[rid] = view
    await slack_sender.on_event(ws_env.ws, env_(rid, "request.created", 1))
    assert {c.token for c in fake_slack.calls} == {ws_env.token}


async def test_question_posted_in_thread_with_buttons_and_updated_when_answered(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, view = ws_env.make_request("Needs your input")
    flow.views[rid] = view
    await slack_sender.on_event(ws_env.ws, env_(rid, "question.asked", 1, {"questionId": "q1"}))
    await slack_sender.on_event(
        ws_env.ws, env_(rid, "question.asked", 2, {"questionId": "q1"})
    )  # duplicate
    posts = fake_slack.of("chat.postMessage")
    assert len(posts) == 2  # status message plus one question
    q = posts[1].params
    assert q["thread_ts"] == "1700000000.000100" and f"answer:{rid}:q1:yes" in str(q["blocks"])
    assert f"<@{ws_env.requester_slack}>" in str(q["blocks"])

    answered = make_view("Needs your input", id=rid)
    answered["questions"][0]["answer"] = {
        "value": "yes",
        "by": {"name": "Priya"},
        "surface": "slack",
        "at": "x",
    }
    flow.views[rid] = answered
    await slack_sender.on_event(ws_env.ws, env_(rid, "answer.received", 3, {"questionId": "q1"}))
    upd = [u for u in fake_slack.of("chat.update") if "Answered" in str(u.params)]
    assert upd and "answer:" not in str(upd[0].params["blocks"])


async def test_B_AC_56_dm_only_to_the_person_who_must_act(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    """B-AC-56: DMs for the four interrupts go to the requester (and approvers for approvals); never otherwise."""
    rid, _ = ws_env.make_request("Investigating")
    seq = 0

    async def go(frm: str, to: str) -> list[str]:
        nonlocal seq
        seq += 1
        flow.views[rid] = make_view(
            to,
            id=rid,
            slack={
                "channel": "C1",
                "threadTs": "1700000000.000100",
                "permalink": "https://acme.slack.com/archives/C1/p1",
            },
        )
        before = len(fake_slack.of("conversations.open"))
        await slack_sender.on_event(ws_env.ws, state_changed(rid, frm, to, seq))
        return [c.params["users"] for c in fake_slack.of("conversations.open")[before:]]

    assert await go("Investigating", "Needs your input") == [ws_env.requester_slack]
    assert await go("Needs your input", "Ticket ready") == []
    assert await go("Ticket ready", "Awaiting approval") == [
        ws_env.requester_slack,
        ws_env.approver_slack,
    ]
    assert await go("Awaiting approval", "Building") == []
    assert await go("Building", "Needs attention") == [ws_env.requester_slack]
    assert await go("Needs attention", "Building") == []
    assert await go("Building", "PR ready for review") == [
        ws_env.requester_slack,
        ws_env.approver_slack,
    ]
    assert await go("PR ready for review", "Done") == []
    assert await go("Done", "Done") == []

    dms = [c for c in fake_slack.of("chat.postMessage") if str(c.params["channel"]).startswith("D")]
    assert {c.params["channel"] for c in dms} == {
        "D" + ws_env.requester_slack,
        "D" + ws_env.approver_slack,
    }
    assert all(len(c.params["blocks"]) == 1 for c in dms)  # one sentence and a link
    assert all("https://acme.slack.com/archives/C1/p1" in str(c.params["blocks"]) for c in dms)


async def test_B_AC_56_duplicate_delivery_sends_one_dm(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, view = ws_env.make_request("Needs attention")
    flow.views[rid] = view
    for _ in range(2):
        await slack_sender.on_event(ws_env.ws, state_changed(rid, "Building", "Needs attention", 7))
    assert len(fake_slack.of("conversations.open")) == 1


async def test_pr_ready_posts_build_finished_in_thread(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, _ = ws_env.make_request("Building")
    flow.views[rid] = make_view("PR ready for review", id=rid)
    await slack_sender.on_event(ws_env.ws, state_changed(rid, "Building", "PR ready for review", 4))
    threads = [c for c in fake_slack.of("chat.postMessage") if c.params.get("thread_ts")]
    assert any(
        c.params["text"] == "PR #18 is ready for review. 14 of 14 tests passed." for c in threads
    )


async def test_ui_request_without_thread_gets_dm_but_no_status(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, _ = ws_env.make_request("Investigating", channel=None, thread_ts=None)
    flow.views[rid] = make_view("Needs your input", id=rid)
    await slack_sender.on_event(
        ws_env.ws, state_changed(rid, "Investigating", "Needs your input", 1)
    )
    assert len(fake_slack.of("conversations.open")) == 1
    assert [
        c for c in fake_slack.of("chat.postMessage") if not str(c.params["channel"]).startswith("D")
    ] == []


async def test_qa_answer_posted_in_thread(
    fake_slack: FakeSlack, ws_env: SimpleNamespace, flow: FakeFlow
) -> None:
    rid, _ = ws_env.make_request("Investigating")
    flow.views[rid] = make_view(
        "Done", id=rid, answer={"text": "Finance-only since March.", "citations": []}
    )
    await slack_sender.on_event(ws_env.ws, env_(rid, "answer.ready", 5, {"answerRef": "x"}))
    assert any(
        c.params["text"] == "Finance-only since March." for c in fake_slack.of("chat.postMessage")
    )
