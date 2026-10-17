"""Drive Slack inputs; observe real graph, provider effects and repository results."""

import os
import uuid
from pathlib import Path

import pytest

from actron.workflow import Workflow
from tests.fakes import GitHubFixture, LinearFixture, SlackFixture


def test_request_acknowledges_graph_evidence_and_requires_clarification(tmp_path: Path) -> None:
    import json

    from actron.connectors import FileSource
    from actron.graph import FalkorStore
    from actron.ingestion import Ingestor, Investigator

    graph = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), "test_" + uuid.uuid4().hex
    )
    record = {
        "id": "slack:policy",
        "provider": "slack",
        "revision": "1",
        "project": "atlas",
        "behavior": "report-export",
        "content": "Report exports are Finance-only.",
        "locator": "fixture://slack/policy",
        "timestamp": "2026-10-01T00:00:00Z",
        "availability": "available",
        "claims": [
            {
                "id": "report-policy",
                "text": "Finance-only exports",
                "status": "approved",
                "behavior": "report-export",
                "approval": {
                    "actor": "person:finance",
                    "source": "fixture://slack/approval",
                    "revision": "1",
                },
            }
        ],
    }
    source = tmp_path / "sources.json"
    source.write_text(json.dumps([record]))
    Ingestor(graph).sync("history", FileSource(source))
    slack, linear, github = SlackFixture(), LinearFixture(), GitHubFixture()
    workflow = Workflow(
        graph,
        slack,
        linear,
        github,
        None,
        Investigator(graph),
        {"demo_user": "U1", "demo_channel": "C1"},
    )
    state = workflow.handle(
        {
            "id": "evt1",
            "type": "request",
            "channel": "C1",
            "user": "U1",
            "project": "atlas",
            "behavior": "report-export",
            "repo": "demo/repo",
            "base": "a" * 40,
            "text": "Allow project admins to export reports",
        }
    )
    assert state["phase"] == "clarification"
    assert len(slack.messages) >= 2
    assert "Finance" in slack.messages[-1]["text"]
    assert not linear.issues
    assert state["evidence"]["decisions"]


@pytest.fixture
def system(tmp_path: Path):
    import json

    from actron.connectors import FileSource
    from actron.graph import FalkorStore
    from actron.ingestion import Ingestor, Investigator
    from actron.worker import LocalRunner, RepositoryWorker
    from tests.fakes import StimulusCoding
    from tests.test_worker import repository

    repo, base = repository(tmp_path)
    graph = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), "workflow_" + uuid.uuid4().hex
    )
    history = json.loads((Path(__file__).parents[1] / "demo/sources/history.json").read_text())[
        "records"
    ]
    mapping = json.loads((Path(__file__).parents[1] / "demo/sources/code-map.json").read_text())
    history.append(
        {
            "id": "code",
            "provider": "github",
            "revision": base,
            "project": "atlas",
            "content": "Synthetic repository snapshot",
            "locator": repo.as_uri(),
            "snapshot": {
                "repo": str(repo),
                "commit": base,
                "components": mapping["components"],
                "checks": mapping["checks"],
                "gaps": mapping["gaps"],
            },
        }
    )
    source = tmp_path / "sources.json"
    source.write_text(json.dumps(history))
    Ingestor(graph).sync("history", FileSource(source))
    slack, linear, github = SlackFixture(), LinearFixture(), GitHubFixture()
    worker = RepositoryWorker(
        str(repo),
        tmp_path / "runs",
        StimulusCoding(),
        LocalRunner(trusted=True),
        check_commands={
            "exports": ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        },
    )
    workflow = Workflow(
        graph,
        slack,
        linear,
        github,
        worker,
        Investigator(graph),
        {"demo_user": "U1", "demo_channel": "C1", "max_repairs": 1},
    )

    class System:
        def __init__(self):
            self.workflow, self.graph = workflow, graph
            self.slack, self.linear, self.github, self.worker = slack, linear, github, worker
            self.repo, self.base, self.source = repo, base, source
            self.counter = 0
            self.state = {}

        def event(self, type, **fields):
            self.counter += 1
            value = {"id": f"event-{self.counter}", "type": type, "channel": "C1", "user": "U1"}
            if self.state:
                value["request"] = self.state["id"]
            value.update(fields)
            self.state = self.workflow.handle(value)
            return self.state

        def propose(self):
            self.event(
                "request",
                project="atlas",
                behavior="report_export",
                repo=str(repo),
                base=base,
                text="Allow project admins to export reports",
            )
            return self.event(
                "clarify",
                text="Own project only; invoices stay Finance-only.",
                scope={
                    "membership": "owning-project-only",
                    "acceptance": [
                        "Project admins can export reports for projects they administer",
                        "Deny cross-project exports",
                        "Preserve Finance-only invoice access",
                    ],
                },
            )

        def approve(self):
            return self.event(
                "approve",
                revision=self.state["revision"],
                hash=self.state["scope_hash"],
                trusted_slack=True,
                interaction=True,
            )

        def execute(self):
            self.propose()
            self.approve()
            return self.event("execute")

        def merge(self):
            return self.event(
                "authorize_merge",
                revision=self.state["revision"],
                hash=self.state["scope_hash"],
                pr=self.state["pr"]["id"],
                head=self.state["pr"]["head"],
                trusted_slack=True,
                interaction=True,
            )

    yield System()
    graph.redis.execute_command("GRAPH.DELETE", graph.graph)


