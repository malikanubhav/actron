"""A request with an open PR keeps building on the PR's branch (found when a re-approved ticket pushed elsewhere)."""

from __future__ import annotations

from actron.activities.request import build_branch

PR = {"number": 2, "state": "open", "branch": "actron/req_1-r1"}


def test_first_build_uses_the_revision_branch() -> None:
    assert build_branch("req_1", 1, 1, False, None) == "actron/req_1-r1"


def test_retry_without_a_pr_gets_its_own_branch() -> None:
    assert build_branch("req_1", 1, 2, False, None) == "actron/req_1-r1-2"


def test_edited_ticket_after_a_pr_reuses_the_pr_branch() -> None:
    assert build_branch("req_1", 2, 1, False, PR) == "actron/req_1-r1"


def test_requested_changes_reuse_the_pr_branch() -> None:
    assert build_branch("req_1", 1, 2, True, PR) == "actron/req_1-r1"


def test_a_closed_pr_does_not_pin_the_branch() -> None:
    assert build_branch("req_1", 2, 1, False, {**PR, "state": "closed"}) == "actron/req_1-r2"
