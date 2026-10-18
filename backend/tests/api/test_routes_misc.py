"""Notifications, settings, replay, health, webhooks and ingestion routes (spec B, B.C7; B-AC-57)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from actron.flow import service
from actron.flow.events import emit, publish_workspace_event
from tests.api._fixtures import FakeGateway, W6Env
from tests.api.conftest import Api, signed_in


async def _req(api: Api) -> str:
    r = await api.post("/api/requests", {"text": "Let admins export invoices", "kindHint": "feature"})
    return str(r.json()["request"]["id"])


# Notifications
async def test_notifications_list_and_read(api: Api, anon: httpx.AsyncClient) -> None:
    """B-AC-62/63 through the API: list, unread filter, mark read 204, unknown 404."""
    rid = await _req(api)
    await emit(api.env.ws, rid, "pr.opened", {"number": 3})
    r = await api.get("/api/notifications?unread=1")
    assert r.status_code == 200 and r.json()["unread"] == 1
    item = r.json()["notifications"][0]
    assert item["kind"] == "pr_ready" and item["tab"] == "pr" and item["requestId"] == rid
    assert (await api.post(f"/api/notifications/{item['id']}/read")).status_code == 204
    assert (await api.get("/api/notifications")).json()["unread"] == 0
    assert (await api.post("/api/notifications/not-a-uuid/read")).status_code == 404
    assert (await anon.get("/api/notifications")).status_code == 401


# Settings
async def test_settings_get_put(api: Api, anon: httpx.AsyncClient) -> None:
    r = await api.get("/api/settings")
    assert r.status_code == 200
    s = r.json()["settings"]
    assert set(s) == {"approvers", "modelPrices", "allowPublicReplays", "thresholds", "models", "jobs",
                      "botIdentity", "budget", "schedules"}
    assert s["budget"]["capUsd"] == 20.0 and len(s["jobs"]) >= 10
    r = await api.put("/api/settings", {"approvers": ["U1", "U2"], "allowPublicReplays": True,
                                        "thresholds": {"conflict": 0.85}})
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["approvers"] == ["U1", "U2"] and s["allowPublicReplays"] is True
    assert s["thresholds"]["conflict"] == 0.85 and s["thresholds"]["linkKeep"] > 0
    assert (await api.put("/api/settings", {"thresholds": {"conflict": 3}})).status_code == 422
    assert (await api.put("/api/settings", {"unknown": 1})).status_code == 422
    assert (await anon.get("/api/settings")).status_code == 401


async def test_settings_put_owner_only(app: Any, w6: W6Env) -> None:
    member = await signed_in(app, w6, w6.add_user("Member"))
    r = await member.put("/api/settings", {"approvers": ["U9"]})
    await member.client.aclose()
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_owner"


async def test_raise_budget_route(api: Api, gateway: FakeGateway) -> None:
    """B-AC-85: POST /api/settings/budget sets the cap and signals waiting builds."""
    rid = await _req(api)
    service.set_request_fields(rid, state="Building")
    r = await api.post("/api/settings/budget", {"capUsd": 45})
    assert r.status_code == 200 and r.json()["settings"]["budget"]["capUsd"] == 45
    assert [s[1] for s in gateway.signals] == ["budget_raised"]
    assert (await api.post("/api/settings/budget", {"capUsd": -1})).status_code == 422


# Replay
async def test_replay_requires_finished(api: Api, anon: httpx.AsyncClient) -> None:
    rid = await _req(api)
    r = await api.get(f"/api/requests/{rid}/replay")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_finished"
    service.set_request_fields(rid, state="Done", outcome="approved")
    r = await api.get(f"/api/requests/{rid}/replay")
    assert r.status_code == 200
    assert [e["type"] for e in r.json()["events"]] == ["request.created"]
    assert (await anon.get(f"/api/requests/{rid}/replay")).status_code == 401


async def test_public_replay_redacted(api: Api, anon: httpx.AsyncClient) -> None:
    """B.C7: public replays only when allowed; names and Slack locations are removed."""
    rid = await _req(api)
    service.set_request_fields(rid, state="Done", outcome="approved")
    assert (await anon.get(f"/api/public/replays/{rid}")).status_code == 404
    await api.put("/api/settings", {"allowPublicReplays": True})
    r = await anon.get(f"/api/public/replays/{rid}")
    assert r.status_code == 200
    text = r.text
    assert "Owner" not in text and api.env.owner_id not in text
    assert r.json()["request"]["requester"]["name"] == "A teammate"


# Health
async def test_health(anon: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import actron.api.routes.health as h

    async def ok(_: Any) -> dict[str, Any]:
        return {"falkordb": "ok", "postgres": "ok", "redis": "ok", "temporal": "ok", "integrations": {},
                "version": "dev"}

    async def down(_: Any) -> dict[str, Any]:
        return {**(await ok(None)), "temporal": "error"}

    monkeypatch.setattr(h, "check_health", ok)
    assert (await anon.get("/api/health")).status_code == 200
    monkeypatch.setattr(h, "check_health", down)
    r = await anon.get("/api/health")
    assert r.status_code == 503 and r.json()["temporal"] == "error"


# Webhooks
def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _github_connection(w6: W6Env, secret: str) -> None:
    from actron.db import models as m
    from actron.db.crypto import encrypt_secret
    from actron.db.session import session_scope

    with session_scope() as s:
        s.add(m.Connection(workspace_id=w6.ws, provider="github", status="connected",
                           config={"repository": "o/r", "workingBranch": "main"},
                           secret_encrypted=encrypt_secret({"access_token": "t", "webhook_secret": secret})))


async def test_github_webhook(anon: httpx.AsyncClient, w6: W6Env, gateway: FakeGateway) -> None:
    """A-AC-92/93: a signed push to the working branch triggers code and GitHub syncs; bad signature 401;
    repeated delivery ignored."""
    await _github_connection(w6, "whsecret123")
    body = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "o/r"}}).encode()
    headers = {"X-GitHub-Event": "push", "X-GitHub-Delivery": f"d-{w6.ws}", "Content-Type": "application/json"}
    r = await anon.post("/webhooks/github", content=body, headers={**headers, "X-Hub-Signature-256": "sha256=bad"})
    assert r.status_code == 401 and not gateway.schedules
    r = await anon.post("/webhooks/github", content=body,
                        headers={**headers, "X-Hub-Signature-256": _sign("whsecret123", body)})
    assert r.status_code == 204
    triggered = {s[2] for s in gateway.schedules if s[0] == "trigger"}
    assert triggered == {"code", "github"}
    gateway.schedules.clear()
    await anon.post("/webhooks/github", content=body,
                    headers={**headers, "X-Hub-Signature-256": _sign("whsecret123", body)})
    assert not gateway.schedules


# Ingestion
async def test_ingestion_status_and_runs(api: Api, w6: W6Env, anon: httpx.AsyncClient) -> None:
    from actron.db import models as m
    from actron.db.session import session_scope

    with session_scope() as s:
        s.add(m.Connection(workspace_id=w6.ws, provider="linear", status="connected", config={"team": "T"}))
        s.add(m.SyncRun(workspace_id=w6.ws, source="linear", mode="backfill", status="partial",
                        items={"LinearIssue": 12}, errors=[{"action": "comments", "error": "rate limit",
                                                            "at": "2026-10-17T00:00:00Z"}],
                        reason="public rate limit", started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
    await publish_workspace_event(w6.ws, "linking.finished", {"runId": "r", "counts": {
        "references_resolved": 4, "pending": 1, "decisions": 2, "identities": 3, "links_kept": 9, "links_dropped": 1}})
    r = await api.get("/api/ingestion/status")
    assert r.status_code == 200
    data = r.json()
    src = data["sources"][0]
    assert src["provider"] == "linear" and src["state"] == "PARTIAL" and src["counts"] == {"LinearIssue": 12}
    assert src["reason"] == "public rate limit"
    assert data["linking"] == {"referencesResolved": 4, "pending": 1, "decisions": 2, "identities": 3,
                               "linksKept": 9, "linksDropped": 1}
    assert data["memoryPercent"] == 100
    runs = (await api.get("/api/ingestion/runs?source=linear")).json()["runs"]
    assert runs[0]["status"] == "partial" and runs[0]["errors"][0]["error"] == "rate limit"
    assert (await api.get("/api/ingestion/runs?limit=0")).status_code == 422
    assert (await anon.get("/api/ingestion/status")).status_code == 401