def test_complete_workflow_records_actual_commit_then_reuses_scoped_decision(system):
    state = system.execute()
    assert state["phase"] == "reviewing", state
    assert state["run"]["commit"] != system.base
    assert all(c["exit_code"] == 0 for c in state["run"]["checks"])
    assert "test_project_admin_cannot_export_invoice" in state["run"]["checks"][-1]["output"]
    system.github.ready(state["pr"]["id"])
    state = system.merge()
    assert state["phase"] == "merged", state
    evidence = system.event(
        "investigate",
        request="",
        project="atlas",
        behavior="report_export",
        repo=str(system.repo),
        base=system.base,
    )["evidence"]
    assert any("project admins" in d["text"] for d in evidence["decisions"])
    assert any(
        "Invoice" in d["text"] and d["behavior"] == "invoice_export" for d in evidence["decisions"]
    )
    assert not any(d["claim_id"] == "reports-finance-v1" for d in evidence["decisions"])
    assert any(d["claim_id"] == "reports-finance-v1" for d in evidence["historical"])


def test_external_ticket_change_requires_new_displayed_revision(system):
    state = system.propose()
    old_revision, old_hash = state["revision"], state["scope_hash"]
    issue = system.linear.issues[state["ticket"]["id"]]
    issue["scope"]["objective"] = "Different externally edited objective"
    state = system.approve()
    assert state["phase"] == "awaiting_approval"
    assert state["revision"] == old_revision + 1
    assert "changed externally" in state["error"]
    assert not system.graph.list("Handoff")
    state = system.event(
        "approve", revision=old_revision, hash=old_hash, trusted_slack=True, interaction=True
    )
    assert "stale" in state["error"]
    assert not system.graph.list("Handoff")


def test_quoted_approval_and_duplicate_delivery_cannot_duplicate_handoff(system):
    state = system.propose()
    state = system.event(
        "approve", text="approved", revision=state["revision"], hash=state["scope_hash"]
    )
    assert "verified" in state["error"]
    assert not system.graph.list("Handoff")
    event = {
        "id": "approval-once",
        "type": "approve",
        "channel": "C1",
        "user": "U1",
        "request": state["id"],
        "revision": state["revision"],
        "hash": state["scope_hash"],
        "trusted_slack": True,
        "interaction": True,
    }
    system.workflow.handle(event)
    system.workflow.handle(event)
    assert len(system.graph.list("Handoff")) == 1
    assert len(system.graph.list("Approval")) == 1


