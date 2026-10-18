"""Block Kit builders: snapshots per state and message type, limits, actions (B-AC-52, C-AC-10, C-AC-35)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from actron.config import REPO_ROOT
from actron.integrations import slack_blocks as sb

from .views import HASH, RID, SHA, make_view

SNAP = Path(__file__).parent / "snapshots"
NOW = datetime(2026, 10, 18, 9, 3, 0, tzinfo=UTC)
STATES = [
    "Investigating",
    "Needs your input",
    "Ticket ready",
    "Awaiting approval",
    "Building",
    "Needs attention",
    "PR ready for review",
    "Changes requested",
    "Done",
    "Cancelled",
]


def check_snapshot(name: str, payload: Any) -> None:
    path = SNAP / f"{name}.json"
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or (
        not path.exists() and os.environ.get("UPDATE_SNAPSHOTS") == "new"
    ):
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(text), (
        f"snapshot {name} changed"
    )


def all_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
    out = list(msg.get("blocks") or [])
    for a in msg.get("attachments") or []:
        out.extend(a["blocks"])
    return out


def action_ids(msg: dict[str, Any]) -> list[str]:
    return [
        e["action_id"] for b in all_blocks(msg) if b["type"] == "actions" for e in b["elements"]
    ]


def labels(msg: dict[str, Any]) -> list[str]:
    return [
        e["text"]["text"]
        for b in all_blocks(msg)
        if b["type"] == "actions"
        for e in b["elements"]
        if e["type"] == "button"
    ]


@pytest.mark.parametrize("state", STATES)
def test_B_AC_52_status_snapshot_per_state(state: str) -> None:
    """B-AC-52, C-AC-35: status message blocks for every state, valid and snapshot-stable."""
    msg = sb.status_message(make_view(state), now=NOW)
    assert sb.validate_message(msg) == []
    check_snapshot("status_" + state.lower().replace(" ", "_"), msg)


def test_C_AC_35_snapshots_of_other_message_types() -> None:
    pr = make_view("PR ready for review")
    cases = {
        "ack": sb.acknowledgement(make_view("Investigating")),
        "approval_confirmation": sb.approval_confirmation(
            make_view("Building"), "Maya", "ticket", "slack", now=NOW
        ),
        "needs_you_dm_input": sb.needs_you_dm(
            make_view("Needs your input"),
            "needs_input",
            thread_url="https://acme.slack.com/archives/C1/p1",
        ),
        "needs_you_dm_ticket": sb.needs_you_dm(make_view("Awaiting approval"), "ticket"),
        "needs_you_thread": sb.needs_you_thread(make_view("Awaiting approval"), "ticket", "U1"),
        "build_finished": sb.build_finished(pr),
        "failure": sb.failure(make_view("Needs attention")),
        "question_choice": sb.question_message(
            make_view("Needs your input"), make_view("Needs your input")["questions"][0], 1, 3, "U1"
        ),
        "question_select": sb.question_message(
            make_view("Needs your input"), make_view("Needs your input")["questions"][1], 2, 3
        ),
        "question_text": sb.question_message(
            make_view("Needs your input"), make_view("Needs your input")["questions"][2], 3, 3
        ),
        "answer_qa": sb.answer_message(
            make_view(
                "Done",
                answer={
                    "text": "Exports are Finance-only since March.",
                    "citations": [make_view("Needs your input")["evidence"][1]],
                },
            )
        ),
        "modal": sb.request_changes_modal(RID, pr_number=18),
    }
    for name, msg in cases.items():
        errs = sb.validate_view(msg) if name == "modal" else sb.validate_message(msg)
        assert errs == [], (name, errs)
        check_snapshot(name, msg)


def test_header_context_and_headline() -> None:
    msg = sb.status_message(make_view("Building"), now=NOW)
    blocks = all_blocks(msg)
    assert blocks[0] == {
        "type": "header",
        "text": {"type": "plain_text", "text": "Export invoices as CSV"},
    }
    assert blocks[1]["elements"][0]["text"] == "STATE · BUILDING · 3m"
    assert blocks[2]["text"]["text"] == "Building. 3 of 14 tests passed."


def test_elapsed_text() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    f = lambda s: sb.elapsed_text(t0, datetime.fromtimestamp(t0.timestamp() + s, UTC))  # noqa: E731
    assert [f(5), f(125), f(3700), f(90000)] == ["5s", "2m", "1h 1m", "1d 1h"]


def test_evidence_at_most_three_quotes_with_source_and_author() -> None:
    msg = sb.status_message(make_view("Needs your input"), now=NOW)
    blocks = all_blocks(msg)
    quotes = [b for b in blocks if b["type"] == "section" and b["text"]["text"].startswith(">")]
    assert len(quotes) == 3
    # conflict first, special characters escaped
    assert "Finance-only" in quotes[0]["text"]["text"]
    assert "&lt;yet&gt; &amp; later" in quotes[0]["text"]["text"]
    ctx = [b["elements"][0]["text"] for b in blocks if b["type"] == "context"]
    assert "<https://acme.slack.com/archives/C1/p11|Slack message> · Maya" in ctx
    assert "LABEL · CONFLICT" in ctx


def test_answer_buttons_use_documented_action_ids() -> None:
    msg = sb.status_message(make_view("Needs your input"), now=NOW)
    ids = action_ids(msg)
    assert f"answer:{RID}:q1:yes" in ids and f"answer:{RID}:q1:no" in ids
    assert f"open:{RID}" in ids


def test_many_options_use_a_menu_and_text_questions_get_a_reply_hint() -> None:
    view = make_view("Needs your input")
    sel = sb.answer_controls(view, view["questions"][1])[0]["elements"][0]
    assert (
        sel["type"] == "static_select" and sel["action_id"] == f"answer:{RID}:target_branch:~select"
    )
    msg = sb.question_message(view, view["questions"][2], 3, 3)
    assert "Reply in this thread starting with 3." in msg["blocks"][0]["text"]["text"]


def test_long_answer_value_falls_back_to_option_index() -> None:
    aid = sb.answer_action_id(RID, "q1", "x" * 300, 4)
    assert aid == f"answer:{RID}:q1:#4"


def test_approve_ticket_button_carries_hash_and_revision() -> None:
    msg = sb.status_message(make_view("Awaiting approval"), now=NOW)
    assert f"approve_ticket:{RID}:{HASH}" in action_ids(msg)
    assert "Approve ticket v2" in labels(msg)
    assert not any(a.startswith("request_changes") for a in action_ids(msg))


def test_approve_pr_button_names_head_and_confirms() -> None:
    msg = sb.status_message(make_view("PR ready for review"), now=NOW)
    btn = next(
        e
        for b in all_blocks(msg)
        if b["type"] == "actions"
        for e in b["elements"]
        if e["action_id"].startswith("approve_pr")
    )
    assert btn["action_id"] == f"approve_pr:{RID}:{SHA}"
    assert btn["text"]["text"] == "Approve PR #18 (head 3f2a1c9)"
    assert "3f2a1c9" in btn["confirm"]["text"]["text"]
    ids = action_ids(msg)
    assert f"request_changes:{RID}" in ids and f"close_pr:{RID}" in ids
    assert "Review in Actron" in labels(msg) and "Open PR" in labels(msg)


def test_retry_only_when_allowed() -> None:
    assert f"retry:{RID}" in action_ids(sb.status_message(make_view("Needs attention"), now=NOW))
    v = make_view("Needs attention", allowedActions=["cancel"])
    assert f"retry:{RID}" not in action_ids(sb.status_message(v, now=NOW))


def test_approval_confirmation_has_no_approve_button() -> None:
    msg = sb.approval_confirmation(make_view("Building"), "Maya", "ticket", "slack", now=NOW)
    assert "Approved by Maya in Slack. Build started." in json.dumps(msg)
    assert not any(a.startswith("approve") for a in action_ids(msg))
    # the Building status keeps the same line, derived from the approvals
    assert "Approved by Maya in Slack. Build started." in json.dumps(
        sb.status_message(make_view("Building"), now=NOW)
    )


def test_build_finished_and_failure_wording() -> None:
    bf = sb.build_finished(make_view("PR ready for review"))
    assert bf["text"] == "PR #18 is ready for review. 14 of 14 tests passed."
    fail = sb.failure(make_view("Needs attention"))
    assert fail["text"] == "The build failed twice. The change would have weakened existing tests."


def test_needs_you_dm_is_one_sentence_and_a_link() -> None:
    dm = sb.needs_you_dm(make_view("Awaiting approval"), "ticket", thread_url="https://t/x")
    assert dm["text"] == "Ticket v2 for Export invoices as CSV is ready for your approval."
    assert (
        len(dm["blocks"]) == 1
        and "<https://t/x|Open the thread>" in dm["blocks"][0]["text"]["text"]
    )


def test_refusal_messages_cover_documented_reasons() -> None:
    for reason in (
        "stale_revision",
        "stale_head",
        "external_edit",
        "invalid_transition",
        "not_an_approver",
    ):
        assert sb.refusal_text(reason) != sb.refusal_text(None)


def test_C_AC_10_states_json_shared_with_frontend() -> None:
    """C-AC-10: the Slack map and the UI map agree on names, text and colours."""
    front = json.loads((REPO_ROOT / "frontend" / "lib" / "states.json").read_text())
    m = sb.state_map()
    assert set(m["requestStates"]) == set(front["requestStates"])
    for name, entry in front["requestStates"].items():
        assert sb.state_text(name) == entry["text"]
        assert sb.state_color(name) == front["tones"][entry["tone"]]["hex"]
    assert sb.label_text("possible_conflict") == front["labels"]["possible_conflict"]["text"]
    backend = REPO_ROOT / "backend" / "actron" / "flow" / "states.json"
    if backend.exists():
        data = json.loads(backend.read_text())
        assert data["tones"] == {
            k: {"token": v["token"], "hex": v["hex"]} for k, v in front["tones"].items()
        }
        assert set(data["requestStates"]) == set(front["requestStates"])
        for name, entry in data["requestStates"].items():
            f = front["requestStates"][name]
            assert (entry.get("text") or entry["slackLabel"]) == f["text"]
            assert entry["tone"] == f["tone"]
            assert entry["needsYou"] == f["needsYou"] and entry["final"] == f["final"]


def test_validator_catches_limit_violations() -> None:
    long = "x" * 3001
    assert sb.validate_blocks([{"type": "section", "text": {"type": "mrkdwn", "text": long}}])
    assert sb.validate_blocks([sb.header("h")] * 51)
    bad_header = {"type": "header", "text": {"type": "plain_text", "text": "h" * 151}}
    assert sb.validate_blocks([bad_header])
    btn = {"type": "button", "text": {"type": "plain_text", "text": "b" * 76}, "action_id": "a"}
    assert sb.validate_blocks([sb.actions("x", [btn])])
    dup = sb.actions("x", [sb.button("a", "same"), sb.button("b", "same")])
    assert sb.validate_blocks([dup])
    assert sb.validate_message({"text": "", "blocks": []})


def test_long_text_is_clipped_to_limits() -> None:
    view = make_view("Needs your input", title="T" * 400, headline="H" * 5000)
    view["evidence"][1]["quote"] = "q" * 5000
    assert sb.validate_message(sb.status_message(view, now=NOW)) == []
