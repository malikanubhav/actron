"""RequestWorkflow in the time-skipping test server with fake activities (spec B, B2).

Every appendix F row and each refusal is a test (B-AC-7). Also B-AC-8 (concurrent approvals), B-AC-9 (edit voids
earlier approval target), B-AC-10 (24-hour reminder), B-AC-11 (cancel during build), B-AC-13 (Q&A), B-AC-78
(memory_stale), B-AC-81 (missing_branch).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from tests.api._wf_harness import Fakes, Run, failing, run_workflow

pytestmark = pytest.mark.asyncio(loop_scope="module")

Q1 = {"questionId": "q1", "text": "Keep Finance-only?", "kind": "choice", "required": True,
      "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}], "evidenceIds": []}
BRANCH_Q = {"questionId": "target_branch", "text": "Which branch should this change go into?", "kind": "choice",
            "required": True, "options": [{"value": "main", "label": "main"}, {"value": "new:main", "label": "New"}],
            "evidenceIds": []}


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def client() -> AsyncIterator[Client]:
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env.client
    finally:
        await env.shutdown()


async def to_awaiting(run: Run) -> dict[str, Any]:
    return await run.wait_state("Awaiting approval")


async def to_pr_ready(run: Run) -> None:
    await to_awaiting(run)
    await run.signal("approve_ticket", {"revisionHash": "hash1"})
    await run.wait_state("PR ready for review")


# Investigating
async def test_create_starts_investigating(client: Client) -> None:
    """B-AC-7 row: (new) create -> Investigating."""
    fakes = Fakes()
    fakes.gates["ensure_fresh"] = asyncio.Event()

    async def body(run: Run) -> None:
        assert (await run.wait_state("Investigating"))["state"] == "Investigating"
        fakes.gates["ensure_fresh"].set()
        await to_awaiting(run)

    await run_workflow(client, fakes, body)


async def test_freshness_timeout_moves_to_needs_attention(client: Client) -> None:
    """B-AC-7 / B-AC-78: freshness gate timeout (memory_stale) -> Needs attention."""
    fakes = Fakes(script={"ensure_fresh": {"status": "stale", "sha": "old"}})

    async def body(run: Run) -> None:
        await run.wait_state("Needs attention")
        last = fakes.called("set_state")[-1]
        assert last["reason"] == "memory_stale" and last["data"]["failedStep"] == "investigate"
        assert not fakes.called("investigate_request")

    await run_workflow(client, fakes, body)


async def test_investigation_failed_twice(client: Client) -> None:
    """B-AC-7: investigation failed twice -> Needs attention; retry -> Investigating."""
    fakes = Fakes(script={"investigate_request": failing(2, {"label": "clear"})})

    async def body(run: Run) -> None:
        await run.wait_state("Needs attention")
        assert len(fakes.called("investigate_request")) == 2
        await run.signal("retry")
        await to_awaiting(run)
        assert "Investigating" in fakes.states()

    await run_workflow(client, fakes, body)


async def test_findings_with_questions_then_all_answered(client: Client) -> None:
    """B-AC-7 rows: findings with questions -> Needs your input; all answered -> Ticket ready."""
    fakes = Fakes(script={"prepare_questions": {"questions": [Q1, BRANCH_Q], "branchNames": ["main", "dev"]}})

    async def body(run: Run) -> None:
        st = await run.wait_state("Needs your input")
        assert st["pendingQuestions"] == ["q1", "target_branch"]
        await run.signal("answer", {"questionId": "q1", "value": "yes"})
        await run.wait_for(lambda: len(fakes.called("record_answer")) == 1)
        assert (await run.state())["state"] == "Needs your input"
        await run.signal("answer", {"questionId": "target_branch", "value": "dev"})
        await to_awaiting(run)
        assert fakes.states()[:2] == ["Needs your input", "Ticket ready"]

    await run_workflow(client, fakes, body)


async def test_invalid_answer_refused(client: Client) -> None:
    """B-AC-31: an answer that is not an option is refused and the question stays open."""
    fakes = Fakes(script={"prepare_questions": {"questions": [Q1], "branchNames": ["main"]}})

    async def body(run: Run) -> None:
        await run.wait_state("Needs your input")
        await run.signal("answer", {"questionId": "q1", "value": "maybe"})
        await run.wait_for(lambda: any(o.get("reason") == "invalid_answer" for o in fakes.outcomes()))
        assert (await run.state())["pendingQuestions"] == ["q1"]

    await run_workflow(client, fakes, body)


async def test_findings_without_questions(client: Client) -> None:
    """B-AC-7 rows: findings without questions -> Ticket ready; ticket saved -> Awaiting approval."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_awaiting(run)
        assert fakes.states()[:2] == ["Ticket ready", "Awaiting approval"]
        assert fakes.called("set_state")[0]["reason"] == "no_questions"
        assert len(fakes.called("sync_ticket")) == 1

    await run_workflow(client, fakes, body)


