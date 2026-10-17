"""Observe source updates through signed Slack ingress and real graph evidence."""

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

import pytest

from actron.connectors import FileSource
from actron.contracts import Payload, Rejected
from actron.graph import FalkorStore
from actron.ingestion import Ingestor, Investigator
from actron.ingress import SlackIngress
from actron.workflow import Workflow
from tests.fakes import GitHubFixture, LinearFixture, SlackFixture


def investigate(store: FalkorStore, *, base: str = "base") -> Payload:
    """Submit the public command and inspect its persisted, externally visible result."""
    slack = SlackFixture()
    workflow = Workflow(
        store,
        slack,
        LinearFixture(),
        GitHubFixture(),
        None,
        Investigator(store),
        {"demo_user": "U1", "demo_channel": "C1"},
    )
    ingress = SlackIngress(store, workflow, "source-update-secret", clock=lambda: 1000)
    body = urlencode(
        {
            "command": "/actron",
            "text": "investigate "
            + json.dumps(
                {
                    "project": "acme",
                    "behavior": "reports",
                    "repo": "repo",
                    "base": base,
                }
            ),
            "channel_id": "C1",
            "user_id": "U1",
            "trigger_id": uuid.uuid4().hex,
        }
    ).encode()
    signature = hmac.new(
        b"source-update-secret",
        b"v0:1000:" + body,
        hashlib.sha256,
    ).hexdigest()
    previous = {row["id"] for row in store.list("Inbox")}
    assert (
        ingress.receive(
            body,
            {
                "X-Slack-Request-Timestamp": "1000",
                "X-Slack-Signature": "v0=" + signature,
            },
        )[0]
        == 200
    )
    ingress.drain()
    row = next(row for row in store.list("Inbox") if row["id"] not in previous)
    assert row["status"] == "done"
    assert row["result"]["phase"] == "investigated"
    assert slack.messages[-1]["text"].startswith("Connected evidence")
    return row["result"]["evidence"]


def test_revision_updates_retain_approved_rule_and_expose_unavailable_sources(
    tmp_path: Path,
) -> None:
    store = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), f"test_{uuid.uuid4().hex}"
    )
    path = tmp_path / "sources.json"
    rule = {
        "id": "policy",
        "provider": "slack",
        "revision": "1",
        "project": "acme",
        "behavior": "reports",
        "content": "Reports are restricted",
        "locator": "slack://demo/policy",
        "claims": [
            {
                "id": "report-policy",
                "behavior": "reports",
                "text": "Reports are restricted",
                "status": "approved",
                "approval": {
                    "actor": "fictional-owner",
                    "source": "slack://demo/approval",
                    "revision": "1",
                },
            }
        ],
    }
    proposal = {
        "id": "proposal",
        "provider": "linear",
        "revision": "2",
        "project": "acme",
        "behavior": "reports",
        "content": "Allow reports",
        "locator": "linear://demo/proposal",
        "claims": [
            {
                "id": "allow-reports",
                "behavior": "reports",
                "text": "Allow reports",
                "status": "approved",
            }
        ],
    }
    path.write_text(json.dumps([rule, proposal]))
    try:
        ingest = Ingestor(store)
        ingest.sync("fixture", FileSource(path, page_size=1))
        ingest.sync("fixture", FileSource(path, page_size=1))
        evidence = investigate(store)
        assert evidence["constraints"] == ["Reports are restricted"]
        assert evidence["proposals"][0]["text"] == "Allow reports"
        assert len(store.list("SourceRevision")) == 2
        path.write_text(
            json.dumps(
                [
                    {
                        **rule,
                        "revision": "3",
                        "availability": "inaccessible",
                        "content": "",
                        "claims": [],
                    }
                ]
            )
        )
        ingest.sync("fixture", FileSource(path))
        evidence = investigate(store)
        assert evidence["decisions"] == []
        assert any("unavailable" in gap for gap in evidence["gaps"])
        assert len(store.list("SourceRevision")) == 3
    finally:
        store.redis.execute_command("GRAPH.DELETE", store.graph)


def test_snapshot_refresh_preserves_history_and_never_mixes_commits(tmp_path: Path) -> None:
    store = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), f"test_{uuid.uuid4().hex}"
    )
    path = tmp_path / "snapshot.json"

    def record(commit: str, helper: str) -> dict:
        return {
            "id": "repo-snapshot",
            "provider": "github",
            "revision": commit,
            "project": "acme",
            "content": helper,
            "locator": f"github://repo/{commit}",
            "snapshot": {
                "repo": "repo",
                "commit": commit,
                "components": [
                    {"id": helper, "path": "policy.py", "behaviors": ["reports", "invoices"]}
                ],
                "checks": [
                    {
                        "id": "invoice",
                        "command": ["python", "-m", "unittest"],
                        "behaviors": ["invoices"],
                    }
                ],
            },
        }

    try:
        ingest = Ingestor(store)
        path.write_text(json.dumps([record("old", "shared")]))
        ingest.sync("code", FileSource(path))
        path.write_text(json.dumps([record("new", "dedicated")]))
        ingest.sync("code", FileSource(path))
        evidence = investigate(store, base="old")
        assert evidence["snapshot"]["commit"] == "new"
        assert [item["id"] for item in evidence["components"]] == ["dedicated"]
        assert evidence["checks"][0]["commit"] == "new"
        assert any("stale" in gap for gap in evidence["gaps"])
        assert len(store.list("Snapshot")) == 2
        path.write_text(json.dumps([record("new", "tampered")]))
        with pytest.raises(Rejected, match="immutable"):
            ingest.sync("code", FileSource(path))
    finally:
        store.redis.execute_command("GRAPH.DELETE", store.graph)


