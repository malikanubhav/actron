# ruff: noqa: F403, F405
"""Slack export import (A-AC-89, A-AC-90, A-AC-91 import side). The export below is synthetic."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from actron.connectors import slack_export
from actron.graph import ids
from tests.fakes.support import *

U = [
    {"id": "U1", "team_id": "T9", "name": "ada", "real_name": "Ada", "profile": {"email": "ada@example.com",
                                                                            "display_name": "ada"}},
    {"id": "U2", "team_id": "T9", "name": "bob", "real_name": "Bob", "profile": {}},  # no email
]
CHANNELS = [
    {"id": "C1", "name": "eng", "created": 1700000000, "members": ["U1", "U2"], "topic": {"value": "Eng"},
     "purpose": {"value": "Build"}, "original_id": "C0OLD1"},
    {"id": "C2", "name": "ops", "created": 1700000100, "members": ["U1"], "is_archived": True},
]


def _msg(ts: str, text: str, user: str = "U1", **extra: Any) -> dict[str, Any]:
    return {"type": "message", "user": user, "text": text, "ts": ts, "team": "T9", **extra}


def build_export(root: Path) -> Path:
    (root / "eng").mkdir(parents=True)
    (root / "ops").mkdir()
    (root / "users.json").write_text(json.dumps(U))
    (root / "channels.json").write_text(json.dumps(CHANNELS))
    (root / "eng" / "2024-01-10.json").write_text(json.dumps([
        _msg("1704880000.000100", "Should we retry? <@U2>", reply_count=2, latest_reply="1704880200.000100",
             thread_ts="1704880000.000100",
             reactions=[{"name": "eyes", "users": ["U2"], "count": 1}],
             files=[{"id": "F1", "name": "spec.pdf", "mimetype": "application/pdf"}]),
        _msg("1704880100.000100", "yes, with backoff", "U2", thread_ts="1704880000.000100"),
        _msg("1704880200.000100", "agreed", "U1", thread_ts="1704880000.000100"),
        _msg("1704880300.000100", "build is green", "U2", subtype="bot_message", bot_id="B1"),
        {"type": "message", "subtype": "tombstone", "ts": "1704880400.000100", "text": "This message was deleted.",
         "hidden": True},
    ]))
    (root / "eng" / "2024-01-11.json").write_text(json.dumps([
        _msg("1704966400.000100", "We decided to use exponential backoff."),
    ]))
    (root / "ops" / "2024-01-10.json").write_text(json.dumps([
        _msg("1704880500.000100", "deploy at noon"),
        {"type": "message", "subtype": "message_deleted", "deleted_ts": "1704880500.000100",
         "ts": "1704880600.000100"},
    ]))
    return root


def _rows(store: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    return store.query(cypher, params, read_only=True)


async def test_a_ac_89_export_imports_into_documented_nodes_and_links_and_reimport_creates_nothing(
        store: Any, ws: str, tmp_path: Path) -> None:
    """A-AC-89"""
    root = build_export(tmp_path / "export")
    config = {"path": str(root)}
    first = await drive(slack_export, ws, config)
    n = store.count
    assert n("SlackWorkspace") == 1 and store.get_node(ids.slack_workspace("T9")) is not None
    assert n("SlackUser") == 2 and n("SlackChannel") == 2
    # eng: 5 messages in day 1 minus nothing (tombstone placeholder kept) + 1; ops: deleted message tombstoned
    eng_msgs = _rows(store, "MATCH (m:SlackMessage {channelId: 'C1'}) RETURN count(m) AS c")[0]["c"]
    assert eng_msgs == 6
    assert n("SlackReaction") == 1 and n("SlackFile") == 1
    chan = store.get_node(ids.slack_channel("C1"))
    assert chan["aliases"] == ["C0OLD1"] and chan["topic"] == "Eng"
    assert store.get_node(ids.slack_channel("C2"))["isArchived"] is True
    ada = store.get_node(ids.slack_user("U1"))
    assert ada["email"] == "ada@example.com"
    assert store.get_node(ids.slack_user("U2")).get("email") is None  # stays identity-unresolved
    parent = store.get_node(ids.slack_msg("C1", "1704880000.000100"))
    assert parent["replyCount"] == 2 and parent["postedAt"].startswith("2024-01-10")
    threads = _rows(store, "MATCH (r:SlackMessage)-[:THREAD_OF]->(p:SlackMessage) RETURN count(r) AS c")[0]["c"]
    assert threads == 2
    bot = store.get_node(ids.slack_msg("C1", "1704880300.000100"))
    assert bot["subtype"] == "bot_message" and bot["botId"] == "B1"
    tomb = store.get_node(ids.slack_msg("C1", "1704880400.000100"))
    assert tomb is not None and tomb["deleted"] is True
    gone = store.get_node(ids.slack_msg("C2", "1704880500.000100"))
    assert gone is not None and gone["deleted"] is True
    members = _rows(store, "MATCH (:SlackUser)-[r:RELATED_TO_CHANNEL]->(:SlackChannel) RETURN count(r) AS c")[0]["c"]
    assert members == 3
    assert first.counts["SlackMessage"] >= 8

    before = store.count()
    second = await drive(slack_export, ws, config, cursor=first.cursor)
    assert store.count() == before
    assert second.counts.get("SlackMessage", 0) == 0 and not second.changed


async def test_later_export_with_more_days_imports_only_the_new_messages(store: Any, ws: str, tmp_path: Path) -> None:
    root = build_export(tmp_path / "export")
    first = await drive(slack_export, ws, {"path": str(root)})
    (root / "eng" / "2024-01-12.json").write_text(json.dumps([_msg("1705052800.000100", "a new day")]))
    # the first day file also gained a message (a later export of the same day)
    day1 = json.loads((root / "eng" / "2024-01-11.json").read_text())
    day1.append(_msg("1704966500.000100", "late addition"))
    (root / "eng" / "2024-01-11.json").write_text(json.dumps(day1))
    slack_export._ROOTS.clear()
    second = await drive(slack_export, ws, {"path": str(root)}, cursor=first.cursor)
    assert second.counts["SlackMessage"] == 2
    assert sorted(second.changed) == [ids.slack_msg("C1", "1704966500.000100"), ids.slack_msg("C1", "1705052800.000100")]


async def test_a_ac_90_events_jsonl_edits_and_deletes_match_live_events(store: Any, ws: str, tmp_path: Path) -> None:
    """A-AC-90"""
    root = build_export(tmp_path / "export")
    events = [
        {"type": "message", "subtype": "message_changed", "channel": "C1", "ts": "1705100000.000100",
         "message": {"type": "message", "user": "U1", "text": "Should we retry twice? <@U2>",
                     "ts": "1704880000.000100", "edited": {"user": "U1", "ts": "1705100000.000100"}}},
        {"event": {"type": "message", "subtype": "message_deleted", "channel": "eng",  # by name, as converted archives do
                   "deleted_ts": "1704880300.000100"}},
        {"type": "event_callback", "event": {"type": "message", "channel": "C1", "user": "U2", "text": "after the fact",
                                             "ts": "1705100100.000100"}},
    ]
    (root / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    run = await drive(slack_export, ws, {"path": str(root)})
    mid = ids.slack_msg("C1", "1704880000.000100")
    node = store.get_node(mid)
    assert node["text"] == "Should we retry twice? <@U2>" and node["version"] == 2
    assert store.get_node(mid + "@v1")["text"] == "Should we retry? <@U2>"
    assert store.get_node(ids.slack_msg("C1", "1704880300.000100"))["deleted"] is True
    assert store.get_node(ids.slack_msg("C1", "1705100100.000100"))["text"] == "after the fact"
    assert run.cursor["events_offset"] == 3
    again = await drive(slack_export, ws, {"path": str(root)}, cursor=run.cursor)
    assert store.get_node(mid)["version"] == 2 and again.counts.get("events", 0) == 0


async def test_a_ac_91_zip_is_validated_extracted_and_imported(store: Any, ws: str, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """A-AC-91 (connector side): a zip goes through validation and is extracted under the clone dir."""
    from actron.config import get_settings

    monkeypatch.setenv("ACTRON_CLONE_DIR", str(tmp_path / "clones"))
    get_settings.cache_clear()
    root = build_export(tmp_path / "export")
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
    slack_export._ROOTS.clear()
    run = await drive(slack_export, ws, {"path": str(z)})
    assert store.count("SlackMessage") == 7
    assert (tmp_path / "clones" / ws / "slack_export").is_dir()
    assert run.cursor["workspace"]["id"] == "T9"
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.json", "[]")
        zf.writestr("eng/2024-01-01.json", "[]")
    slack_export._ROOTS.clear()
    with pytest.raises(slack_export.ExportValidationError):
        await drive(slack_export, ws, {"path": str(bad)})
    get_settings.cache_clear()


async def test_export_without_team_field_uses_a_path_hash(store: Any, ws: str, tmp_path: Path) -> None:
    root = tmp_path / "plain"
    (root / "dev").mkdir(parents=True)
    (root / "dev" / "2024-02-01.json").write_text(json.dumps([{"type": "message", "user": "U1", "text": "hi",
                                                                "ts": "1706745600.000100"}]))
    await drive(slack_export, ws, {"path": str(root)})
    wid = _rows(store, "MATCH (w:SlackWorkspace) RETURN w.id AS id")[0]["id"]
    assert wid.startswith("slack:workspace:export-")
    assert store.count("SlackMessage") == 1


async def test_run_import_helper_for_the_cli(store: Any, ws: str, tmp_path: Path) -> None:
    root = build_export(tmp_path / "export")
    counts, cursor = await slack_export.run_import(ws, {"path": str(root)})
    assert counts["SlackMessage"] >= 8 and cursor["workspace"]["id"] == "T9"