def test_lost_linear_creation_response_recovers_one_issue_after_restart(system):
    system.linear.lose_response = True
    state = system.propose()
    assert state["phase"] == "reconciling"
    assert len(system.linear.issues) == 1
    old = system.workflow
    system.workflow = Workflow(
        old.store, old.slack, old.tickets, old.prs, old.worker, old.investigator, old.config
    )
    state = system.event("recover")
    assert state["phase"] == "awaiting_approval"
    assert len(system.linear.issues) == 1
    assert state["presented_revision"] == 1


@pytest.mark.parametrize(
    "failure", ["missing-check", "failed-check", "missing-review", "changed-head"]
)
def test_merge_rejects_missing_or_stale_prerequisites(system, failure):
    state = system.execute()
    assert state["phase"] == "reviewing", state
    pr = system.github.prs[state["pr"]["id"]]
    system.github.ready(pr["id"])
    if failure == "missing-check":
        pr["checks"] = []
    elif failure == "failed-check":
        pr["checks"][0]["status"] = "failure"
    elif failure == "missing-review":
        pr["reviews"] = []
    else:
        pr["head"] = "b" * 40
    state = system.merge()
    assert state["error"]
    assert not pr["merged"]


def test_provider_expected_head_rejects_concurrent_push(system):
    state = system.execute()
    system.github.ready(state["pr"]["id"])
    system.github.race_head = "f" * 40
    state = system.merge()
    assert "expected-head" in state["error"]
    assert not system.github.prs[state["pr"]["id"]]["merged"]
    state = system.event("recover")
    assert state["phase"] == "reviewing"
    assert "merge_authorization" not in state


@pytest.mark.parametrize("provider", ["pr", "merge"])
def test_unknown_external_write_is_reconciled_without_duplicate_effects(system, provider):
    if provider == "pr":
        system.github.lose_create = True
        state = system.execute()
    else:
        state = system.execute()
        system.github.ready(state["pr"]["id"])
        system.github.lose_merge = True
        state = system.merge()
    assert state["phase"] == "reconciling", state
    state = system.event("recover")
    assert state["phase"] == ("reviewing" if provider == "pr" else "merged"), state
    assert len(system.github.prs) == 1
    assert len(system.graph.list("Run")) == 1


def test_review_commit_receives_fresh_checks_and_old_merge_button_expires(system):
    state = system.execute()
    old_head = state["pr"]["head"]
    state = system.event(
        "review", pr=state["pr"]["id"], head=old_head, text="Add an explanation comment"
    )
    assert state["phase"] == "reviewing", state
    assert state["pr"]["head"] != old_head
    assert len(system.github.prs) == 1
    assert len(state["runs"]) == 2
    assert all(
        c["head"] == state["pr"]["head"] for c in state["run"]["checks"] if c["kind"] != "baseline"
    )
    state = system.event(
        "authorize_merge",
        pr=state["pr"]["id"],
        head=old_head,
        revision=state["revision"],
        hash=state["scope_hash"],
        trusted_slack=True,
        interaction=True,
    )
    assert "stale" in state["error"]


def test_scope_changing_review_returns_to_approval_without_coding(system):
    state = system.execute()
    state = system.event(
        "review",
        pr=state["pr"]["id"],
        head=state["pr"]["head"],
        scope={"acceptance": ["Materially changed product requirement"]},
    )
    assert state["phase"] == "awaiting_approval"
    assert state["revision"] == 2
    assert "approval" not in state
    assert len(state["runs"]) == 1


def test_source_access_loss_after_approval_stops_execution(system):
    import json

    from actron.connectors import FileSource
    from actron.ingestion import Ingestor

    state = system.propose()
    system.approve()
    records = json.loads(system.source.read_text())
    record = next(r for r in records if r["id"] == "finance-export-thread")
    record.update(revision="unavailable-2", availability="inaccessible")
    system.source.write_text(json.dumps([record]))
    Ingestor(system.graph).sync("access-update", FileSource(system.source))
    state = system.event("execute")
    assert state["phase"] == "clarification"
    assert "Evidence changed" in state["error"]
    assert not system.graph.list("Run")


