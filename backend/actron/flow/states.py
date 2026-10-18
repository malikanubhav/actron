"""Request states, actions and the transitions table (spec B, B.C1; PROMPT appendix F).

Pure data and pure functions: the workflow (deterministic code) and the API both import this module.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Final


class State(StrEnum):
    INVESTIGATING = "Investigating"
    NEEDS_YOUR_INPUT = "Needs your input"
    TICKET_READY = "Ticket ready"
    AWAITING_APPROVAL = "Awaiting approval"
    BUILDING = "Building"
    NEEDS_ATTENTION = "Needs attention"
    PR_READY = "PR ready for review"
    CHANGES_REQUESTED = "Changes requested"
    DONE = "Done"
    CANCELLED = "Cancelled"


class Action(StrEnum):
    """Everything that can move a request. User signals use the B.C1 names; the rest are workflow outcomes."""

    MEMORY_STALE = "memory_stale"
    INVESTIGATION_FAILED = "investigation_failed"
    FINDINGS_WITH_QUESTIONS = "findings_with_questions"
    FINDINGS_WITHOUT_QUESTIONS = "findings_without_questions"
    NOTHING_FOUND = "nothing_found"
    ANSWER_READY = "answer_ready"
    ANSWER = "answer"
    ALL_ANSWERED = "all_answered"
    TICKET_SAVED = "ticket_saved"
    EDIT_TICKET = "edit_ticket"
    APPROVE_TICKET = "approve_ticket"
    APPROVE_TICKET_REFUSED = "approve_ticket_refused"
    BUDGET_REACHED = "budget_reached"
    BUDGET_RAISED = "budget_raised"
    BUILD_PASSED = "build_passed"
    BUILD_FAILED = "build_failed"
    RETRY_INVESTIGATION = "retry_investigation"
    RETRY_BUILD = "retry_build"
    FEEDBACK_CODE_CHANGE = "feedback_code_change"
    FEEDBACK_SCOPE_CHANGE = "feedback_scope_change"
    FEEDBACK_QUESTION = "feedback_question"
    APPROVE_PR = "approve_pr"
    APPROVE_PR_REFUSED = "approve_pr_refused"
    CLOSE_PR = "close_pr"
    REVISION_BUILD_PASSED = "revision_build_passed"
    REVISION_BUILD_FAILED = "revision_build_failed"
    CANCEL = "cancel"


class InvalidTransition(Exception):
    """The action is not allowed in this state. `code` is the API/Slack reason."""

    code = "invalid_transition"

    def __init__(self, state: State, action: Action | str) -> None:
        self.state = state
        self.action = action
        super().__init__(f"{action} is not allowed while the request is {state}")


INITIAL_STATE: Final = State.INVESTIGATING
FINAL_STATES: Final[frozenset[State]] = frozenset({State.DONE, State.CANCELLED})

S = State
A = Action

_ROWS: list[tuple[State, Action, State]] = [
    (S.INVESTIGATING, A.MEMORY_STALE, S.NEEDS_ATTENTION),
    (S.INVESTIGATING, A.INVESTIGATION_FAILED, S.NEEDS_ATTENTION),
    (S.INVESTIGATING, A.FINDINGS_WITH_QUESTIONS, S.NEEDS_YOUR_INPUT),
    (S.INVESTIGATING, A.FINDINGS_WITHOUT_QUESTIONS, S.TICKET_READY),
    (S.INVESTIGATING, A.NOTHING_FOUND, S.TICKET_READY),
    (S.INVESTIGATING, A.ANSWER_READY, S.DONE),
    # B.C1: an answer is recorded while waiting; the state moves on only when all required answers are in.
    (S.NEEDS_YOUR_INPUT, A.ANSWER, S.NEEDS_YOUR_INPUT),
    (S.NEEDS_YOUR_INPUT, A.ALL_ANSWERED, S.TICKET_READY),
    (S.TICKET_READY, A.TICKET_SAVED, S.AWAITING_APPROVAL),
    (S.TICKET_READY, A.EDIT_TICKET, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, A.EDIT_TICKET, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, A.APPROVE_TICKET, S.BUILDING),
    (S.AWAITING_APPROVAL, A.APPROVE_TICKET_REFUSED, S.AWAITING_APPROVAL),
    (S.BUILDING, A.BUDGET_REACHED, S.BUILDING),
    # B.C1: budget_raised resumes a build waiting on the daily model budget.
    (S.BUILDING, A.BUDGET_RAISED, S.BUILDING),
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
_ROWS += [(s, A.CANCEL, S.CANCELLED) for s in State if s not in FINAL_STATES]

TRANSITIONS: Final[dict[tuple[State, Action], State]] = {(src, act): dst for src, act, dst in _ROWS}


def transition(state: State | str, action: Action | str) -> State:
    """The state after `action`, or InvalidTransition."""
    st = State(state)
    try:
        act = Action(action)
    except ValueError:
        raise InvalidTransition(st, str(action)) from None
    try:
        return TRANSITIONS[(st, act)]
    except KeyError:
        raise InvalidTransition(st, act) from None


def is_final(state: State | str) -> bool:
    return State(state) in FINAL_STATES


# User signals on RequestWorkflow and where each is valid (B.C1). Order is the order shown to users.
SIGNALS: Final[tuple[str, ...]] = (
    "answer", "edit_ticket", "approve_ticket", "pr_feedback", "approve_pr", "close_pr", "retry", "cancel",
)
SIGNAL_VALID_IN: Final[dict[str, set[State]]] = {
    "answer": {S.NEEDS_YOUR_INPUT},
    "edit_ticket": {S.TICKET_READY, S.AWAITING_APPROVAL, S.NEEDS_ATTENTION},
    "approve_ticket": {S.AWAITING_APPROVAL},
    "pr_feedback": {S.PR_READY},
    "approve_pr": {S.PR_READY},
    "close_pr": {S.PR_READY},
    "retry": {S.NEEDS_ATTENTION},
    "cancel": {s for s in State if s not in FINAL_STATES},
    "budget_raised": {S.BUILDING},
}


def allowed_signals(state: State | str) -> list[str]:
    st = State(state)
    return [name for name in SIGNALS if st in SIGNAL_VALID_IN[name]]


def signal_valid(name: str, state: State | str) -> bool:
    return State(state) in SIGNAL_VALID_IN.get(name, set())


# Shared state map (spec C, C-AC-10): chip tone and colour token for the UI, label text for Slack.
TONES: Final[dict[str, dict[str, str]]] = {
    "running": {"token": "--state-running", "hex": "#5BC0EB"},
    "ok": {"token": "--state-ok", "hex": "#4CC38A"},
    "conflict": {"token": "--state-conflict", "hex": "#F2555A"},
    "possible": {"token": "--state-possible", "hex": "#F0A44B"},
    "idle": {"token": "--state-idle", "hex": "#8C8C8C"},
    "needs_you": {"token": "--accent", "hex": "#E4F24C"},
}
STATE_TONE: Final[dict[State, str]] = {
    S.INVESTIGATING: "running",
    S.NEEDS_YOUR_INPUT: "needs_you",
    S.TICKET_READY: "running",
    S.AWAITING_APPROVAL: "needs_you",
    S.BUILDING: "running",
    S.NEEDS_ATTENTION: "conflict",
    S.PR_READY: "needs_you",
    S.CHANGES_REQUESTED: "running",
    S.DONE: "ok",
    S.CANCELLED: "idle",
}
NEEDS_YOU: Final[frozenset[State]] = frozenset(
    {S.NEEDS_YOUR_INPUT, S.AWAITING_APPROVAL, S.NEEDS_ATTENTION, S.PR_READY}
)
# Numbered pipeline: 01 Investigate · 02 Clarify · 03 Ticket · 04 Approve · 05 Build · 06 Review.
PIPELINE_STEP: Final[dict[State, int]] = {
    S.INVESTIGATING: 1,
    S.NEEDS_YOUR_INPUT: 2,
    S.TICKET_READY: 3,
    S.AWAITING_APPROVAL: 4,
    S.BUILDING: 5,
    S.CHANGES_REQUESTED: 5,
    S.PR_READY: 6,
    S.DONE: 6,
    S.NEEDS_ATTENTION: 1,
    S.CANCELLED: 1,
}

STATE_MAP_PATH: Final[Path] = Path(__file__).with_name("states.json")


def state_map() -> dict[str, Any]:
    """The JSON written to flow/states.json; a test keeps the file and this function equal."""
    return {
        "$comment": "Request state names, chip colour tokens and Slack labels (spec C, C-AC-10). "
        "Generated from actron/flow/states.py; a test compares it with frontend/lib/states.json.",
        "tones": TONES,
        "requestStates": {
            s.value: {
                "tone": STATE_TONE[s],
                "token": TONES[STATE_TONE[s]]["token"],
                "hex": TONES[STATE_TONE[s]]["hex"],
                "slackLabel": s.value.upper(),
                "needsYou": s in NEEDS_YOU,
                "final": s in FINAL_STATES,
                "pipelineStep": PIPELINE_STEP[s],
            }
            for s in State
        },
    }


def write_state_map(path: Path = STATE_MAP_PATH) -> None:
    path.write_text(json.dumps(state_map(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