async def test_state_query_never_lags_the_postgres_mirror(client: Client) -> None:
    """B-AC-36: while the mirror of a new state is being written (UI and Slack already see it once it lands), the
    state query the service pre-checks with reports that new state, so an action sent at once is not refused."""
    fakes = Fakes()
    fakes.gates["set_state"] = asyncio.Event()

    async def body(run: Run) -> None:
        await run.wait_for(lambda: bool(fakes.called("set_state")))
        writing = fakes.called("set_state")[0]["to"]
        assert writing == "Ticket ready"
        assert (await run.state())["state"] == writing  # the mirror activity has not returned yet
        fakes.gates["set_state"].set()
        await to_awaiting(run)

    await run_workflow(client, fakes, body)


async def test_nothing_found(client: Client) -> None:
    """B-AC-7 row: nothing found (branch named) -> Ticket ready."""
    fakes = Fakes(script={"investigate_request": {"label": "nothing_found"}})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        assert fakes.called("set_state")[0]["reason"] == "nothing_found"

    await run_workflow(client, fakes, body)


async def test_question_kind_ends_done(client: Client) -> None:
    """B-AC-7 / B-AC-13: Q&A requests end Done (answered) with an answer and no ticket."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        res = await run.result()
        assert res == {"state": "Done", "outcome": "answered"}
        assert len(fakes.called("write_answer")) == 1
        assert not fakes.called("save_revision") and not fakes.called("prepare_questions")

    await run_workflow(client, fakes, body, kind="question")


# Tickets and approvals
async def test_edit_during_ticket_ready(client: Client) -> None:
    """B-AC-7 row: Ticket ready + edit_ticket -> Awaiting approval with a new revision."""
    fakes = Fakes()
    fakes.gates["draft_ticket"] = asyncio.Event()

    async def body(run: Run) -> None:
        await run.wait_for(lambda: bool(fakes.called("draft_ticket")))
        await run.signal("edit_ticket", {"content": {"objective": "Edited"}})
        fakes.gates["draft_ticket"].set()
        await run.wait_for(lambda: len(fakes.called("save_revision")) == 2)
        st = await to_awaiting(run)
        assert st["currentRevision"] == {"n": 2, "hash": "hash2"}

    await run_workflow(client, fakes, body)


async def test_edit_while_awaiting_voids_old_hash(client: Client) -> None:
    """B-AC-7 / B-AC-9: edit while Awaiting approval makes a new revision; approving the old hash is stale."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("edit_ticket", {"content": {"objective": "v2"}})
        await run.wait_for(lambda: len(fakes.called("save_revision")) == 2)
        assert (await run.state())["currentRevision"]["hash"] == "hash2"
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_for(lambda: ("ticket", "refused", "stale_revision") in fakes.approvals())
        assert (await run.state())["state"] == "Awaiting approval"
        assert any(o.get("revision") == {"n": 2, "hash": "hash2"} for o in fakes.outcomes())
        await run.signal("approve_ticket", {"revisionHash": "hash2"})
        await run.wait_state("PR ready for review")

    await run_workflow(client, fakes, body)