def test_real_graph_outage_reports_dependency_unavailable():
    from actron.graph import FalkorStore
    from actron.ingestion import Investigator

    graph = FalkorStore(
        "redis://127.0.0.1:1/0?socket_connect_timeout=0.1", "outage", lock_wait=0.01
    )
    slack = SlackFixture()
    state = Workflow(
        graph, slack, LinearFixture(), GitHubFixture(), None, Investigator(graph), {}
    ).handle({"id": "offline", "type": "request", "channel": "C", "user": "U"})
    assert state["blocked"] is True
    assert "unavailable" in slack.messages[-1]["text"]


def test_actual_failure_keeps_failed_commit_and_repairs_within_scope(system):
    from tests.fakes import StimulusCoding

    system.worker.coding = StimulusCoding(fail_once=True)
    state = system.execute()
    assert state["phase"] == "reviewing", state
    attempts = state["run"]["attempts"]
    assert len(attempts) == 2
    assert any(c["exit_code"] != 0 for c in attempts[0]["checks"])
    assert attempts[0]["commit"] != attempts[1]["commit"]
    assert state["revision"] == 1
    assert all(c["exit_code"] == 0 for c in attempts[1]["checks"])


def test_worker_scope_change_requires_new_ticket_approval(system):
    class ScopeChange:
        def propose(self, checkout, packet, remaining_tokens, timeout):
            return {
                "scope_revision": "Project membership criteria require product clarification",
                "tokens": 0,
            }

    system.worker.coding = ScopeChange()
    state = system.execute()
    assert state["phase"] == "clarification", state
    assert "approval" not in state
    assert not system.github.prs
    state = system.event(
        "clarify",
        text="Explicit updated scope",
        scope={"membership": "owning-project-only", "acceptance": ["Updated inspected criteria"]},
    )
    assert state["phase"] == "awaiting_approval"
    assert state["revision"] == 2


def test_failed_predecessor_is_repaired_with_original_scope_approval(system):
    from tests.fakes import StimulusCoding

    system.worker.max_attempts = 1
    system.worker.coding = StimulusCoding(fail_once=True)
    state = system.execute()
    assert state["phase"] == "failed", state
    system.worker.coding = StimulusCoding()
    state = system.event("repair", text="Repair within existing approved criteria")
    assert state["phase"] == "reviewing", state
    assert len(state["runs"]) == 2
    assert any(c.get("kind") == "predecessor" for c in state["run"]["check_history"])


def test_new_unapproved_proposals_and_unrelated_names_are_not_active_rules(system):
    evidence = system.event(
        "investigate",
        project="atlas",
        behavior="report_export",
        repo=str(system.repo),
        base=system.base,
    )["evidence"]
    assert not evidence["conflict"]
    assert any(d["claim_id"] == "reports-finance-v1" for d in evidence["decisions"])
    assert any("admin" in p["text"] for p in evidence["proposals"])
    assert not any("all project members" in d["text"] for d in evidence["decisions"])


def test_changed_repository_snapshot_invalidates_approved_request(system):
    import json

    from actron.connectors import FileSource
    from actron.ingestion import Ingestor

    system.propose()
    system.approve()
    records = json.loads(system.source.read_text())
    record = next(r for r in records if r["id"] == "code")
    new_head = "c" * 40
    record["revision"] = new_head
    record["snapshot"]["commit"] = new_head
    record["snapshot"]["components"][0]["calls"] = []
    system.source.write_text(json.dumps([record]))
    Ingestor(system.graph).sync("new-code", FileSource(system.source))
    state = system.event("execute")
    assert state["phase"] == "clarification"
    assert "Evidence changed" in state["error"]
    assert not system.github.prs