def test_interrupted_cursor_resumes_without_duplicate_revisions(tmp_path: Path) -> None:
    from actron.contracts import Payload, Unavailable

    store = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), f"test_{uuid.uuid4().hex}"
    )
    path = tmp_path / "pages.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": str(index),
                    "provider": "slack",
                    "revision": "1",
                    "project": "acme",
                    "content": f"Message {index}",
                    "locator": f"slack://demo/{index}",
                }
                for index in range(3)
            ]
        )
    )

    class InterruptedSource(FileSource):
        def fetch(self, cursor: str | None = None) -> Payload:
            if cursor == "1":
                raise Unavailable("source disconnected between pages")
            return super().fetch(cursor)

    try:
        ingest = Ingestor(store)
        with pytest.raises(Unavailable, match="disconnected"):
            ingest.sync("history", InterruptedSource(path, page_size=1))
        evidence = investigate(store)
        assert "Partial import: history" in evidence["critical_gaps"]
        ingest.sync("history", FileSource(path, page_size=1))
        assert len(store.list("SourceRevision")) == 3
        assert store.get("Import", "history")["complete"] is True
        ingest.sync("history", FileSource(path, page_size=1))
        assert len(store.list("SourceRevision")) == 3
    finally:
        store.redis.execute_command("GRAPH.DELETE", store.graph)


def test_approved_replacement_is_scoped_and_code_access_loss_blocks_execution(
    tmp_path: Path,
) -> None:
    store = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"), f"test_{uuid.uuid4().hex}"
    )
    path = tmp_path / "sources.json"
    rules = {
        "id": "rules",
        "provider": "slack",
        "revision": "1",
        "project": "acme",
        "content": "Historical rules",
        "locator": "slack://demo/rules",
        "claims": [
            {
                "id": "reports-v1",
                "behavior": "reports",
                "text": "Finance reports only",
                "status": "approved",
                "approval": {"actor": "owner", "source": "slack://demo/rules", "revision": "1"},
            },
            {
                "id": "invoice-v1",
                "behavior": "invoices",
                "text": "Finance invoices only",
                "status": "approved",
                "approval": {"actor": "owner", "source": "slack://demo/rules", "revision": "1"},
            },
        ],
    }
    code = {
        "id": "code",
        "provider": "github",
        "revision": "base",
        "project": "acme",
        "content": "Code snapshot",
        "locator": "github://demo/base",
        "snapshot": {
            "repo": "repo",
            "commit": "base",
            "components": [
                {"id": "shared", "path": "permissions.py", "behaviors": ["reports", "invoices"]}
            ],
            "checks": [],
        },
    }
    replacement = {
        "id": "replacement",
        "provider": "linear",
        "revision": "2",
        "project": "acme",
        "content": "Reports exception approved",
        "locator": "linear://demo/replacement",
        "claims": [
            {
                "id": "reports-v2",
                "behavior": "reports",
                "text": "Project admins may export reports",
                "status": "approved",
                "supersedes": ["reports-v1", "invoice-v1"],
                "approval": {
                    "actor": "owner",
                    "source": "linear://demo/replacement",
                    "revision": "2",
                },
            }
        ],
    }
    try:
        ingest = Ingestor(store)
        path.write_text(json.dumps([rules, code]))
        ingest.sync("history", FileSource(path))
        path.write_text(json.dumps([replacement]))
        ingest.sync("replacement", FileSource(path))
        evidence = investigate(store)
        assert set(evidence["constraints"]) == {
            "Project admins may export reports",
            "Finance invoices only",
        }
        assert [claim["claim_id"] for claim in evidence["historical"]] == ["reports-v1"]
        path.write_text(
            json.dumps(
                [
                    {
                        **code,
                        "revision": "deleted",
                        "availability": "deleted",
                        "content": "",
                        "snapshot": None,
                    }
                ]
            )
        )
        ingest.sync("code-update", FileSource(path))
        evidence = investigate(store)
        assert any("github:code" in gap for gap in evidence["critical_gaps"])
    finally:
        store.redis.execute_command("GRAPH.DELETE", store.graph)