async def test_approve_current_hash_builds(client: Client) -> None:
    """B-AC-7 rows: approve with current hash -> Building; tests pass, PR opened -> PR ready for review."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        assert fakes.approvals() == [("ticket", "accepted", None)]
        assert fakes.states()[-2:] == ["Building", "PR ready for review"]
        assert (await run.state())["pr"] == {"number": 7, "headSha": "head1"}
        assert fakes.called("prepare_build")[0]["baseSha"] == "base123"

    await run_workflow(client, fakes, body)


async def test_external_edit_refused(client: Client) -> None:
    """B-AC-7 / B-AC-34: external edit in Linear -> approval refused with external_edit; stays Awaiting."""
    fakes = Fakes(script={"check_external_edit": [{"externalEdit": True}, {"externalEdit": False}]})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_for(lambda: ("ticket", "refused", "external_edit") in fakes.approvals())
        assert (await run.state())["state"] == "Awaiting approval"

    await run_workflow(client, fakes, body)


async def test_concurrent_approvals_one_build(client: Client) -> None:
    """B-AC-8 / B-AC-38: two approvals of the same hash (Slack and UI) -> one accepted, one duplicate, one build."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await asyncio.gather(
            run.signal("approve_ticket", {"revisionHash": "hash1", "actor": {"surface": "slack", "name": "A"}}),
            run.signal("approve_ticket", {"revisionHash": "hash1", "actor": {"surface": "ui", "name": "B"}}),
        )
        await run.wait_state("PR ready for review")
        await run.wait_for(lambda: any(o.get("status") == "duplicate" for o in fakes.outcomes()))
        assert fakes.approvals() == [("ticket", "accepted", None)]
        assert len(fakes.called("prepare_build")) == 1

    await run_workflow(client, fakes, body)


async def test_duplicate_signal_key_applied_once(client: Client) -> None:
    """B-AC-2 / B-AC-5: the workflow deduplicates signals by idempotencyKey."""
    fakes = Fakes(script={"prepare_questions": {"questions": [Q1, BRANCH_Q], "branchNames": ["main"]}})

    async def body(run: Run) -> None:
        await run.wait_state("Needs your input")
        await run.signal("answer", {"questionId": "q1", "value": "yes"}, key="same")
        await run.signal("answer", {"questionId": "q1", "value": "no"}, key="same")
        await run.signal("answer", {"questionId": "target_branch", "value": "main"})
        await to_awaiting(run)
        assert [a["value"] for a in fakes.called("record_answer")] == ["yes", "main"]

    await run_workflow(client, fakes, body)