def test_unconfirmed_slack_revision_display_does_not_accept_approval(system):
    from actron.contracts import UnknownOutcome

    class LostPresentation(SlackFixture):
        def post(self, channel, text, thread=None, blocks=None):
            if blocks:
                raise UnknownOutcome("Lost Slack presentation")
            return super().post(channel, text, thread, blocks)

    system.workflow.slack = LostPresentation()
    state = system.propose()
    assert state["phase"] == "reconciling"
    assert "presented_revision" not in state
    assert len(system.linear.issues) == 1
    system.workflow.slack = system.slack
    state = system.event("recover")
    assert state["phase"] == "awaiting_approval"
    assert state["presented_revision"] == 1
    assert len(system.linear.issues) == 1


def test_pending_write_cannot_be_replaced_by_a_new_signed_command(system):
    import json
    from urllib.parse import urlencode

    from actron.ingress import SlackIngress
    from tests.test_ingress import signed

    system.linear.lose_response = True
    state = system.propose()
    pending = state["pending"]["id"]
    ingress = SlackIngress(system.graph, system.workflow, "secret", clock=lambda: 1000)
    body = urlencode(
        {
            "command": "/actron",
            "text": "revise "
            + json.dumps({"request": state["id"], "scope": {"objective": "A different objective"}}),
            "channel_id": "C1",
            "user_id": "U1",
            "trigger_id": "new-revision-during-reconcile",
        }
    ).encode()
    ingress.receive(body, signed(body))
    ingress.drain()
    current = system.graph.get("Request", state["id"])
    assert "unresolved operation" in current["error"]
    assert current["pending"]["id"] == pending
    assert current["revision"] == 1
    assert len(system.linear.issues) == 1
    state = system.event("recover")
    assert state["phase"] == "awaiting_approval"
    assert len(system.linear.issues) == 1


def test_slack_rendered_approval_blocks_show_exact_scope_and_head(system):
    state = system.propose()
    rendered = " ".join(
        block.get("text", {}).get("text", "") for block in system.slack.messages[-1]["blocks"]
    )
    assert state["scope_hash"] in rendered
    assert "Preserve Finance-only invoice access" in rendered
    assert "owning-project-only" in rendered
    system.approve()
    state = system.event("execute")
    rendered = " ".join(
        block.get("text", {}).get("text", "") for block in system.slack.messages[-1]["blocks"]
    )
    assert state["pr"]["head"] in rendered
    assert state["pr"]["url"] in rendered


def test_interrupted_pr_revision_completes_same_pr_after_restart(system):
    from actron.contracts import UnknownOutcome

    state = system.execute()
    old_pr, old_head = state["pr"]["id"], state["pr"]["head"]
    provider = system.github

    class BeforePushFailure:
        failed = False

        def __getattr__(self, name):
            return getattr(provider, name)

        def create(self, operation, run, scope):
            if not self.failed:
                self.failed = True
                raise UnknownOutcome("Interrupted before revision branch push")
            return provider.create(operation, run, scope)

    system.workflow.prs = BeforePushFailure()
    state = system.event("review", pr=old_pr, head=old_head, text="Add a reviewed explanation")
    assert state["phase"] == "reconciling"
    assert provider.prs[old_pr]["head"] == old_head
    state = system.event("recover")
    assert state["phase"] == "reviewing", state
    assert state["pr"]["id"] == old_pr
    assert state["pr"]["head"] != old_head
    assert len(provider.prs) == 1


def test_review_feedback_survives_interruption_before_worker_launch(system):
    from actron.contracts import UnknownOutcome
    from tests.fakes import StimulusCoding

    state = system.execute()
    worker = system.worker
    observed = []

    class RecordingCoding(StimulusCoding):
        def propose(self, checkout, packet, remaining_tokens, timeout):
            observed.append(packet["feedback"])
            return super().propose(checkout, packet, remaining_tokens, timeout)

    worker.coding = RecordingCoding()

    class BeforeLaunchFailure:
        failed = False

        def find(self, operation):
            return worker.find(operation)

        def run(self, operation, scope, evidence, base, feedback=""):
            if not self.failed:
                self.failed = True
                raise UnknownOutcome("Interrupted before coding process creation")
            return worker.run(operation, scope, evidence, base, feedback)

    system.workflow.worker = BeforeLaunchFailure()
    feedback = "Add the explanation from the current Slack review"
    state = system.event("review", pr=state["pr"]["id"], head=state["pr"]["head"], text=feedback)
    assert state["phase"] == "reconciling"
    state = system.event("recover")
    assert state["phase"] == "reviewing", state
    assert observed == [feedback]
    assert len(state["runs"]) == 2


