"""State machine table (PROMPT appendix F, spec B, B.C1). Every row of appendix F is one test (B-AC-7)."""

from __future__ import annotations

import json

import pytest

from actron.config import REPO_ROOT
from actron.flow.states import (
    FINAL_STATES,
    INITIAL_STATE,
    SIGNAL_VALID_IN,
    STATE_MAP_PATH,
    TRANSITIONS,
    Action,
    InvalidTransition,
    State,
    allowed_signals,
    is_final,
    state_map,
    transition,
)

S = State
A = Action

APPENDIX_F = [
    (S.INVESTIGATING, A.MEMORY_STALE, S.NEEDS_ATTENTION),
    (S.INVESTIGATING, A.INVESTIGATION_FAILED, S.NEEDS_ATTENTION),
    (S.INVESTIGATING, A.FINDINGS_WITH_QUESTIONS, S.NEEDS_YOUR_INPUT),
    (S.INVESTIGATING, A.FINDINGS_WITHOUT_QUESTIONS, S.TICKET_READY),
    (S.INVESTIGATING, A.NOTHING_FOUND, S.TICKET_READY),
    (S.INVESTIGATING, A.ANSWER_READY, S.DONE),
    (S.NEEDS_YOUR_INPUT, A.ALL_ANSWERED, S.TICKET_READY),
    (S.TICKET_READY, A.TICKET_SAVED, S.AWAITING_APPROVAL),
    (S.TICKET_READY, A.EDIT_TICKET, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, A.EDIT_TICKET, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, A.APPROVE_TICKET, S.BUILDING),
    (S.AWAITING_APPROVAL, A.APPROVE_TICKET_REFUSED, S.AWAITING_APPROVAL),
    (S.BUILDING, A.BUDGET_REACHED, S.BUILDING),
    (S.BUILDING, A.BUILD_PASSED, S.PR_READY),
    (S.BUILDING, A.BUILD_FAILED, S.NEEDS_ATTENTION),
    (S.NEEDS_ATTENTION, A.EDIT_TICKET, S.AWAITING_APPROVAL),
    (S.NEEDS_ATTENTION, A.RETRY_INVESTIGATION, S.INVESTIGATING),
    (S.NEEDS_ATTENTION, A.RETRY_BUILD, S.BUILDING),
    (S.PR_READY, A.FEEDBACK_CODE_CHANGE, S.CHANGES_REQUESTED),
    (S.PR_READY, A.FEEDBACK_SCOPE_CHANGE, S.NEEDS_ATTENTION),
    (S.PR_READY, A.FEEDBACK_QUESTION, S.PR_READY),
    (S.PR_READY, A.APPROVE_PR, S.DONE),
    (S.PR_READY, A.APPROVE_PR_REFUSED, S.PR_READY),
    (S.PR_READY, A.CLOSE_PR, S.CANCELLED),
    (S.CHANGES_REQUESTED, A.REVISION_BUILD_PASSED, S.PR_READY),
    (S.CHANGES_REQUESTED, A.REVISION_BUILD_FAILED, S.NEEDS_ATTENTION),
]


def test_states_exact_strings() -> None:
    """B.C1: state strings are shared by API, UI and Slack."""
    assert [s.value for s in State] == [
        "Investigating", "Needs your input", "Ticket ready", "Awaiting approval", "Building",
        "Needs attention", "PR ready for review", "Changes requested", "Done", "Cancelled",
    ]


def test_create_starts_investigating() -> None:
    """B-AC-7 appendix F row: (new) create -> Investigating."""
    assert INITIAL_STATE is State.INVESTIGATING


@pytest.mark.parametrize(("src", "action", "dst"), APPENDIX_F, ids=[f"{r[0].value}|{r[1].value}" for r in APPENDIX_F])
def test_appendix_f_row(src: State, action: Action, dst: State) -> None:
    """B-AC-7: each appendix F row is in the table and resolves to its target."""
    assert transition(src, action) is dst