async def test_invalid_transition_refused(client: Client) -> None:
    """B-AC-7: an action not valid in the state is refused with invalid_transition."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_pr", {"headSha": "x"})
        await run.signal("retry")
        await run.wait_for(lambda: ("pr", "refused", "invalid_transition") in fakes.approvals())
        await run.wait_for(lambda: any(o.get("reason") == "invalid_transition" for o in fakes.outcomes()))
        assert (await run.state())["state"] == "Awaiting approval"

    await run_workflow(client, fakes, body)


# Build outcomes
@pytest.mark.parametrize("reason", ["build_failed_after_repairs", "scope_change", "tests_weakened", "timeout",
                                    "missing_fork", "missing_identity"])
async def test_build_failure_needs_attention(client: Client, reason: str) -> None:
    """B-AC-7 row: Building -> Needs attention for each stop reason; retry -> Building."""
    fakes = Fakes(script={"build": [{"status": "failed", "stopReason": reason}, {"status": "passed", "prNumber": 9,
                                                                               "headSha": "h9"}]})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_state("Needs attention")
        last = fakes.called("set_state")[-1]
        assert last["reason"] == reason and last["flags"] == {"fromBuild": True}
        await run.signal("retry")
        await run.wait_state("PR ready for review")
        assert fakes.states()[-3:] == ["Needs attention", "Building", "PR ready for review"]

    await run_workflow(client, fakes, body)


@pytest.mark.parametrize(("fresh", "reason"), [({"status": "stale"}, "memory_stale"),
                                               ({"status": "missing_branch"}, "missing_branch")])
async def test_build_freshness_failures(client: Client, fresh: dict[str, Any], reason: str) -> None:
    """B-AC-81 / B-AC-78: a deleted target branch or a stale memory before the build -> Needs attention."""
    fakes = Fakes(script={"ensure_fresh": [{"status": "fresh", "sha": "a"}, fresh]})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_state("Needs attention")
        assert fakes.called("set_state")[-1]["reason"] == reason
        assert not fakes.called("prepare_build")

    await run_workflow(client, fakes, body)


async def test_needs_attention_edit_goes_to_awaiting(client: Client) -> None:
    """B-AC-7 row: Needs attention + edit_ticket -> Awaiting approval (new revision)."""
    fakes = Fakes(script={"build": {"status": "failed", "stopReason": "timeout"}})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_state("Needs attention")
        await run.signal("edit_ticket", {"content": {"objective": "smaller"}})
        st = await run.wait_state("Awaiting approval")
        assert st["currentRevision"]["n"] == 2

    await run_workflow(client, fakes, body)


async def test_cancel_during_build_cancels_child(client: Client) -> None:
    """B-AC-11: cancel during Building cancels the build child and its running Pi activity."""
    fakes = Fakes(script={"build_input": {"hang": True}})

    async def body(run: Run) -> None:
        await to_awaiting(run)
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_state("Building")
        await asyncio.sleep(0.5)
        await run.signal("cancel", {"reason": "not needed"})
        res = await run.result()
        assert res == {"state": "Cancelled", "outcome": "cancelled"}
        assert fakes.pi_cancelled == ["b1"]
        assert len(fakes.called("mark_build_cancelled")) == 1

    await run_workflow(client, fakes, body)


# Review
async def test_feedback_code_change_then_revision_build(client: Client) -> None:
    """B-AC-7 rows: feedback code_change -> Changes requested; revision build passes -> PR ready."""
    fakes = Fakes(script={"classify_feedback": {"kind": "code_change_within_scope"}})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("pr_feedback", {"text": "Rename the flag", "headSha": "head1"})
        await run.wait_for(lambda: len(fakes.called("prepare_build")) == 2)
        await run.wait_state("PR ready for review")
        assert "Changes requested" in fakes.states()
        assert fakes.called("prepare_build")[1]["feedback"] == "Rename the flag"
        assert fakes.called("prepare_build")[1]["sameBranch"] is True

    await run_workflow(client, fakes, body)


async def test_revision_build_fails(client: Client) -> None:
    """B-AC-7 row: Changes requested + revision build fails -> Needs attention."""
    fakes = Fakes(script={"classify_feedback": {"kind": "code_change_within_scope"},
                          "build": [{"status": "passed", "prNumber": 7, "headSha": "head1"},
                                    {"status": "stopped", "stopReason": "tests_weakened"}]})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("pr_feedback", {"text": "Change it", "headSha": "head1"})
        await run.wait_state("Needs attention")
        assert fakes.states()[-2:] == ["Changes requested", "Needs attention"]

    await run_workflow(client, fakes, body)


async def test_feedback_scope_change(client: Client) -> None:
    """B-AC-7 row: feedback scope_change -> Needs attention."""
    fakes = Fakes(script={"classify_feedback": {"kind": "scope_change"}})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("pr_feedback", {"text": "Also add PDF export", "headSha": "head1"})
        await run.wait_state("Needs attention")
        assert fakes.called("set_state")[-1]["reason"] == "scope_change"

    await run_workflow(client, fakes, body)


async def test_feedback_question(client: Client) -> None:
    """B-AC-7 row: feedback question -> stays PR ready, answer posted."""
    fakes = Fakes(script={"classify_feedback": {"kind": "question"}})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("pr_feedback", {"text": "Why this file?", "headSha": "head1"})
        await run.wait_for(lambda: bool(fakes.called("answer_feedback")))
        assert (await run.state())["state"] == "PR ready for review"

    await run_workflow(client, fakes, body)


async def test_approve_pr_current_head(client: Client) -> None:
    """B-AC-7 row: approve_pr with the current head -> Done (approved), write-back runs."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("approve_pr", {"headSha": "head1"})
        res = await run.result()
        assert res == {"state": "Done", "outcome": "approved"}
        assert ("pr", "accepted", None) in fakes.approvals()
        assert len(fakes.called("writeback")) == 1
        assert fakes.called("trigger_syncs")

    await run_workflow(client, fakes, body)


async def test_feedback_approval_treated_as_approve(client: Client) -> None:
    """B-AC-7 row: pr_feedback classified approval -> Done."""
    fakes = Fakes(script={"classify_feedback": {"kind": "approval"}})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("pr_feedback", {"text": "Looks good, ship it", "headSha": "head1"})
        assert (await run.result())["state"] == "Done"

    await run_workflow(client, fakes, body)


async def test_approve_pr_stale_head(client: Client) -> None:
    """B-AC-7 / B-AC-37: approve_pr with a stale head is refused with stale_head."""
    fakes = Fakes(script={"read_pr_head": {"headSha": "head2"}})

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("approve_pr", {"headSha": "head1"})
        await run.wait_for(lambda: ("pr", "refused", "stale_head") in fakes.approvals())
        assert (await run.state())["state"] == "PR ready for review"

    await run_workflow(client, fakes, body)