def test_interrupted_approval_persistence_recovers_one_handoff(system):
    from actron.contracts import Unavailable

    state = system.propose()
    graph = system.graph

    class LostGraphResponse:
        interrupted = False

        def __getattr__(self, name):
            return getattr(graph, name)

        def put(self, kind, key, value):
            graph.put(kind, key, value)
            if kind == "Approval" and not self.interrupted:
                self.interrupted = True
                raise Unavailable("Injected lost graph response after approval write")

    system.workflow.store = LostGraphResponse()
    event = {
        "id": "interrupted-approval",
        "type": "approve",
        "request": state["id"],
        "channel": "C1",
        "user": "U1",
        "revision": state["revision"],
        "hash": state["scope_hash"],
        "trusted_slack": True,
        "interaction": True,
    }
    assert system.workflow.handle(event)["blocked"] is True
    recovered = system.workflow.handle(event)
    assert recovered["phase"] == "approved", recovered
    assert len(graph.list("Approval")) == 1
    assert len(graph.list("Handoff")) == 1


def test_read_only_investigation_preserves_active_review_and_approved_evidence(system):
    state = system.execute()
    approved_evidence = state["evidence"]["fingerprint"]
    approved_head = state["pr"]["head"]
    state = system.event("investigate")
    assert state["phase"] == "reviewing"
    assert state["evidence"]["fingerprint"] == approved_evidence
    assert state["pr"]["head"] == approved_head
    assert state["latest_investigation"]["fingerprint"] == approved_evidence


def test_failed_repairs_stop_at_the_configured_budget(system):
    import difflib
    import re

    class PersistentlyFailingCoding:
        """Controlled repeated failure; never claimed to be model-generated."""

        def propose(self, checkout, packet, remaining_tokens, timeout):
            original = (checkout / "app/reports.py").read_text()
            replacement = re.sub(r"return [^\n]+", "return False", original)
            if replacement == original:
                replacement += "\n# Controlled unsuccessful repair attempt.\n"
            patch = "diff --git a/app/reports.py b/app/reports.py\n" + "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    replacement.splitlines(keepends=True),
                    fromfile="a/app/reports.py",
                    tofile="b/app/reports.py",
                )
            )
            return {"patch": patch, "tokens": 0}

    system.worker.max_attempts = 1
    system.worker.coding = PersistentlyFailingCoding()
    state = system.execute()
    assert state["phase"] == "failed"
    state = system.event("repair", text="Attempt repair inside approved scope")
    assert state["phase"] == "failed", state
    assert len(state["runs"]) == 2
    assert any(c["exit_code"] != 0 for c in state["run"]["checks"])
    state = system.event("repair", text="Attempt beyond the repair budget")
    assert "limit exhausted" in state["error"]
    assert len(state["runs"]) == 2


def test_concurrent_duplicate_approval_has_one_durable_execution_handoff(system):
    from concurrent.futures import ThreadPoolExecutor

    state = system.propose()
    event = {
        "id": "concurrent-approval",
        "type": "approve",
        "request": state["id"],
        "channel": "C1",
        "user": "U1",
        "revision": state["revision"],
        "hash": state["scope_hash"],
        "trusted_slack": True,
        "interaction": True,
    }
    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(system.workflow.handle, [event, event]))
    assert all(result["phase"] == "approved" for result in results)
    assert len(system.graph.list("Approval")) == 1
    assert len(system.graph.list("Handoff")) == 1
    assert len(system.linear.issues) == 1
