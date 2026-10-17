"""Durable Slack workflow with separate scope and current-commit authorization gates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from actron.contracts import (
    Payload,
    PullRequests,
    Rejected,
    Slack,
    Store,
    Tickets,
    Unavailable,
    UnknownOutcome,
    Worker,
    canonical,
    digest,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Workflow:
    def __init__(
        self,
        store: Store,
        slack: Slack,
        tickets: Tickets,
        prs: PullRequests,
        worker: Worker | None,
        investigator: Any,
        config: Payload,
    ) -> None:
        self.store, self.slack, self.tickets = store, slack, tickets
        self.prs, self.worker, self.investigator, self.config = prs, worker, investigator, config

    def handle(self, event: Payload) -> Payload:
        """Consume one normalized Slack input. Repeated inputs resume durable operations."""
        if not all(event.get(k) for k in ("id", "type", "channel", "user")):
            raise Rejected("Slack input requires id, type, channel and user")
        request_id = event.get("request") or "req-" + digest([event["channel"], event["id"]])[:24]
        state: Payload = {}
        try:
            with self.store.lock("request:" + request_id):
                state = self.store.get("Request", request_id) or {}
                receipt = self.store.get("Event", event["id"])
                if receipt and receipt.get("request") != request_id:
                    raise Rejected("Event identity already belongs to another request")
                if receipt and receipt.get("fingerprint") != digest(event):
                    raise Rejected("Event identity was reused with changed input")
                if receipt and receipt.get("complete"):
                    return state
                if event["id"] in state.get("completed_events", []):
                    self.store.put(
                        "Event",
                        event["id"],
                        {
                            "id": event["id"],
                            "request": request_id,
                            "complete": True,
                            "completed": now(),
                            "fingerprint": digest(event),
                        },
                    )
                    return state
                self.store.put(
                    "Event",
                    event["id"],
                    {
                        "id": event["id"],
                        "request": request_id,
                        "complete": False,
                        "received": now(),
                        "fingerprint": digest(event),
                    },
                )
                if not state:
                    if event["type"] not in ("request", "investigate"):
                        raise Rejected("Unknown request")
                    state = {
                        "id": request_id,
                        "channel": event["channel"],
                        "user": event["user"],
                        "phase": "investigating",
                        "objective": event.get("text", ""),
                        "project": event.get("project", "atlas"),
                        "behavior": event.get("behavior", "report-export"),
                        "repo": event.get("repo", self.config.get("repository", "")),
                        "base": event.get("base", self.config.get("base", "")),
                        "created": now(),
                        "revision": 0,
                        "repairs": 0,
                        "runs": [],
                    }
                    self._save(state)
                if event["channel"] != state["channel"]:
                    raise Rejected("Interaction channel does not match the request")
                if not state.get("thread"):
                    # A durable request exists before Slack is contacted. A lost acknowledgement
                    # may need thread reconciliation, but must never create another ticket/worker.
                    text = f"Request {request_id} received. Investigating connected evidence."
                    start = getattr(self.slack, "start", None)
                    state["thread"] = (
                        start(state["channel"], request_id, text)
                        if start
                        else self.slack.post(state["channel"], text)
                    )
                    self._save(state)
                action = event["type"]
                if state.get("pending") and not receipt and action not in ("recover", "status"):
                    raise Rejected(
                        "An unresolved operation owns this request; recover it before changing work"
                    )
                if receipt and state.get("pending"):
                    self._recover(state)
                elif action in ("request", "investigate"):
                    self._investigate(state, action == "investigate")
                elif action == "clarify":
                    self._clarify(state, event)
                elif action == "revise":
                    self._revise(state, event)
                elif action == "approve":
                    self._approve(state, event)
                elif action in ("execute", "repair"):
                    self._execute(state, event)
                elif action == "review":
                    self._review(state, event)
                elif action == "authorize_merge":
                    self._authorize_merge(state, event)
                elif action == "recover":
                    self._recover(state)
                elif action == "status":
                    self._say(
                        state,
                        f"Current durable state: {state['phase']}; revision {state['revision']}.",
                    )
                else:
                    raise Rejected("Unsupported Slack action")
                state.pop("error", None)
                state.pop("blocked", None)
                state.setdefault("completed_events", []).append(event["id"])
                self._save(state)
                self.store.put(
                    "Event",
                    event["id"],
                    {
                        "id": event["id"],
                        "request": request_id,
                        "complete": True,
                        "completed": now(),
                        "fingerprint": digest(event),
                    },
                )
        except UnknownOutcome as exc:
            state["phase"] = "reconciling"
            state["error"] = str(exc)
            self._save(state)
            self._say(
                state,
                f"Provider outcome unknown: {exc}. Recover will reconcile the existing operation.",
            )
        except Rejected as exc:
            state["error"] = str(exc)
            self._save(state)
            self._say({**event, **state}, f"Action rejected: {exc}")
        except Unavailable as exc:
            # Graph failure must not be replaced by a fixture or model-generated policy answer.
            state["error"] = str(exc)
            state["blocked"] = True
            try:
                self._say({**event, **state}, f"Dependency unavailable; work paused: {exc}")
            except Unavailable:
                pass
        return state

    def _save(self, state: Payload) -> None:
        if state.get("id"):
            state["updated"] = now()
            self.store.put("Request", state["id"], state)

    def _say(self, state: Payload, text: str, blocks: list[Payload] | None = None) -> bool:
        display = (
            text
            if len(text) <= 12000
            else text[:12000]
            + "\n[Truncated for Slack; complete results retained in graph/run artifacts.]"
        )
        state["message"] = text
        if blocks:
            # With Block Kit, Slack displays blocks and uses text as a fallback.
            sections = [
                {"type": "section", "text": {"type": "plain_text", "text": display[i : i + 2900]}}
                for i in range(0, len(display), 2900)
            ]
            blocks = sections + blocks
        try:
            self.slack.post(state["channel"], display, state.get("thread"), blocks)
        except Unavailable as exc:
            state["notification_error"] = str(exc)
            return False
        state.pop("notification_error", None)
        return True

    def _evidence(self, state: Payload) -> Payload:
        result: Payload = self.investigator.evidence(
            state["project"], state["behavior"], state["repo"], state["base"]
        )
        return result

    def _investigate(self, state: Payload, read_only: bool) -> None:
        evidence = self._evidence(state)
        self.store.put("Evidence", state["id"] + ":" + evidence["fingerprint"], evidence)
        details = self._describe(evidence)
        if read_only:
            if state["phase"] in ("investigating", "investigated"):
                state["phase"] = "investigated"
                state["evidence"] = evidence
            else:
                state["latest_investigation"] = evidence
            self._say(state, details)
            return
        state["evidence"] = evidence
        if (
            evidence.get("conflict")
            or evidence.get("critical_gaps")
            or not evidence.get("decisions")
        ):
            state["phase"] = "clarification"
            self._say(
                state,
                details + "\nShould report export expand to admins of the owning project "
                "while invoices remain Finance-only? Confirm project membership and deny cross-project access. "
                "Missing critical evidence must be refreshed before execution.",
            )
        else:
            # The permission expansion requires an explicit membership decision even when
            # historical source extraction cannot prove a conflict.
            if "admin" in state["objective"].lower() and not state.get("membership"):
                state["phase"] = "clarification"
                self._say(
                    state,
                    details + "\nConfirm owning-project admin membership, cross-project denial, "
                    "and preserved invoice restrictions before proposing implementation.",
                )
            else:
                self._propose(state, {})

    @staticmethod
    def _describe(evidence: Payload) -> str:
        lines = ["Connected evidence (bounded dependency coverage):"]
        for label, key in (
            ("Approved", "decisions"),
            ("Unapproved proposal", "proposals"),
            ("Historical", "historical"),
        ):
            for item in evidence.get(key, []):
                lines.append(f"{label}: {item.get('text', item.get('decision', item))}")
        for source in evidence.get("sources", []):
            lines.append(
                f"Source: {source.get('locator', source.get('id'))} "
                f"revision {source.get('revision', source.get('hash', 'unknown'))} "
                f"availability {source.get('availability', 'unknown')}"
            )
        for component in evidence.get("components", []):
            lines.append(
                f"Impact: {component.get('path', component.get('id'))} "
                f"({component.get('method', 'unresolved')}) {component.get('behaviors', [])}"
            )
        lines.append(f"Repository snapshot: {evidence.get('snapshot')}")
        lines.append(f"Selected checks: {[c.get('id') for c in evidence.get('checks', [])]}")
        lines.extend("Coverage gap: " + str(gap) for gap in evidence.get("gaps", []))
        return "\n".join(lines)

    def _clarify(self, state: Payload, event: Payload) -> None:
        if state["phase"] != "clarification":
            raise Rejected("Request is not awaiting clarification")
        clarification = {
            "id": event["id"],
            "request": state["id"],
            "user": event["user"],
            "text": event.get("text", ""),
            "scope": event.get("scope", {}),
            "time": now(),
            "evidence": state["evidence"]["fingerprint"],
        }
        self.store.put("Clarification", event["id"], clarification)
        self.store.link("Request", state["id"], "CLARIFIED_BY", "Clarification", event["id"], {})
        scope = event.get("scope", {})
        if (
            "admin" in state["objective"].lower()
            and scope.get("membership") != "owning-project-only"
        ):
            self._say(
                state,
                "Clarification recorded. Set membership to owning-project-only and provide "
                "acceptance criteria; project membership remains unresolved.",
            )
            return
        state["membership"] = scope.get("membership")
        state["clarification"] = event["id"]
        state["evidence"] = self._evidence(state)
        self._propose(state, scope)

    def _scope(self, state: Payload, changes: Payload) -> Payload:
        evidence = state["evidence"]
        previous = state.get("scope", {})
        # The requested behavior is the explicitly reviewed policy change. Preserve
        # independent impacted decisions, rather than preserving the rule being replaced.
        independent = [
            d["text"]
            for d in evidence.get("decisions", [])
            if d.get("behavior") != state["behavior"]
        ]
        constraints = list(
            dict.fromkeys(
                independent + previous.get("constraints", []) + changes.get("constraints", [])
            )
        )
        return {
            "objective": changes.get("objective", previous.get("objective", state["objective"])),
            "acceptance": changes.get(
                "acceptance", previous.get("acceptance", [state["objective"]])
            ),
            "constraints": constraints,
            "components": evidence.get("components", []),
            "evidence": evidence.get("sources", []),
            "checks": evidence.get("checks", []),
            "unresolved": changes.get("unresolved", previous.get("unresolved", [])),
            "project": state["project"],
            "behavior": state["behavior"],
            "repo": state["repo"],
            "base": state["base"],
            "membership": changes.get("membership", state.get("membership")),
        }

    def _propose(self, state: Payload, changes: Payload) -> None:
        scope = self._scope(state, changes)
        self._new_revision(state, scope)
        operation = f"ticket:{state['id']}:{state['revision']}"
        kind = "ticket_update" if state.get("ticket") else "ticket_create"
        self._pending(state, kind, operation)
        if kind == "ticket_create":
            issue = self.tickets.find(operation) or self.tickets.create(operation, scope)
        else:
            issue = self.tickets.update(state["ticket"]["id"], scope)
        self._ticket_confirmed(state, issue)

    def _new_revision(self, state: Payload, scope: Payload) -> None:
        state["revision"] += 1
        state["scope"], state["scope_hash"] = scope, digest(scope)
        state.pop("approval", None)
        state.pop("merge_authorization", None)
        existing = self.store.get("Revision", f"{state['id']}:{state['revision']}")
        while existing and existing["hash"] != state["scope_hash"]:
            state["revision"] += 1
            existing = self.store.get("Revision", f"{state['id']}:{state['revision']}")
        revision = existing or {
            "id": f"{state['id']}:{state['revision']}",
            "request": state["id"],
            "revision": state["revision"],
            "scope": scope,
            "hash": state["scope_hash"],
            "base": state["base"],
            "evidence": state["evidence"]["fingerprint"],
            "created": now(),
        }
        if not existing:
            self.store.put("Revision", revision["id"], revision)
        self.store.link("Request", state["id"], "HAS_REVISION", "Revision", revision["id"], {})
        for handoff in self.store.list("Handoff"):
            if handoff["request"] == state["id"] and handoff["status"] in ("ready", "queued"):
                handoff["status"] = "cancelled"
                self.store.put("Handoff", handoff["id"], handoff)

    def _ticket_confirmed(self, state: Payload, issue: Payload) -> None:
        if digest(issue.get("scope")) != state["scope_hash"]:
            raise UnknownOutcome("Linear content does not match the proposed scope")
        state["ticket"] = issue
        self._confirmed(state, issue)
        state["phase"] = "awaiting_approval"
        self._save(state)
        self._present(state)

    def _present(self, state: Payload) -> None:
        value = {"request": state["id"], "revision": state["revision"], "hash": state["scope_hash"]}
        blocks = self._button("Approve this revision", "approve", value)
        scope = state["scope"]
        if (
            "admin" in scope.get("objective", "").lower()
            and scope.get("membership") != "owning-project-only"
        ):
            raise Rejected("Project-admin scope must resolve owning-project membership")
        summary = {
            key: scope.get(key)
            for key in (
                "objective",
                "acceptance",
                "constraints",
                "unresolved",
                "membership",
                "repo",
                "base",
            )
        }
        summary["components"] = [c.get("path", c.get("id")) for c in scope.get("components", [])]
        summary["checks"] = [c.get("id") for c in scope.get("checks", [])]
        if len(canonical(summary)) > 10000:
            raise Rejected("Scope is too large for exact Slack review; shorten its criteria")
        self._pending(state, "present", f"present:{state['id']}:{state['revision']}")
        displayed = self._say(
            state,
            f"Ticket {state['ticket']['url']} — revision {state['revision']} "
            f"SHA-256 {state['scope_hash']}. Awaiting explicit approval.\n{canonical(summary)}",
            blocks,
        )
        if not displayed:
            raise UnknownOutcome("Ticket exists but Slack revision presentation is unconfirmed")
        state["presented_revision"] = state["revision"]
        state["phase"] = "awaiting_approval"
        self._confirmed(state, {"presented_revision": state["revision"]})
        self._save(state)

    @staticmethod
    def _button(text: str, action: str, value: Payload) -> list[Payload]:
        return [
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": action,
                        "text": {"type": "plain_text", "text": text},
                        "value": canonical(value),
                    }
                ],
            }
        ]

    def _revise(self, state: Payload, event: Payload) -> None:
        if state["phase"] in ("executing", "merging", "merged"):
            raise Rejected("Scope cannot be changed during execution or after merge")
        changes = event.get("scope")
        if not changes or not isinstance(changes, dict):
            raise Rejected("Revision requires inspectable scope changes")
        state["evidence"] = self._evidence(state)
        self._propose(state, changes)

    def _identity(self, event: Payload, interaction: bool = False) -> None:
        if not self.config.get("demo_user") or not self.config.get("demo_channel"):
            raise Rejected("Configure the explicit POC user/channel binding before authorization")
        if (
            event["user"] != self.config["demo_user"]
            or event["channel"] != self.config["demo_channel"]
        ):
            raise Rejected("Interaction does not match the configured POC identity binding")
        if interaction and not (
            event.get("trusted_slack") is True and event.get("interaction") is True
        ):
            raise Rejected("Authorization requires a verified current Slack button interaction")

    def _refresh_scope(self, state: Payload) -> None:
        current = self.tickets.read(state["ticket"]["id"])
        if digest(current.get("scope")) != state["scope_hash"]:
            self._new_revision(state, current["scope"])
            state["ticket"] = current
            state["phase"] = "awaiting_approval"
            self._present(state)
            raise Rejected("Linear changed externally; approve the newly displayed exact revision")

    def _approve(self, state: Payload, event: Payload) -> None:
        self._identity(event, interaction=True)
        if state["phase"] != "awaiting_approval":
            raise Rejected("No ticket revision is awaiting approval")
        self._refresh_scope(state)
        if (event.get("revision"), event.get("hash")) != (state["revision"], state["scope_hash"]):
            raise Rejected("Approval references a stale revision or scope hash")
        if state.get("presented_revision") != state["revision"]:
            raise Rejected("The current revision has not been presented in Slack")
        if state["scope"].get("unresolved"):
            raise Rejected("Resolve consequential scope questions before approval")
        scope = state["scope"]
        if any(scope.get(key) != state[key] for key in ("project", "behavior", "repo", "base")):
            raise Rejected("External ticket identity/base differs from the investigated request")
        independent = [
            d["text"]
            for d in state["evidence"].get("decisions", [])
            if d.get("behavior") != state["behavior"]
        ]
        if not set(independent) <= set(scope.get("constraints", [])):
            raise Rejected("Ticket removed a preserved independent constraint")
        if {c["id"] for c in scope.get("checks", [])} != {
            c["id"] for c in state["evidence"].get("checks", [])
        }:
            raise Rejected("Ticket changed the evidence-selected validation plan")
        approval = {
            "id": event["id"],
            "request": state["id"],
            "revision": state["revision"],
            "hash": state["scope_hash"],
            "base": state["base"],
            "repo": state["repo"],
            "user": event["user"],
            "time": now(),
            "evidence": state["evidence"]["fingerprint"],
        }
        self.store.put("Approval", event["id"], approval)
        self.store.link(
            "Revision",
            f"{state['id']}:{state['revision']}",
            "APPROVED_BY",
            "Approval",
            event["id"],
            {},
        )
        state["approval"], state["phase"] = approval, "approved"
        handoff = f"execute:{state['id']}:{state['revision']}"
        self.store.put(
            "Handoff",
            handoff,
            {
                "id": handoff,
                "request": state["id"],
                "approval": event["id"],
                "revision": state["revision"],
                "status": "ready",
            },
        )
        self._say(
            state,
            f"Revision {state['revision']} approved for base {state['base']}. Execution queued.",
        )

    def _ready(self, state: Payload) -> None:
        self._refresh_scope(state)
        approval = state.get("approval", {})
        if (
            approval.get("hash") != state["scope_hash"]
            or approval.get("base") != state["base"]
            or approval.get("repo") != state["repo"]
            or approval.get("revision") != state["revision"]
            or approval.get("evidence") != state["evidence"]["fingerprint"]
        ):
            raise Rejected("Exact current scope and base require approval")
        fresh = self._evidence(state)
        if fresh["fingerprint"] != state["evidence"]["fingerprint"]:
            state["phase"] = "clarification"
            state.pop("approval", None)
            state["evidence"] = fresh
            raise Rejected("Evidence changed; refresh scope and obtain renewed approval")
        snapshot = fresh.get("snapshot", {})
        if snapshot.get("commit") != state["base"] or snapshot.get("repo") != state["repo"]:
            raise Rejected("Repository evidence is missing or mixes incompatible snapshots")
        if not fresh.get("checks") or not fresh.get("decisions"):
            raise Rejected("Critical decision or validation evidence is missing")
        critical = fresh.get("critical_gaps", [])
        if critical:
            raise Rejected("Critical evidence gaps: " + "; ".join(critical))

    def _pending(self, state: Payload, kind: str, operation: str, **fields: Any) -> None:
        pending = dict(
            id=operation, kind=kind, request=state["id"], status="pending", time=now(), **fields
        )
        self.store.put("Operation", operation, pending)
        state["pending"] = pending
        self._save(state)

    def _confirmed(self, state: Payload, result: Payload) -> None:
        pending = state.pop("pending", None)
        if pending:
            pending.update(status="confirmed", result=result, completed=now())
            self.store.put("Operation", pending["id"], pending)

    def _execute(self, state: Payload, event: Payload, feedback: str = "") -> None:
        if state["phase"] not in ("approved", "failed", "reviewing"):
            raise Rejected("No approved execution is ready")
        self._ready(state)
        if self.worker is None:
            raise Unavailable("No real coding worker configured")
        if state["phase"] == "failed":
            if state["repairs"] >= int(self.config.get("max_repairs", 2)):
                raise Rejected("Repair attempt limit exhausted")
            state["repairs"] += 1
        operation = f"worker:{state['id']}:{state['revision']}:{len(state['runs'])}"
        base = state.get("run", {}).get("commit") or state["base"]
        effective_feedback = feedback or event.get("text", "")
        self._pending(state, "worker", operation, base=base, feedback=effective_feedback)
        handoff_id = f"execute:{state['id']}:{state['revision']}"
        handoff = self.store.get("Handoff", handoff_id)
        if handoff:
            handoff.update(status="executing", operation=operation)
            self.store.put("Handoff", handoff_id, handoff)
        state["phase"] = "executing"
        self._save(state)
        self._say(
            state,
            f"Executing approved revision {state['revision']} at {base}; preserving constraint tests.",
        )
        execution_evidence = dict(state["evidence"])
        if state.get("run", {}).get("branch"):
            execution_evidence["_execution_branch"] = state["run"]["branch"]
        result = self.worker.find(operation) or self.worker.run(
            operation, state["scope"], execution_evidence, base, effective_feedback
        )
        self._worker_confirmed(state, result)

    def _worker_confirmed(self, state: Payload, result: Payload) -> None:
        if result.get("status") in ("running", "unknown"):
            raise UnknownOutcome(
                "Worker ownership exists; reconcile instead of starting another worker"
            )
        self._confirmed(state, result)
        handoff_id = f"execute:{state['id']}:{state['revision']}"
        handoff = self.store.get("Handoff", handoff_id)
        if handoff:
            handoff.update(status="done", result=result.get("status"))
            self.store.put("Handoff", handoff_id, handoff)
        state["run"] = result
        if not any(run.get("operation") == result.get("operation") for run in state["runs"]):
            state["runs"].append(result)
        run_id = result.get("operation", state["id"] + ":run")
        self.store.put("Run", run_id, result)
        self.store.link(
            "Revision", f"{state['id']}:{state['revision']}", "IMPLEMENTED_BY", "Run", run_id, {}
        )
        if result.get("status") == "scope_revision":
            state["phase"] = "clarification"
            state.pop("approval", None)
            self._say(
                state,
                "Worker requires product scope changes. Clarify and approve a new revision. "
                + result.get("output", ""),
            )
            return
        checks = result.get("checks", [])
        suite = [
            c for c in checks if c.get("kind") == "suite" and c.get("head") == result.get("commit")
        ]
        passed = (
            result.get("status") == "succeeded"
            and result.get("commit")
            and suite
            and all(c.get("exit_code") == 0 for c in checks)
            and all(
                c.get("head") == result["commit"] for c in checks if c.get("kind") != "baseline"
            )
        )
        if not passed:
            state["phase"] = "failed"
            self._save(state)
            self._say(
                state,
                f"Implementation failed. Actual run {run_id}, commit {result.get('commit')}. "
                f"Checks: {canonical(checks)}. Repair budget remaining: "
                f"{max(0, int(self.config.get('max_repairs', 2)) - state['repairs'])}.",
            )
            return
        state["phase"] = "validated"
        state.pop("merge_authorization", None)
        self._save(state)
        self._say(state, f"Tested commit {result['commit']}; actual checks: {canonical(checks)}")
        self._open_pr(state)

    def _open_pr(self, state: Payload) -> None:
        self._ready(state)
        operation = f"pr:{state['id']}"
        self._pending(state, "pr", operation)
        # create is an upsert at the provider boundary: an existing operation's PR
        # receives the newly validated branch, without creating a second PR.
        pr_scope = dict(
            state["scope"],
            ticket=state["ticket"]["url"],
            revision=state["revision"],
            scope_hash=state["scope_hash"],
            request=state["id"],
        )
        pr = self.prs.create(operation, state["run"], pr_scope)
        self._pr_confirmed(state, pr)

    def _pr_confirmed(self, state: Payload, pr: Payload) -> None:
        if pr.get("head") != state["run"]["commit"]:
            raise UnknownOutcome("PR does not yet identify the tested worker commit")
        self._confirmed(state, pr)
        state["pr"], state["phase"] = pr, "reviewing"
        self.store.put("PullRequest", state["id"], pr)
        self._save(state)
        self._merge_button(state)

    def _merge_button(self, state: Payload) -> None:
        pr = state["pr"]
        value = {
            "request": state["id"],
            "revision": state["revision"],
            "hash": state["scope_hash"],
            "pr": pr["id"],
            "head": pr["head"],
        }
        self._say(
            state,
            f"Confirmed PR {pr['url']}, head {pr['head']}. "
            f"Current provider checks: {canonical(pr.get('checks', []))}. "
            "Merge requires current-head checks/reviews and explicit authorization.",
            self._button("Authorize this head", "authorize_merge", value),
        )

    def _review(self, state: Payload, event: Payload) -> None:
        if state["phase"] != "reviewing":
            raise Rejected("No PR is awaiting review")
        pr = self.prs.read(state["pr"]["id"])
        if event.get("pr") != pr["id"] or event.get("head") != pr["head"]:
            raise Rejected("Review feedback references another PR or stale commit")
        self.store.put(
            "Feedback",
            event["id"],
            {
                "id": event["id"],
                "request": state["id"],
                "pr": pr["id"],
                "head": pr["head"],
                "text": event.get("text", ""),
                "time": now(),
            },
        )
        if event.get("scope"):
            state["evidence"] = self._evidence(state)
            self._propose(state, event["scope"])
            return
        if pr["head"] != state["run"]["commit"]:
            raise Rejected("PR head changed outside the validated worker output")
        state.pop("merge_authorization", None)
        self._execute(state, event, event.get("text", ""))

    def _authorize_merge(self, state: Payload, event: Payload) -> None:
        self._identity(event, interaction=True)
        if state["phase"] != "reviewing":
            raise Rejected("No reviewed PR is awaiting merge")
        self._ready(state)
        pr = self.prs.read(state["pr"]["id"])
        if (event.get("revision"), event.get("hash"), event.get("pr"), event.get("head")) != (
            state["revision"],
            state["scope_hash"],
            pr["id"],
            pr["head"],
        ):
            state.pop("merge_authorization", None)
            raise Rejected("Authorization is stale for the current scope, PR or head")
        if pr["head"] != state["run"]["commit"]:
            raise Rejected("The current head has no matching actual local validation")
        required = pr.get("required_checks", [])
        if not required or not pr.get("checks_complete") or not pr.get("reviews_complete"):
            raise Rejected("Required check/review information is missing or incomplete")
        for name in required:
            matching = [
                c
                for c in pr.get("checks", [])
                if c.get("name") == name and c.get("head") == pr["head"]
            ]
            if not matching or any(c.get("status") != "success" for c in matching):
                raise Rejected(f"Required current-head check {name} is missing, pending or failed")
        latest: dict[str, Payload] = {}
        for review in pr.get("reviews", []):
            if review.get("head") == pr["head"]:
                latest[review.get("user", "")] = review
        if any(r.get("state") == "CHANGES_REQUESTED" for r in latest.values()):
            raise Rejected("Current-head review requests changes")
        approvals = sum(r.get("state") == "APPROVED" for r in latest.values())
        if approvals < max(1, int(pr.get("reviews_required", 0))):
            raise Rejected("Required current-head approvals are missing")
        authorization = {
            "id": event["id"],
            "request": state["id"],
            "revision": state["revision"],
            "hash": state["scope_hash"],
            "pr": pr["id"],
            "head": pr["head"],
            "user": event["user"],
            "time": now(),
            "validation": state["run"],
            "provider_validation": pr,
        }
        self.store.put("MergeAuthorization", event["id"], authorization)
        state["merge_authorization"] = authorization
        self._pending(
            state, "merge", f"merge:{state['id']}:{pr['head']}", head=pr["head"], pr=pr["id"]
        )
        state["phase"] = "merging"
        self._save(state)
        result = self.prs.merge(pr["id"], pr["head"])
        self._merge_confirmed(state, result)

    def _merge_confirmed(self, state: Payload, result: Payload) -> None:
        auth = state.get("merge_authorization", {})
        if (
            not result.get("merged")
            or not result.get("merge_commit")
            or result.get("head") != auth.get("head")
        ):
            raise UnknownOutcome("Merge outcome has not been confirmed for the authorized head")
        self._confirmed(state, result)
        state["pr"], state["phase"] = result, "merged"
        outcome = {
            "id": "outcome:" + state["id"],
            "project": state["project"],
            "behavior": state["behavior"],
            "scope": state["scope"],
            "decision": state["scope"]["objective"],
            "supersedes": [
                d["id"]
                for d in state["evidence"].get("decisions", [])
                if d.get("behavior") == state["behavior"] and d.get("id")
            ],
            "request": state["id"],
            "pr": result["id"],
            "head": auth["head"],
            "merge_commit": result["merge_commit"],
            "merged": True,
            "revision": state["revision"],
            "evidence": state["evidence"],
            "time": now(),
        }
        self.store.put("Outcome", outcome["id"], outcome)
        self.store.link("Request", state["id"], "RESULTED_IN", "Outcome", outcome["id"], {})
        self._save(state)
        self._say(
            state,
            f"Confirmed merge {result['merge_commit']} for authorized head {auth['head']}. "
            "The scoped decision and preserved constraints are available to later investigations.",
        )

    def _recover(self, state: Payload) -> None:
        pending = state.get("pending")
        if not pending:
            if (
                state["phase"] == "awaiting_approval"
                and state.get("presented_revision") != state["revision"]
            ):
                self._present(state)
            elif state["phase"] == "validated":
                self._open_pr(state)
            elif state["phase"] == "reviewing":
                self._merge_button(state)
            else:
                self._say(state, f"Resumed durable state: {state['phase']}.")
            return
        kind, operation = pending["kind"], pending["id"]
        if kind == "present":
            self._present(state)
        elif kind == "ticket_create":
            issue = self.tickets.find(operation)
            if issue is None:
                issue = self.tickets.create(operation, state["scope"])
            self._ticket_confirmed(state, issue)
        elif kind == "ticket_update":
            issue = self.tickets.read(state["ticket"]["id"])
            if digest(issue.get("scope")) != state["scope_hash"]:
                # Concurrent external edits must be reviewed; never overwrite them during recovery.
                self._new_revision(state, issue["scope"])
            self._ticket_confirmed(state, issue)
        elif kind == "worker":
            if self.worker is None:
                raise Unavailable("Worker unavailable for reconciliation")
            result = self.worker.find(operation)
            if result is None:
                # Persisted handoff may precede process creation. The worker itself must claim
                # this same operation atomically before starting work.
                self._ready(state)
                execution_evidence = dict(state["evidence"])
                if state.get("run", {}).get("branch"):
                    execution_evidence["_execution_branch"] = state["run"]["branch"]
                result = self.worker.run(
                    operation,
                    state["scope"],
                    execution_evidence,
                    pending["base"],
                    pending.get("feedback", ""),
                )
            self._worker_confirmed(state, result)
        elif kind == "pr":
            pr = self.prs.find(operation)
            if pr is None or pr.get("head") != state["run"]["commit"]:
                self._ready(state)
                pr_scope = dict(
                    state["scope"],
                    ticket=state["ticket"]["url"],
                    revision=state["revision"],
                    scope_hash=state["scope_hash"],
                    request=state["id"],
                )
                pr = self.prs.create(operation, state["run"], pr_scope)
            self._pr_confirmed(state, pr)
        elif kind == "merge":
            pr = self.prs.read(pending["pr"])
            if pr.get("merged"):
                self._merge_confirmed(state, pr)
            elif pr.get("head") != pending["head"]:
                self._confirmed(state, {"status": "rejected", "reason": "head changed"})
                state.pop("merge_authorization", None)
                state["phase"] = "reviewing"
                self._say(
                    state,
                    "Recovery found a changed head; obtain fresh validation and authorization.",
                )
            else:
                # Do not blindly repeat an uncertain merge, even if it remains open.
                raise UnknownOutcome(
                    "Merge remains open/unknown; refresh prerequisites and reauthorize explicitly"
                )
        else:
            raise Rejected("Unrecognized pending operation")
