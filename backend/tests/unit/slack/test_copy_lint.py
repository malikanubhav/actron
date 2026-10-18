"""C-AC-36: no emoji as status and no exclamation marks in Slack copy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from actron.integrations import slack_blocks as sb

from .views import RID, make_view

NOW = datetime(2026, 10, 18, 9, 3, 0, tzinfo=UTC)
STATES = list(sb.state_map()["requestStates"])


def every_message() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = [(s, sb.status_message(make_view(s), now=NOW)) for s in STATES]
    v = make_view("Needs your input")
    out += [
        ("ack", sb.acknowledgement(v)),
        ("approval", sb.approval_confirmation(make_view("Building"), "Maya")),
        ("dm", sb.needs_you_dm(v, "needs_input")),
        ("thread", sb.needs_you_thread(v, "ticket", "U1")),
        ("finished", sb.build_finished(make_view("PR ready for review"))),
        ("failure", sb.failure(make_view("Needs attention"))),
        ("question", sb.question_message(v, v["questions"][0], 1, 3)),
        (
            "answered",
            sb.question_answered_message(
                v, {**v["questions"][0], "answer": {"value": "yes", "by": {"name": "Priya"}}}, 1, 3
            ),
        ),
        (
            "qa",
            sb.answer_message(make_view("Done", answer={"text": "Finance-only.", "citations": []})),
        ),
    ]
    return out


@pytest.mark.parametrize(
    ("name", "msg"), every_message(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_C_AC_36_copy_lint_clean(name: str, msg: dict) -> None:
    assert sb.lint_copy(msg) == [], name


def test_C_AC_36_refusals_and_usage_are_clean() -> None:
    for text in [
        sb.USAGE_TEXT,
        *(sb.refusal_text(r) for r in ("stale_head", "not_an_approver", None)),
    ]:
        assert sb.lint_copy({"text": text}) == []


def test_C_AC_36_lint_catches_violations() -> None:
    assert sb.lint_copy({"text": "Done!"})
    assert sb.lint_copy({"text": "ok \U0001f600"})
    assert sb.lint_copy({"text": "all good :white_check_mark:"})
    assert sb.lint_copy({"text": "ok", "blocks": [sb.section("Build passed!")]})
    # times and urls are not emoji shortcodes
    assert sb.lint_copy({"text": "at 10:30:15 see <https://x.io/a:b:c|link>"}) == []


def test_lint_exempts_verbatim_quotes_only() -> None:
    view = make_view("Needs your input")
    view["evidence"][1]["quote"] = "Ship it now!"
    msg = sb.status_message(view, now=NOW)
    assert sb.lint_copy(msg) == []
    assert RID  # keep the import used
