# ruff: noqa: F403, F405
"""Slack mapping and incremental catch-up against the fake server: A-AC-50, 52, 55."""

from __future__ import annotations

from typing import Any

from actron.connectors import slack
from actron.graph import ids
from tests.fakes.slack import FakeSlack
from tests.fakes.support import *


def _config(**extra: Any) -> dict[str, Any]:
    return {"token": "xoxb-test-token", "api_url": "http://fake.slack/api/", "history_days": 3650, **extra}


def _rows(store: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    return store.query(cypher, params, read_only=True)


def _seed(fake: FakeSlack) -> dict[str, str]:
    fake.add_user("U1", "ada", "Ada Lovelace", email="ada@example.com", title="Engineer")
    fake.add_user("U2", "bob", "Bob", email="bob@example.com")
    fake.add_user("U3", "gone", "Gone", deleted=True)
    fake.add_channel("C1", "eng", members=["U1", "U2", "UBOT"], topic="Engineering", purpose="Build things")
    fake.add_channel("C2", "random", is_member=False, members=["U1"])
    ts = {}
    for i in range(205):  # two history pages (limit 200)
        ts[f"m{i}"] = fake.add_message("C1", f"message {i}", user="U1" if i % 2 else "U2")
    ts["parent"] = fake.add_message("C1", "Should we retry? <@U2>", user="U1",
                                    reactions=[{"name": "eyes", "count": 1, "users": ["U2"]}],
                                    files=[{"id": "F1", "name": "spec.pdf", "mimetype": "application/pdf"}])
    ts["r1"] = fake.add_message("C1", "yes, with backoff", user="U2", thread_ts=ts["parent"])
    ts["r2"] = fake.add_message("C1", "agreed", user="U1", thread_ts=ts["parent"])
    ts["bot"] = fake.add_message("C1", "Status: working on it", user="UBOT", bot_id="BBOT")
    return ts


async def test_a_ac_50_users_channels_members_history_replies_reactions_files(fake_slack: FakeSlack, store: Any,
                                                                            ws: str) -> None:
    """A-AC-50"""
    ts = _seed(fake_slack)
    run = await drive(slack, ws, _config(channels=["C1"]))
    n = store.count
    assert n("SlackWorkspace") == 1 and n("SlackChannel") == 1
    assert n("SlackUser") == 4  # ada, bob, gone, actron
    assert n("SlackMessage") == 205 + 1 + 2 + 1
    assert n("SlackReaction") == 1 and n("SlackFile") == 1
    ws_node = store.get_node(ids.slack_workspace("T0001"))
    assert ws_node["domain"] == "northwind" and ws_node["name"] == "Northwind Labs"
    ada = store.get_node(ids.slack_user("U1"))
    assert ada["realName"] == "Ada Lovelace" and ada["email"] == "ada@example.com" and ada["isBot"] is False
    assert store.get_node(ids.slack_user("U3"))["isDeleted"] is True
    chan = store.get_node(ids.slack_channel("C1"))
    assert chan["name"] == "eng" and chan["topic"] == "Engineering" and chan["isPrivate"] is False
    parent = store.get_node(ids.slack_msg("C1", ts["parent"]))
    assert parent["text"] == "Should we retry? <@U2>" and parent["replyCount"] == 2
    assert parent["version"] == 1 and parent["userId"] == "U1" and parent["name"].startswith("Should we retry")
    assert parent["permalink"] == f"https://northwind.slack.com/archives/C1/p{ts['parent'].replace('.', '')}"
    assert parent["postedAt"].endswith("Z")

    def edge(rel: str, a: str, b: str) -> int:
        return int(_rows(store, f"MATCH (a:{a})-[r:{rel}]->(b:{b}) RETURN count(r) AS c")[0]["c"])

    assert edge("RELATED_TO_CHANNEL", "SlackMessage", "SlackChannel") == 209
    assert edge("RELATED_TO", "SlackMessage", "SlackWorkspace") == 209
    assert edge("POSTED_BY", "SlackMessage", "SlackUser") == 209
    assert edge("THREAD_OF", "SlackMessage", "SlackMessage") == 2
    assert edge("RELATED_TO_REACTION", "SlackMessage", "SlackReaction") == 1
    assert edge("RELATED_TO_FILE", "SlackMessage", "SlackFile") == 1
    assert edge("RELATED_TO_CHANNEL", "SlackUser", "SlackChannel") == 3
    assert edge("RELATED_TO", "SlackUser", "SlackWorkspace") == 4
    assert edge("RELATED_TO", "SlackChannel", "SlackWorkspace") == 1
    # history came in two pages, with a cursor per channel
    assert len(fake_slack.calls_to("conversations.history")) == 2
    assert run.cursor["channels"]["C1"]["oldest"] == ts["bot"]
    reply = store.get_node(ids.slack_msg("C1", ts["r1"]))
    assert reply["threadTs"] == ts["parent"]


async def test_a_ac_56_bot_and_actron_messages_are_tagged(fake_slack: FakeSlack, store: Any, ws: str) -> None:
    """A-AC-56 (ingestion side): bot messages carry botId and subtype bot_message; Actron's own are tagged too."""
    ts = _seed(fake_slack)
    fake_slack.add_message("C1", "Posted by Actron without a bot id", user="UBOT")
    await drive(slack, ws, _config(channels=["C1"]))
    bot = store.get_node(ids.slack_msg("C1", ts["bot"]))
    assert bot["botId"] == "BBOT" and bot["subtype"] == "bot_message" and bot["userId"] == "UBOT"
    own = _rows(store, "MATCH (m:SlackMessage) WHERE m.text STARTS WITH 'Posted by Actron' RETURN m.subtype AS s")
    assert own == [{"s": "bot_message"}]
    humans = _rows(store, "MATCH (m:SlackMessage) WHERE m.subtype IS NULL RETURN count(m) AS c")
    assert humans[0]["c"] == 205 + 1 + 2


async def test_a_ac_55_only_allowed_channels_are_read_and_skips_are_listed(fake_slack: FakeSlack, store: Any,
                                                                         ws: str) -> None:
    """A-AC-55"""
    _seed(fake_slack)
    fake_slack.add_channel("C3", "ops", members=["U1"])
    fake_slack.add_message("C3", "ops message", user="U1")
    run = await drive(slack, ws, _config(channels=["C1", "random"]))  # random: the bot is not a member
    assert {r["id"] for r in _rows(store, "MATCH (c:SlackChannel) RETURN c.id AS id")} == {"slack:channel:C1"}
    assert any(e["action"] == "skip_channel" and "random" in e["error"] for e in run.errors)
    assert not any(c["channel"] in ("C2", "C3") for c in fake_slack.calls_to("conversations.history"))
    # without a list, every channel the bot is in is read
    await drive(slack, ws, _config(channels=[]), steps=["workspace", "users", "channels"])
    assert {r["id"] for r in _rows(store, "MATCH (c:SlackChannel) RETURN c.id AS id")} == {
        "slack:channel:C1", "slack:channel:C3"}


async def test_a_ac_52_incremental_catchup_processes_only_new_and_edited(fake_slack: FakeSlack, store: Any,
                                                                       ws: str) -> None:
    """A-AC-52: after new messages and an edit, only those are written; the per-channel cursor advances."""
    ts = _seed(fake_slack)
    first = await drive(slack, ws, _config(channels=["C1"]))
    old_oldest = first.cursor["channels"]["C1"]["oldest"]
    new1 = fake_slack.add_message("C1", "fresh one", user="U1")
    new2 = fake_slack.add_message("C1", "fresh two", user="U2")
    fake_slack.edit_message("C1", ts["bot"], "Status: finished")
    second = await drive(slack, ws, _config(channels=["C1"]), cursor=first.cursor)
    assert second.counts["SlackMessage"] == 3  # two new, one edited
    assert sorted(second.changed) == sorted(
        [ids.slack_msg("C1", new1), ids.slack_msg("C1", new2), ids.slack_msg("C1", ts["bot"])])
    assert float(second.cursor["channels"]["C1"]["oldest"]) > float(old_oldest)
    assert second.cursor["channels"]["C1"]["oldest"] == new2
    edited = store.get_node(ids.slack_msg("C1", ts["bot"]))
    assert edited["text"] == "Status: finished" and edited["version"] == 2 and edited["edited"] is True
    prev = store.get_node(ids.slack_msg("C1", ts["bot"]) + "@v1")
    assert prev is not None and prev["text"] == "Status: working on it"
    total = store.count("SlackMessage")
    third = await drive(slack, ws, _config(channels=["C1"]), cursor=second.cursor)
    assert third.counts.get("SlackMessage", 0) == 0 and store.count("SlackMessage") == total


async def test_new_replies_on_an_existing_thread_are_picked_up(fake_slack: FakeSlack, store: Any, ws: str) -> None:
    ts = _seed(fake_slack)
    first = await drive(slack, ws, _config(channels=["C1"]))
    late = fake_slack.add_message("C1", "one more reply", user="U2", thread_ts=ts["parent"])
    second = await drive(slack, ws, _config(channels=["C1"]), cursor=first.cursor)
    assert store.get_node(ids.slack_msg("C1", late)) is not None
    assert store.get_node(ids.slack_msg("C1", ts["parent"]))["replyCount"] == 3
    assert ids.slack_msg("C1", late) in second.changed


async def test_new_reaction_on_an_unchanged_message_is_stored(fake_slack: FakeSlack, store: Any, ws: str) -> None:
    ts = _seed(fake_slack)
    first = await drive(slack, ws, _config(channels=["C1"]))
    fake_slack.find("C1", ts["parent"])["reactions"].append({"name": "tada", "count": 1, "users": ["U1"]})
    await drive(slack, ws, _config(channels=["C1"]), cursor=first.cursor)
    names = {r["n"] for r in _rows(store, "MATCH (:SlackMessage)-[:RELATED_TO_REACTION]->(r:SlackReaction) "
                                    "RETURN r.name AS n")}
    assert names == {"eyes", "tada"}
