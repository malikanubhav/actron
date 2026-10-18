"""RequestWorkflow (spec B, B2): the authority on a request's state.

Deterministic: every read and write goes through activities; time comes from `workflow.now()`. Signals carry an
`idempotencyKey` and are deduplicated; they queue in an inbox and each wait takes only the actions valid in the
current state (others are refused with `invalid_transition`). `cancel` interrupts any wait, running activity or
build child.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from actron.activities import request as acts
    from actron.flow import questions as qmod
    from actron.flow.states import Action, InvalidTransition, State, transition

REMINDER_AFTER = timedelta(hours=24)
MERGE_POLL = timedelta(minutes=2)
BUILD_QUEUE = "build"
REQUEST_QUEUE = "request"
FAST = timedelta(seconds=60)


@dataclass
class _Msg:
    name: str
    payload: dict[str, Any]


class _Cancelled(Exception):
    def __init__(self, msg: _Msg) -> None:
        super().__init__("cancelled")
        self.msg = msg


@workflow.defn(name="RequestWorkflow")
class RequestWorkflow:
    def __init__(self) -> None:
        self._state = State.INVESTIGATING
        self._inbox: list[_Msg] = []
        self._seen: set[str] = set()
        self._cancel: _Msg | None = None
        self._ws = ""
        self._rid = ""
        self._kind = "feature"
        self._questions: list[dict[str, Any]] = []
        self._answers: dict[str, str] = {}
        self._branch_names: list[str] = []
        self._revision: dict[str, Any] | None = None
        self._target_branch: str | None = None
        self._accepted_hash: str | None = None
        self._failed_step = "investigate"
        self._feedback: str | None = None
        self._build: dict[str, Any] = {"status": None, "queuePosition": None, "id": None}
        self._pr: dict[str, Any] | None = None
        self._outcome: str | None = None
        self._watch: asyncio.Task[None] | None = None
        self._build_attempt = 0
        self._options: dict[str, Any] = {}

    # Signals (B.C1). Each carries {actor, idempotencyKey, ...}.
    def _receive(self, name: str, payload: dict[str, Any] | None) -> None:
        payload = dict(payload or {})
        key = payload.get("idempotencyKey")
        if key:
            if key in self._seen:
                return
            self._seen.add(str(key))
        msg = _Msg(name, payload)
        if name == "cancel" and self._state not in (State.DONE, State.CANCELLED):
            self._cancel = self._cancel or msg
            return
        self._inbox.append(msg)

    @workflow.signal(name="answer")
    def answer(self, payload: dict[str, Any]) -> None:
        self._receive("answer", payload)

    @workflow.signal(name="edit_ticket")
    def edit_ticket(self, payload: dict[str, Any]) -> None:
        self._receive("edit_ticket", payload)

    @workflow.signal(name="approve_ticket")
    def approve_ticket(self, payload: dict[str, Any]) -> None:
        self._receive("approve_ticket", payload)

    @workflow.signal(name="pr_feedback")
    def pr_feedback(self, payload: dict[str, Any]) -> None:
        self._receive("pr_feedback", payload)

    @workflow.signal(name="approve_pr")
    def approve_pr(self, payload: dict[str, Any]) -> None:
        self._receive("approve_pr", payload)

    @workflow.signal(name="close_pr")
    def close_pr(self, payload: dict[str, Any]) -> None:
        self._receive("close_pr", payload)

    @workflow.signal(name="retry")
    def retry(self, payload: dict[str, Any]) -> None:
        self._receive("retry", payload)

    @workflow.signal(name="cancel")
    def cancel(self, payload: dict[str, Any]) -> None:
        self._receive("cancel", payload)

    @workflow.signal(name="budget_raised")
    def budget_raised(self, payload: dict[str, Any]) -> None:
        self._receive("budget_raised", payload)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "currentRevision": dict(self._revision) if self._revision else None,
            "pendingQuestions": qmod.pending_questions(self._questions, self._answers),
            "build": {"status": self._build.get("status"), "queuePosition": self._build.get("queuePosition")},
            "pr": {"number": self._pr.get("number"), "headSha": self._pr.get("headSha")} if self._pr else None,
        }

    # Run
    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        self._ws = str(inp["ws"])
        self._rid = str(inp["requestId"])
        self._kind = str(inp.get("kind") or "feature")
        self._options = dict(inp.get("options") or {})
        step = "investigate"
        try:
            while step != "done":
                if step == "investigate":
                    step = await self._investigate()
                elif step == "questions":
                    step = await self._ask()
                elif step == "ticket":
                    step = await self._draft()
                elif step == "approval":
                    step = await self._approval()
                elif step == "build":
                    step = await self._build_step()
                elif step == "attention":
                    step = await self._attention()
                elif step == "review":
                    step = await self._review()
        except _Cancelled as c:
            await self._finish_cancel(c.msg)
        return {"state": self._state.value, "outcome": self._outcome}

    # Helpers
    def _ids(self) -> dict[str, Any]:
        return {"ws": self._ws, "requestId": self._rid}

    async def _act(self, fn: Any, extra: dict[str, Any] | None = None, *, timeout: timedelta = FAST,
                   attempts: int = 5, heartbeat: timedelta | None = None) -> Any:
        return await workflow.execute_activity(
            fn, {**self._ids(), **(extra or {})}, start_to_close_timeout=timeout,
            heartbeat_timeout=heartbeat,
            retry_policy=RetryPolicy(maximum_attempts=attempts, initial_interval=timedelta(seconds=1),
                                     backoff_coefficient=2.0, maximum_interval=timedelta(seconds=30)),
        )

    async def _move(self, action: Action, reason: str | None = None, *, outcome: str | None = None,
                    data: dict[str, Any] | None = None, flags: dict[str, Any] | None = None,
                    by: dict[str, Any] | None = None) -> None:
        """Apply one appendix F transition; the activity mirrors it only when the state changes."""
        to = transition(self._state, action)
        changed = to != self._state
        # The state query (the service's pre-check) must not lag the PostgreSQL mirror that the UI and Slack
        # read: set it before the mirror is written, so an action sent the moment the new state shows is not
        # refused as "not available while <old state>". A signal arriving meanwhile waits in the queue.
        self._state = to
        if changed or data:
            if to in (State.DONE, State.CANCELLED):
                self._outcome = outcome
            await self._act(acts.set_state, {"to": to.value, "reason": reason or action.value, "outcome": outcome,
                                             "data": data or {}, "flags": flags or {}, "by": by})

    async def _outcome_to(self, msg: _Msg, outcome: dict[str, Any]) -> None:
        key = msg.payload.get("idempotencyKey")
        if key:
            await self._act(acts.publish_outcome, {"idempotencyKey": key,
                                                   "outcome": {**outcome, "state": self._state.value}})

    async def _refuse(self, msg: _Msg, reason: str = "invalid_transition") -> None:
        if msg.name == "approve_ticket" and msg.payload.get("revisionHash") == self._accepted_hash:
            await self._outcome_to(msg, {"status": "duplicate", "reason": None})
            return
        if msg.name in ("approve_ticket", "approve_pr"):
            kind = "ticket" if msg.name == "approve_ticket" else "pr"
            target = msg.payload.get("revisionHash") if kind == "ticket" else msg.payload.get("headSha")
            await self._act(acts.record_approval, {
                "kind": kind, "target": str(target or ""), "status": "refused", "reason": reason,
                "actor": msg.payload.get("actor"), "idempotencyKey": msg.payload.get("idempotencyKey"),
                "state": self._state.value})
            return
        if msg.name == "budget_raised":
            return
        await self._outcome_to(msg, {"status": "refused", "reason": reason})

    async def _next(self, accept: set[str], *, remind: str | None = None) -> _Msg:
        """Wait for the next action valid here; refuse the rest; one reminder after 24 hours when asked."""
        reminded = remind is None
        while True:
            if self._cancel is not None:
                raise _Cancelled(self._cancel)
            if self._inbox:
                msg = self._inbox.pop(0)
                if msg.name in accept:
                    return msg
                await self._refuse(msg)
                continue
            if not reminded:
                try:
                    await workflow.wait_condition(lambda: bool(self._inbox) or self._cancel is not None,
                                                  timeout=REMINDER_AFTER)
                except TimeoutError:
                    reminded = True
                    await self._act(acts.send_reminder, {"kind": remind})
                continue
            await workflow.wait_condition(lambda: bool(self._inbox) or self._cancel is not None)

    async def _await(self, aw: Any, *, defer: frozenset[str] = frozenset(), child: Any = None) -> Any:
        """Await an activity or child while refusing actions that are not valid now; cancel interrupts it."""
        task = asyncio.ensure_future(aw)
        while True:
            await workflow.wait_condition(
                lambda: task.done() or self._cancel is not None
                or any(m.name not in defer for m in self._inbox))
            if task.done():
                return task.result()
            if self._cancel is not None:
                if child is not None:
                    child.cancel()
                else:
                    task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                raise _Cancelled(self._cancel)
            for msg in [m for m in self._inbox if m.name not in defer]:
                self._inbox.remove(msg)
                await self._refuse(msg)

    # Steps
    async def _investigate(self) -> str:
        fresh = await self._await(self._act(acts.ensure_fresh, {**self._fresh_opts()},
                                            timeout=timedelta(minutes=11), attempts=2))
        if fresh.get("status") == "stale":
            self._failed_step = "investigate"
            await self._move(Action.MEMORY_STALE, "memory_stale",
                             data={"failedStep": "investigate", "attentionReason": "memory_stale"})
            return "attention"
        try:
            inv = await self._await(self._act(acts.investigate_request, {"kind": self._kind},
                                              timeout=timedelta(minutes=10), attempts=2))
            result = await self._act(acts.prepare_questions) if self._kind != "question" else {}
        except ActivityError:
            self._failed_step = "investigate"
            await self._move(Action.INVESTIGATION_FAILED, "investigation_failed",
                             data={"failedStep": "investigate", "attentionReason": "investigation_failed"})
            return "attention"
        if self._kind == "question":
            await self._await(self._act(acts.write_answer, timeout=timedelta(minutes=3)))
            await self._move(Action.ANSWER_READY, "answered", outcome="answered")
            return "done"
        self._questions = list(result.get("questions") or [])
        self._branch_names = list(result.get("branchNames") or [])
        self._answers = {}
        if self._questions:
            await self._move(Action.FINDINGS_WITH_QUESTIONS, "questions")
            return "questions"
        nothing = (inv or {}).get("label") == "nothing_found"
        await self._move(Action.NOTHING_FOUND if nothing else Action.FINDINGS_WITHOUT_QUESTIONS,
                         "nothing_found" if nothing else "no_questions")
        return "ticket"

    def _fresh_opts(self) -> dict[str, Any]:
        return {k: self._options[k] for k in ("timeoutSeconds", "pollSeconds") if k in self._options}

    async def _ask(self) -> str:
        while not qmod.all_required_answered(self._questions, self._answers):
            msg = await self._next({"answer"}, remind="needs_input")
            try:
                qmod.apply_answer(self._questions, self._answers, str(msg.payload.get("questionId")),
                                  str(msg.payload.get("value", "")), branch_names=self._branch_names)
            except qmod.InvalidAnswer:
                await self._outcome_to(msg, {"status": "refused", "reason": "invalid_answer"})
                continue
            transition(self._state, Action.ANSWER)
            await self._act(acts.record_answer, {"questionId": msg.payload.get("questionId"),
                                                 "value": self._answers[str(msg.payload.get("questionId"))],
                                                 "actor": msg.payload.get("actor")})
            await self._outcome_to(msg, {"status": "accepted", "reason": None})
        await self._move(Action.ALL_ANSWERED, "answered")
        return "ticket"

    async def _draft(self) -> str:
        content = await self._await(self._act(acts.draft_ticket, timeout=timedelta(minutes=3)),
                                    defer=frozenset({"edit_ticket"}))
        rev = await self._act(acts.save_revision, {"content": content, "createdBy": "actron"})
        self._set_revision(rev)
        await self._await(self._act(acts.sync_ticket, {"n": rev["n"], "hash": rev["hash"]}),
                          defer=frozenset({"edit_ticket"}))
        await self._move(Action.TICKET_SAVED, "ticket_saved")
        return "approval"

    def _set_revision(self, rev: dict[str, Any]) -> None:
        self._revision = {"n": int(rev["n"]), "hash": str(rev["hash"])}
        self._target_branch = rev.get("targetBranch") or self._target_branch

    async def _edit(self, msg: _Msg) -> None:
        actor = msg.payload.get("actor") or {}
        rev = await self._act(acts.save_revision, {
            "content": msg.payload.get("content") or {}, "createdBy": actor.get("name") or actor.get("userId") or "person",
            "by": {"personId": None, "userId": actor.get("userId"), "name": actor.get("name")}})
        self._set_revision(rev)
        await self._act(acts.sync_ticket, {"n": rev["n"], "hash": rev["hash"]})
        await self._move(Action.EDIT_TICKET, "ticket_edited")
        await self._outcome_to(msg, {"status": "accepted", "reason": None, "revision": dict(self._revision or {})})

    async def _approval(self) -> str:
        while True:
            msg = await self._next({"approve_ticket", "edit_ticket"}, remind="awaiting_approval")
            if msg.name == "edit_ticket":
                await self._edit(msg)
                continue
            target = str(msg.payload.get("revisionHash") or "")
            current = (self._revision or {}).get("hash")
            reason = None
            if target != current:
                reason = "stale_revision"
            else:
                check = await self._act(acts.check_external_edit, {"hash": target})
                if check.get("externalEdit"):
                    reason = "external_edit"
            if reason:
                transition(self._state, Action.APPROVE_TICKET_REFUSED)
                await self._act(acts.record_approval, {
                    "kind": "ticket", "target": target, "status": "refused", "reason": reason,
                    "actor": msg.payload.get("actor"), "idempotencyKey": msg.payload.get("idempotencyKey"),
                    "state": self._state.value})
                continue
            transition(self._state, Action.APPROVE_TICKET)
            self._accepted_hash = target
            await self._act(acts.record_approval, {
                "kind": "ticket", "target": target, "status": "accepted", "reason": None,
                "actor": msg.payload.get("actor"), "idempotencyKey": msg.payload.get("idempotencyKey"),
                "state": State.BUILDING.value})
            await self._move(Action.APPROVE_TICKET, "approved")
            return "build"

    async def _wait_budget(self) -> None:
        while True:
            status = await self._act(acts.budget_check)
            if not status.get("reached"):
                return
            if self._state is State.BUILDING:
                transition(self._state, Action.BUDGET_REACHED)
            self._build = {**self._build, "status": "waiting_budget"}
            now = workflow.now()
            tomorrow = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
            wait_for = max(tomorrow - now, timedelta(seconds=1))
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self._cancel is not None or any(m.name == "budget_raised" for m in self._inbox),
                    timeout=wait_for)
            if self._cancel is not None:
                raise _Cancelled(self._cancel)
            self._inbox = [m for m in self._inbox if m.name != "budget_raised"]
            await self._act(acts.budget_resumed)

    async def _build_step(self) -> str:
        revision_build = self._state is State.CHANGES_REQUESTED
        await self._wait_budget()
        fresh = await self._await(self._act(acts.ensure_fresh, {"branch": self._target_branch, **self._fresh_opts()},
                                            timeout=timedelta(minutes=11), attempts=2))
        status = fresh.get("status")
        if status in ("stale", "missing_branch"):
            reason = "memory_stale" if status == "stale" else "missing_branch"
            return await self._build_failed(revision_build, reason, from_build=False)
        self._build_attempt += 1
        inp = await self._act(acts.prepare_build, {
            "revision": self._revision, "baseSha": fresh.get("sha"), "targetSha": fresh.get("targetSha"),
            "feedback": self._feedback, "attempt": self._build_attempt, "sameBranch": revision_build})
        build_id = str(inp["buildId"])
        self._build = {"status": "queued", "queuePosition": None, "id": build_id}
        handle = await workflow.start_child_workflow(
            "BuildWorkflow", inp, id=f"build:{build_id}", task_queue=str(self._options.get("buildQueue") or BUILD_QUEUE),
            cancellation_type=workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED,
            parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
        )
        self._build["status"] = "running"
        try:
            result = await self._await(handle, child=handle)
        except _Cancelled:
            await self._act(acts.mark_build_cancelled, {"buildId": build_id})
            raise
        except ChildWorkflowError as exc:
            result = {"status": "failed", "stopReason": f"build_error: {exc.cause or exc}"[:200]}
        result = dict(result) if isinstance(result, dict) else _as_dict(result)
        rec = await self._act(acts.record_build_result, {"buildId": build_id, "result": result,
                                                         "branch": inp.get("branch"),
                                                         "targetBranch": self._target_branch})
        self._build["status"] = rec.get("status")
        self._feedback = None
        if rec.get("status") == "passed":
            if rec.get("pr"):
                self._pr = dict(rec["pr"])
            self._start_merge_watch()
            await self._move(Action.REVISION_BUILD_PASSED if revision_build else Action.BUILD_PASSED, "build_passed")
            return "review"
        return await self._build_failed(revision_build, str(rec.get("stopReason") or "build_failed"), from_build=True)

    async def _build_failed(self, revision_build: bool, reason: str, *, from_build: bool) -> str:
        self._failed_step = "build"
        await self._move(Action.REVISION_BUILD_FAILED if revision_build else Action.BUILD_FAILED, reason,
                         data={"failedStep": "build", "attentionReason": reason}, flags={"fromBuild": from_build})
        return "attention"

    def _start_merge_watch(self) -> None:
        if self._watch is None and self._pr:
            self._watch = asyncio.ensure_future(self._merge_watch())

    async def _merge_watch(self) -> None:
        """A11: poll the PR every 2 minutes until it is merged or closed, then trigger the syncs."""
        while True:
            await workflow.sleep(MERGE_POLL)
            res = await self._act(acts.check_pr)
            state = res.get("state")
            if state in ("merged", "closed"):
                if self._pr is not None:
                    self._pr["state"] = state
                if state == "merged":
                    await self._act(acts.trigger_syncs)
                return

    async def _attention(self) -> str:
        msg = await self._next({"retry", "edit_ticket"})
        if msg.name == "edit_ticket":
            await self._edit(msg)
            return "approval"
        if self._failed_step == "build":
            await self._move(Action.RETRY_BUILD, "retry")
            return "build"
        await self._move(Action.RETRY_INVESTIGATION, "retry")
        return "investigate"

    async def _review(self) -> str:
        while True:
            msg = await self._next({"approve_pr", "pr_feedback", "close_pr"})
            if msg.name == "approve_pr":
                if await self._approve_pr(msg, str(msg.payload.get("headSha") or "")):
                    return "done"
                continue
            if msg.name == "close_pr":
                await self._act(acts.close_pr, {"reason": msg.payload.get("reason")})
                await self._move(Action.CLOSE_PR, str(msg.payload.get("reason") or "closed"), outcome="closed",
                                 by=msg.payload.get("actor"))
                return "done"
            kind = (await self._act(acts.classify_feedback, {"text": msg.payload.get("text", "")})).get("kind")
            if kind == "approval":
                head = await self._act(acts.read_pr_head)
                if await self._approve_pr(msg, str(head.get("headSha") or "")):
                    return "done"
                continue
            if kind == "code_change_within_scope":
                self._feedback = str(msg.payload.get("text", ""))
                await self._move(Action.FEEDBACK_CODE_CHANGE, "changes_requested")
                return "build"
            if kind == "scope_change":
                self._failed_step = "build"
                await self._move(Action.FEEDBACK_SCOPE_CHANGE, "scope_change",
                                 data={"failedStep": "build", "attentionReason": "scope_change"})
                return "attention"
            transition(self._state, Action.FEEDBACK_QUESTION)
            await self._act(acts.answer_feedback, {"text": msg.payload.get("text", "")},
                            timeout=timedelta(minutes=3))

    async def _approve_pr(self, msg: _Msg, head_sha: str) -> bool:
        head = await self._act(acts.read_pr_head)
        current = str(head.get("headSha") or (self._pr or {}).get("headSha") or "")
        actor = msg.payload.get("actor")
        key = msg.payload.get("idempotencyKey")
        if not head_sha or head_sha != current:
            transition(self._state, Action.APPROVE_PR_REFUSED)
            await self._act(acts.record_approval, {"kind": "pr", "target": head_sha, "status": "refused",
                                                   "reason": "stale_head", "actor": actor, "idempotencyKey": key,
                                                   "state": self._state.value})
            return False
        transition(self._state, Action.APPROVE_PR)
        await self._act(acts.record_approval, {"kind": "pr", "target": head_sha, "status": "accepted", "reason": None,
                                               "actor": actor, "idempotencyKey": key, "state": State.DONE.value})
        await self._act(acts.trigger_syncs)
        try:
            await workflow.execute_child_workflow(
                "WritebackWorkflow",
                {**self._ids(), "buildId": self._build.get("id"), "prNumber": (self._pr or {}).get("number"),
                 "headSha": head_sha},
                id=f"writeback:{self._rid}", task_queue=workflow.info().task_queue,
            )
        except ChildWorkflowError as exc:
            workflow.logger.warning("write-back failed: %s", exc)
        await self._move(Action.APPROVE_PR, "pr_approved", outcome="approved")
        return True

    async def _finish_cancel(self, msg: _Msg) -> None:
        try:
            await self._move(Action.CANCEL, str(msg.payload.get("reason") or "cancelled"), outcome="cancelled",
                             by=msg.payload.get("actor"))
        except InvalidTransition:
            return


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        out: dict[str, Any] = value.model_dump(mode="json", by_alias=True)
        return out
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"status": "failed", "stopReason": "unreadable build result"}


WORKFLOWS = [RequestWorkflow]
