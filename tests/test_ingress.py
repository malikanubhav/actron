"""Public signed Slack ingress seam; providers and workflow are boundary fakes."""

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from actron.contracts import Rejected
from actron.ingress import SlackIngress


class Memory:
    def __init__(self):
        self.records = {}

    def get(self, kind, key):
        return self.records.get((kind, key))

    def put(self, kind, key, value):
        self.records[kind, key] = value

    def list(self, kind):
        return [value for (item_kind, _), value in self.records.items() if item_kind == kind]


class Workflow:
    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)
        return {"phase": "investigating"}


def signed(body, timestamp=1000):
    signature = hmac.new(
        b"secret", b"v0:" + str(timestamp).encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    return {"X-Slack-Request-Timestamp": str(timestamp), "X-Slack-Signature": "v0=" + signature}


def command(text):
    return urlencode(
        {
            "command": "/actron",
            "text": text,
            "channel_id": "C-DEMO",
            "user_id": "U-DEMO",
            "trigger_id": "trigger-1",
        }
    ).encode()


def test_signed_command_acknowledges_durable_enqueue_before_dispatch():
    store, workflow = Memory(), Workflow()
    ingress = SlackIngress(store, workflow, "secret", clock=lambda: 1000)
    body = command('request {"project":"orbit","behavior":"export","repo":"demo","base":"abc"}')
    assert ingress.receive(body, signed(body))[0] == 200
    assert workflow.events == []
    assert store.list("Inbox")[0]["status"] == "pending"
    ingress.drain()
    assert workflow.events[0]["channel"] == "C-DEMO"
    assert workflow.events[0]["user"] == "U-DEMO"
    assert store.list("Inbox")[0]["status"] == "done"
    ingress.receive(body, signed(body))
    ingress.drain()
    assert len(workflow.events) == 1


@pytest.mark.parametrize("delta", [-301, 301])
def test_expired_signed_commands_rejected(delta):
    ingress = SlackIngress(Memory(), Workflow(), "secret", clock=lambda: 1000 + delta)
    body = command('status {"request":"r"}')
    with pytest.raises(Rejected, match="Expired"):
        ingress.receive(body, signed(body))


def test_tampered_signature_rejected():
    ingress = SlackIngress(Memory(), Workflow(), "secret", clock=lambda: 1000)
    original = command('status {"request":"r"}')
    with pytest.raises(Rejected, match="signature"):
        ingress.receive(original + b"x", signed(original))


@pytest.mark.parametrize(
    "text",
    [
        'approve {"request":"r","revision":1,"hash":"h"}',
        'status {"request":"r","trusted_slack":true}',
        'status {"request":"r","user":"U-OTHER"}',
        'authorize_merge {"request":"r","head":"h"}',
    ],
)
def test_command_cannot_forge_approval_or_identity(text):
    ingress = SlackIngress(Memory(), Workflow(), "secret", clock=lambda: 1000)
    body = command(text)
    with pytest.raises(Rejected):
        ingress.receive(body, signed(body))


def test_signed_button_binds_scope_and_identity():
    store, workflow = Memory(), Workflow()
    ingress = SlackIngress(store, workflow, "secret", clock=lambda: 1000)
    payload = {
        "type": "block_actions",
        "trigger_id": "button-trigger",
        "channel": {"id": "C-DEMO"},
        "user": {"id": "U-DEMO"},
        "actions": [
            {
                "type": "button",
                "action_id": "approve",
                "value": json.dumps({"request": "r", "revision": 2, "hash": "hash-2"}),
            }
        ],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ingress.receive(body, signed(body))
    restarted = SlackIngress(store, workflow, "secret", clock=lambda: 1000)
    restarted.drain()
    event = workflow.events[0]
    assert event["interaction"] is True
    assert event["trusted_slack"] is True
    assert (event["request"], event["revision"], event["hash"], event["user"]) == (
        "r",
        2,
        "hash-2",
        "U-DEMO",
    )


def test_graph_outage_does_not_acknowledge_event():
    class Offline(Memory):
        def put(self, kind, key, value):
            raise ConnectionError("graph offline")

    ingress = SlackIngress(Offline(), Workflow(), "secret", clock=lambda: 1000)
    body = command('status {"request":"r"}')
    with pytest.raises(ConnectionError):
        ingress.receive(body, signed(body))


# The shared fixture uses real FalkorDB, disposable git and actual repository checks.
# External provider effects remain explicitly simulated at their public contracts.
from tests.test_workflow import system  # noqa: F401


def test_signed_flow_clarifies_approves_and_restart_dispatches_actual_worker(system):  # noqa: F811
    ingress = SlackIngress(system.graph, system.workflow, "secret", clock=lambda: 1000)
    counter = 0

    def trace(title, state, extra=None):
        import os

        if os.environ.get("ACTRON_DEMO_TRACE") != "1":
            return
        lines = [
            "Phase: " + state.get("phase", "unknown"),
            "Request: " + state.get("id", ""),
            "Ticket revision: " + str(state.get("revision", 0)),
        ]
        if state.get("scope_hash"):
            lines.append("Scope: " + state["scope_hash"])
        if state.get("run"):
            lines += [
                "Tested commit: " + state["run"]["commit"],
                "Actual check exits: " + str([c["exit_code"] for c in state["run"]["checks"]]),
            ]
        if state.get("pr"):
            lines.append("Provider-fake PR head: " + state["pr"]["head"])
        lines += extra or []
        print("ACTRON_TRACE " + json.dumps({"title": title, "lines": lines}), flush=True)

    def deliver(verb, args):
        nonlocal counter
        counter += 1
        body = urlencode(
            {
                "command": "/actron",
                "text": verb + " " + json.dumps(args),
                "channel_id": "C1",
                "user_id": "U1",
                "trigger_id": f"ingress-{counter}",
            }
        ).encode()
        assert ingress.receive(body, signed(body))[0] == 200
        ingress.drain()
        return system.graph.list("Request")[0]

    state = deliver(
        "request",
        {
            "project": "atlas",
            "behavior": "report_export",
            "repo": str(system.repo),
            "base": system.base,
            "text": "Allow project admins to export reports",
        },
    )
    assert state["phase"] == "clarification"
    trace(
        "Signed Slack request investigates graph history",
        state,
        [
            "Approved Finance-only report rule found.",
            "Shared helper reaches independent invoice rule.",
            "Clarification requested before ticket or implementation.",
        ],
    )
    state = deliver(
        "clarify",
        {
            "request": state["id"],
            "text": "Own project membership only; preserve invoices.",
            "scope": {
                "membership": "owning-project-only",
                "acceptance": [
                    "Project admins may export reports for their own project",
                    "Preserve Finance-only invoice access",
                    "Deny cross-project exports",
                ],
            },
        },
    )
    assert state["phase"] == "awaiting_approval"
    assert len(system.linear.issues) == 1
    trace(
        "Clarification produces an exact Linear revision",
        state,
        [
            "Project membership and Finance-only invoices retained.",
            "Approval binds the displayed revision and scope hash.",
        ],
    )
    payload = {
        "type": "block_actions",
        "trigger_id": "approve-live-shaped",
        "channel": {"id": "C1"},
        "user": {"id": "U1"},
        "actions": [
            {
                "type": "button",
                "action_id": "approve",
                "value": json.dumps(
                    {
                        "request": state["id"],
                        "revision": state["revision"],
                        "hash": state["scope_hash"],
                    }
                ),
            }
        ],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ingress.receive(body, signed(body))
    ingress.drain()
    assert system.graph.list("Request")[0]["phase"] == "approved"
    trace(
        "Verified Slack button queues durable execution",
        system.graph.list("Request")[0],
        [
            "Signed interaction identity matches the configured demo user/channel.",
            "A fresh dispatcher will recover the stored Handoff.",
        ],
    )
    # A new runtime picks the durable handoff up, without another user command.
    restarted = SlackIngress(system.graph, system.workflow, "secret", clock=lambda: 1000)
    restarted.drain()
    state = system.graph.list("Request")[0]
    assert state["phase"] == "reviewing", state
    assert state["run"]["commit"] != system.base
    assert state["run"]["checks"][-1]["exit_code"] == 0
    assert len(system.github.prs) == 1
    restarted.drain()
    assert len(system.github.prs) == 1
    trace(
        "Restart drains handoff; git/checks produce a PR",
        state,
        [
            "Real disposable git checkout and implementation commit.",
            "Selected checks and preserved full test suite exited zero.",
        ],
    )
    previous_head = state["pr"]["head"]
    state = deliver(
        "review",
        {
            "request": state["id"],
            "pr": state["pr"]["id"],
            "head": previous_head,
            "text": "Improve the implementation explanation; retain scope.",
        },
    )
    assert state["phase"] == "reviewing", state
    assert state["pr"]["head"] != previous_head
    trace(
        "Slack review creates a freshly tested PR revision",
        state,
        ["Changed head requires new checks and a fresh merge authorization."],
    )
    system.github.ready(state["pr"]["id"])
    payload = {
        "type": "block_actions",
        "trigger_id": "merge-live-shaped",
        "channel": {"id": "C1"},
        "user": {"id": "U1"},
        "actions": [
            {
                "type": "button",
                "action_id": "authorize_merge",
                "value": json.dumps(
                    {
                        "request": state["id"],
                        "revision": state["revision"],
                        "hash": state["scope_hash"],
                        "pr": state["pr"]["id"],
                        "head": state["pr"]["head"],
                    }
                ),
            }
        ],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    restarted.receive(body, signed(body))
    restarted.drain()
    state = system.graph.list("Request")[0]
    assert state["phase"] == "merged", state
    trace(
        "Separate current-head button confirms provider-fake merge",
        state,
        [
            "Provider-fake required check and review refer to this exact head.",
            "No real GitHub merge or live model is claimed.",
        ],
    )
    from actron.ingestion import Investigator

    evidence = Investigator(system.graph).evidence(
        "atlas", "report_export", str(system.repo), system.base
    )
    assert any("project admins" in item["text"] for item in evidence["decisions"])
    assert any(item["behavior"] == "invoice_export" for item in evidence["decisions"])
    trace(
        "Later investigation reuses only the scoped decision",
        state,
        ["Graph rule: " + item["text"] for item in evidence["decisions"]],
    )


@pytest.mark.parametrize(
    "scope",
    [
        {"checks": []},
        {"membership": True},
        {"acceptance": "unsafe"},
        {"constraints": [3]},
        {"user": "U-OTHER"},
    ],
)
def test_scope_cannot_override_provider_or_validation_metadata(scope):
    ingress = SlackIngress(Memory(), Workflow(), "secret", clock=lambda: 1000)
    body = command("clarify " + json.dumps({"request": "r", "text": "clarify", "scope": scope}))
    with pytest.raises(Rejected):
        ingress.receive(body, signed(body))


@pytest.mark.parametrize("visible_after_loss", [True, False])
def test_slack_root_lost_response_reconciles_or_pauses_without_duplicate(visible_after_loss):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from actron.contracts import UnknownOutcome
    from actron.ingress import SlackAPI

    posts, searches = [], []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def answer(self, value):
            encoded = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            searches.append(self.path)
            messages = [{**posts[0], "ts": "177.001"}] if posts and visible_after_loss else []
            self.answer({"ok": True, "messages": messages, "has_more": False})

        def do_POST(self):
            posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            # Provider accepted the write; its response is missing required outcome evidence.
            self.answer({"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    records = Memory()
    try:
        slack = SlackAPI("test-token", f"http://127.0.0.1:{server.server_port}", store=records)
        with pytest.raises(UnknownOutcome):
            slack.start("C1", "request-1", "Received")
        # Reconstructing the adapter models a process restart; graph journal survives.
        restarted = SlackAPI("test-token", f"http://127.0.0.1:{server.server_port}", store=records)
        if visible_after_loss:
            assert restarted.start("C1", "request-1", "Received") == "177.001"
            assert records.get("SlackRoot", "request-1")["status"] == "confirmed"
        else:
            with pytest.raises(UnknownOutcome, match="remains unknown"):
                restarted.start("C1", "request-1", "Received")
        assert len(posts) == 1
        assert all("include_all_metadata=true" in query for query in searches)
        assert posts[0]["metadata"]["event_payload"]["request"] == "request-1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