@pytest.mark.parametrize("src", [s for s in State if s not in FINAL_STATES])
def test_cancel_from_every_non_final(src: State) -> None:
    """B-AC-7: any non-final state + cancel -> Cancelled."""
    assert transition(src, Action.CANCEL) is State.CANCELLED


@pytest.mark.parametrize("src", sorted(FINAL_STATES))
def test_final_states_refuse_everything(src: State) -> None:
    """B-AC-7: final states accept no action."""
    for action in Action:
        with pytest.raises(InvalidTransition):
            transition(src, action)


def test_table_has_no_extra_rows() -> None:
    """B-AC-7: the table is exactly appendix F plus cancel rows and the in-state records from B.C1."""
    expected = {(s, a) for s, a, _ in APPENDIX_F}
    expected |= {(s, Action.CANCEL) for s in State if s not in FINAL_STATES}
    expected |= {(S.NEEDS_YOUR_INPUT, A.ANSWER), (S.BUILDING, A.BUDGET_RAISED)}
    assert set(TRANSITIONS) == expected


def test_invalid_pair_raises_with_fields() -> None:
    """B-AC-7: invalid pairs raise InvalidTransition(state, action)."""
    with pytest.raises(InvalidTransition) as exc:
        transition(State.INVESTIGATING, Action.APPROVE_PR)
    assert exc.value.state is State.INVESTIGATING
    assert exc.value.action is Action.APPROVE_PR
    assert exc.value.code == "invalid_transition"


def test_signal_validity_matches_b_c1() -> None:
    """B.C1 signal table: where each user signal is valid."""
    assert SIGNAL_VALID_IN["answer"] == {S.NEEDS_YOUR_INPUT}
    assert SIGNAL_VALID_IN["edit_ticket"] == {S.TICKET_READY, S.AWAITING_APPROVAL, S.NEEDS_ATTENTION}
    assert SIGNAL_VALID_IN["approve_ticket"] == {S.AWAITING_APPROVAL}
    assert SIGNAL_VALID_IN["pr_feedback"] == {S.PR_READY}
    assert SIGNAL_VALID_IN["approve_pr"] == {S.PR_READY}
    assert SIGNAL_VALID_IN["close_pr"] == {S.PR_READY}
    assert SIGNAL_VALID_IN["retry"] == {S.NEEDS_ATTENTION}
    assert SIGNAL_VALID_IN["cancel"] == {s for s in State if s not in FINAL_STATES}
    assert SIGNAL_VALID_IN["budget_raised"] == {S.BUILDING}


def test_allowed_signals_for_awaiting_approval() -> None:
    assert allowed_signals(State.AWAITING_APPROVAL) == ["edit_ticket", "approve_ticket", "cancel"]
    assert allowed_signals(State.DONE) == []
    assert is_final(State.CANCELLED) and not is_final(State.BUILDING)


def test_state_map_json_matches_code() -> None:
    """C-AC-10: backend states.json (name -> chip colour token, Slack label) matches states.py."""
    data = json.loads(STATE_MAP_PATH.read_text())
    assert data == state_map()
    assert set(data["requestStates"]) == {s.value for s in State}
    for name, entry in data["requestStates"].items():
        assert entry["token"].startswith("--")
        assert entry["slackLabel"] == name.upper()


def test_state_map_matches_frontend() -> None:
    """C-AC-10: the backend map agrees with frontend/lib/states.json (tone, token, text, needsYou, final)."""
    path = REPO_ROOT / "frontend" / "lib" / "states.json"
    if not path.exists():
        pytest.skip("frontend/lib/states.json not present")
    front = json.loads(path.read_text())
    back = state_map()
    for name, entry in front["requestStates"].items():
        mine = back["requestStates"][name]
        assert mine["tone"] == entry["tone"]
        assert mine["slackLabel"] == entry["text"]
        assert mine["needsYou"] == entry["needsYou"]
        assert mine["final"] == entry["final"]
        assert mine["token"] == front["tones"][entry["tone"]]["token"]
        assert mine["hex"] == front["tones"][entry["tone"]]["hex"]