async def test_close_pr(client: Client) -> None:
    """B-AC-7 row: close_pr -> Cancelled with outcome closed (PR closed on GitHub)."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await to_pr_ready(run)
        await run.signal("close_pr", {"reason": "not now"})
        assert await run.result() == {"state": "Cancelled", "outcome": "closed"}
        assert fakes.called("close_pr")

    await run_workflow(client, fakes, body)


# Cancel from every non-final state
async def _reach(run: Run, state: str) -> None:
    fakes = run.fakes
    if state == "Investigating":
        await run.wait_state("Investigating")
        return
    if state == "Needs your input":
        await run.wait_state(state)
        return
    if state == "Ticket ready":
        await run.wait_for(lambda: bool(fakes.called("draft_ticket")))
        return
    await to_awaiting(run)
    if state == "Awaiting approval":
        return
    await run.signal("approve_ticket", {"revisionHash": "hash1"})
    if state == "Building":
        await run.wait_state("Building")
        return
    if state == "Needs attention":
        await run.wait_state(state)
        return
    await run.wait_state("PR ready for review")
    if state == "Changes requested":
        await run.signal("pr_feedback", {"text": "change", "headSha": "head1"})
        await run.wait_state(state)


@pytest.mark.parametrize("state", ["Investigating", "Needs your input", "Ticket ready", "Awaiting approval",
                                   "Building", "Needs attention", "PR ready for review", "Changes requested"])
async def test_cancel_from_every_state(client: Client, state: str) -> None:
    """B-AC-7 row: any non-final state + cancel -> Cancelled (outcome cancelled)."""
    script: dict[str, Any] = {}
    fakes = Fakes(script=script)
    if state == "Investigating":
        fakes.gates["investigate_request"] = asyncio.Event()
    if state == "Needs your input":
        script["prepare_questions"] = {"questions": [Q1], "branchNames": ["main"]}
    if state == "Ticket ready":
        fakes.gates["draft_ticket"] = asyncio.Event()
    if state in ("Building", "Changes requested"):
        script["build_input"] = {"hang": True} if state == "Building" else {}
    if state == "Changes requested":
        script["classify_feedback"] = {"kind": "code_change_within_scope"}
    if state == "Needs attention":
        script["build"] = {"status": "failed", "stopReason": "timeout"}

    async def body(run: Run) -> None:
        if state == "Changes requested":
            # Hold the second build so the request stays in Changes requested.
            await _reach_pr_then_hold(run)
        else:
            await _reach(run, state)
        await run.signal("cancel", {"reason": "stop"})
        res = await run.result()
        assert res == {"state": "Cancelled", "outcome": "cancelled"}
        assert fakes.called("set_state")[-1]["to"] == "Cancelled"

    await run_workflow(client, fakes, body)


async def _reach_pr_then_hold(run: Run) -> None:
    await to_pr_ready(run)
    run.fakes.script["build_input"] = {"hang": True}
    await run.signal("pr_feedback", {"text": "change", "headSha": "head1"})
    await run.wait_state("Changes requested")


async def test_reminder_sent_once_after_a_day(client: Client) -> None:
    """B-AC-10: waiting for answers for more than 24 hours sends exactly one reminder."""
    fakes = Fakes(script={"prepare_questions": {"questions": [Q1], "branchNames": ["main"]}})

    async def body(run: Run) -> None:
        await run.wait_state("Needs your input")
        env = CURRENT_ENV["env"]
        await env.sleep(timedelta(hours=25))
        await run.wait_for(lambda: len(fakes.called("send_reminder")) == 1)
        await env.sleep(timedelta(hours=49))
        await asyncio.sleep(0.3)
        assert len(fakes.called("send_reminder")) == 1
        assert fakes.called("send_reminder")[0]["kind"] == "needs_input"

    CURRENT_ENV["env"] = await WorkflowEnvironment.start_time_skipping()
    try:
        await run_workflow(CURRENT_ENV["env"].client, fakes, body)
    finally:
        await CURRENT_ENV["env"].shutdown()


CURRENT_ENV: dict[str, WorkflowEnvironment] = {}
