"""No action sequence drives the request state machine into an invalid state (PROMPT 9.2, B-AC-7)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from actron.flow.states import (
    FINAL_STATES,
    INITIAL_STATE,
    TRANSITIONS,
    Action,
    InvalidTransition,
    State,
    transition,
)


@settings(max_examples=400)
@given(st.lists(st.sampled_from(list(Action)), max_size=60))
def test_any_action_sequence_stays_valid(actions: list[Action]) -> None:
    """B-AC-7: invalid actions are refused and leave the state unchanged; valid ones land on a known state."""
    state = INITIAL_STATE
    for action in actions:
        try:
            nxt = transition(state, action)
        except InvalidTransition:
            assert (state, action) not in TRANSITIONS
            continue
        assert isinstance(nxt, State)
        assert state not in FINAL_STATES
        state = nxt
    assert state in set(State)


def test_every_state_reachable_from_initial() -> None:
    """B-AC-7: the table has no unreachable state."""
    seen = {INITIAL_STATE}
    frontier = [INITIAL_STATE]
    while frontier:
        cur = frontier.pop()
        for (src, _), dst in TRANSITIONS.items():
            if src is cur and dst not in seen:
                seen.add(dst)
                frontier.append(dst)
    assert seen == set(State)


def test_every_non_final_state_can_finish() -> None:
    """B-AC-7: from every non-final state some path reaches Done or Cancelled."""
    for start in State:
        if start in FINAL_STATES:
            continue
        seen = {start}
        frontier = [start]
        while frontier:
            cur = frontier.pop()
            for (src, _), dst in TRANSITIONS.items():
                if src is cur and dst not in seen:
                    seen.add(dst)
                    frontier.append(dst)
        assert seen & FINAL_STATES
