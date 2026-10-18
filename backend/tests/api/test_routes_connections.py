"""Connectors and connections (spec B, B.C7; spec A, A11): success, auth, validation, 409 (B-AC-57)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from tests.api._fixtures import FakeGateway, W6Env
from tests.api.conftest import Api, signed_in

TOKEN = "ghp_" + "A" * 36


@dataclass
class FakeResult:
    ok: bool
    message: str
    field_errors: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "field_errors": self.field_errors, "details": self.details,
                "warnings": self.warnings}


@pytest.fixture
def forms(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from actron.connectors import forms as real

    state: dict[str, Any] = {"ok": True, "details": {}}

    async def validate(provider: str, values: dict[str, Any]) -> FakeResult:
        state["last"] = (provider, dict(values))
        if not state["ok"]:
            return FakeResult(False, "The token was refused.", {"access_token": "Refused by GitHub."})
        return FakeResult(True, "Found owner/repo.", details=state["details"])

    async def options(provider: str, field_id: str, values: dict[str, Any]) -> list[dict[str, Any]]:
        state["options_values"] = dict(values)
        if field_id != "workingBranch":
            raise KeyError(field_id)
        return [{"value": "main", "label": "main", "default": True}]

    monkeypatch.setattr(real, "validate", validate)
    monkeypatch.setattr(real, "options", options)
    return state


async def test_list_connectors(api: Api, anon: httpx.AsyncClient) -> None:
    """B-AC-57: GET /api/connectors returns W3's form definitions."""
    r = await api.get("/api/connectors")
    assert r.status_code == 200
    providers = {p["provider"] for p in r.json()["providers"]}
    assert {"github", "slack", "linear"} <= providers
    assert all("fields" in p and "label" in p for p in r.json()["providers"])
    assert (await anon.get("/api/connectors")).status_code == 401


async def test_validate_connector(api: Api, forms: dict[str, Any]) -> None:
    r = await api.post("/api/connectors/github/validate", {"values": {"access_token": TOKEN}})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["found"] == "Found owner/repo."
    forms["ok"] = False
    r = await api.post("/api/connectors/github/validate", {"values": {}})
    assert r.json()["ok"] is False and r.json()["errors"] == [{"field": "access_token", "message": "Refused by GitHub."}]
    assert (await api.post("/api/connectors/nope/validate", {"values": {}})).status_code == 404
    assert (await api.post("/api/connectors/github/validate", {"values": "x"})).status_code == 422


async def test_connector_options(api: Api, forms: dict[str, Any]) -> None:
    r = await api.get("/api/connectors/github/options?field=workingBranch&repository=o/r")
    assert r.status_code == 200 and r.json()["options"][0]["value"] == "main"
    assert (await api.get("/api/connectors/github/options?field=other")).status_code == 404
    assert (await api.get("/api/connectors/github/options")).status_code == 422


async def test_c_ac_50_51_options_reuse_the_secret_of_the_last_accepted_validate(
        api: Api, app: Any, forms: dict[str, Any]) -> None:
    """C-AC-50 and C-AC-51: the options endpoint never takes a token from the URL; it reuses the secret of this
    user's last accepted validate call, stored encrypted in Redis with a short TTL, never returned."""
    from actron.api.routes.connectors import SECRET_TTL_S
    from actron.flow.events import redis_client

    r = await api.get("/api/connectors/github/options?field=workingBranch&repository=o/r&access_token=from-url")
    assert r.status_code == 200
    assert "access_token" not in forms["options_values"]  # nothing validated yet, and the URL value is ignored
    r = await api.post("/api/connectors/github/validate", {"values": {"repository": "o/r", "access_token": TOKEN}})
    assert r.json()["ok"] is True and TOKEN not in r.text
    r = await api.get("/api/connectors/github/options?field=workingBranch&repository=o/r&access_token=from-url")
    assert r.status_code == 200 and TOKEN not in r.text
    assert forms["options_values"] == {"repository": "o/r", "access_token": TOKEN}
    key = f"connector-secret:{api.env.ws}:{api.user_id}:github"
    stored = await redis_client().get(key)
    assert stored and TOKEN not in stored
    assert 0 < await redis_client().ttl(key) <= SECRET_TTL_S
    # A refused secret is not kept: the earlier accepted one stays.
    forms["ok"] = False
    await api.post("/api/connectors/github/validate", {"values": {"repository": "o/r", "access_token": "bad-one"}})
    await api.get("/api/connectors/github/options?field=workingBranch&repository=o/r")
    assert forms["options_values"]["access_token"] == TOKEN
    # Another user in the same workspace does not get it.
    other = await signed_in(app, api.env, api.env.add_user("Second user"))
    try:
        await other.get("/api/connectors/github/options?field=workingBranch&repository=o/r")
        assert "access_token" not in forms["options_values"]
    finally:
        await other.client.aclose()
        await redis_client().delete(key)


async def test_connector_checks(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from actron.connectors import forms as real

    @dataclass
    class Check:
        id: str
        status: str
        message: str
        title: str = "t"
        troubleshooting: str | None = None

        def as_dict(self) -> dict[str, Any]:
            return dict(self.__dict__)

    async def checks(provider: str, ws: str) -> list[Check]:
        return [Check("scopes", "ok", "All scopes present."), Check("webhook", "pending", "No ping yet.")]

    monkeypatch.setattr(real, "checks", checks)
    r = await api.get("/api/connectors/github/checks")
    assert [c["ok"] for c in r.json()["checks"]] == [True, None]


async def _connect(api: Api, **over: Any) -> httpx.Response:
    body = {"provider": "github", "config": {"repository": "o/r", "workingBranch": "main"},
            "secret": {"access_token": TOKEN}, **over}
    return await api.post("/api/connections", body)


async def test_create_connection_github_makes_two_rows(api: Api, forms: dict[str, Any], gateway: FakeGateway) -> None:
    """A11: one repository form creates `code` and `github` rows, starts backfills and schedules; 409 twice."""
    r = await _connect(api)
    assert r.status_code == 201, r.text
    conn = r.json()["connection"]
    assert conn["provider"] == "github" and conn["secretLast4"] == TOKEN[-4:]
    assert conn["sync"]["state"] == "BACKFILLING"
    assert "access_token" not in str(r.json()) and TOKEN not in r.text
    assert sorted(s[1] for s in gateway.syncs) == ["code", "github"]
    assert ("ensure", api.env.ws, "github") in gateway.schedules
    listed = (await api.get("/api/connections")).json()["connections"]
    assert sorted(c["provider"] for c in listed) == ["code", "github"]
    again = await _connect(api)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_connected"


async def test_create_connection_accepts_the_form_field_id_for_the_working_branch(
        api: Api, forms: dict[str, Any], gateway: FakeGateway) -> None:
    """C-AC-49/50: the Connect form posts its field ids (`working_branch`); the connection stores `workingBranch`."""
    r = await _connect(api, config={"repository": "o/r", "working_branch": "dev"})
    assert r.status_code == 201, r.text
    assert r.json()["connection"]["config"]["workingBranch"] == "dev"


async def test_create_connection_validation(api: Api, forms: dict[str, Any], anon: httpx.AsyncClient) -> None:
    r = await _connect(api, config={"repository": "o/r"})
    assert r.status_code == 422
    forms["ok"] = False
    r = await _connect(api)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert (await api.post("/api/connections", {"provider": "nope", "config": {}})).status_code == 422
    assert (await anon.post("/api/connections", json={})).status_code == 401


async def test_slack_token_connection_adopts_team(api: Api, forms: dict[str, Any], w6: W6Env) -> None:
    """B11a: a token-form Slack connection stores teamId and the workspace adopts the team (W9 ensure_team)."""
    from actron.db import models as m
    from actron.db.session import session_scope

    forms["details"] = {"team_id": "T999", "team": "Acme", "bot_user_id": "B1"}
    r = await api.post("/api/connections", {"provider": "slack", "config": {"channels": ["C1"]},
                                            "secret": {"bot_token": "xoxb-" + "1" * 20, "app_token": "xapp-1-x"}})
    assert r.status_code == 201, r.text
    assert r.json()["connection"]["config"]["teamId"] == "T999"
    with session_scope() as s:
        ws = s.get(m.Workspace, w6.ws)
        assert ws is not None and ws.slack_team_id == "T999"


async def test_patch_working_branch_reingests(api: Api, forms: dict[str, Any], gateway: FakeGateway) -> None:
    """A-AC-97: changing the working branch updates both rows and re-ingests."""
    conn = (await _connect(api)).json()["connection"]
    gateway.syncs.clear()
    r = await api.patch(f"/api/connections/{conn['id']}", {"config": {"workingBranch": "dev"}})
    assert r.status_code == 200 and r.json()["reingest"] is True
    assert r.json()["connection"]["config"]["workingBranch"] == "dev"
    assert gateway.syncs == [(api.env.ws, "code", "backfill")]
    r = await api.patch(f"/api/connections/{conn['id']}", {"config": {"historyDays": 30}})
    assert "reingest" not in r.json()
    assert (await api.patch(f"/api/connections/{conn['id']}", {"config": {}})).status_code == 422
    assert (await api.patch("/api/connections/not-a-uuid", {"config": {"a": 1}})).status_code == 404


async def test_sync_reset_delete(api: Api, forms: dict[str, Any], gateway: FakeGateway) -> None:
    """B.C7: sync now 202, reset cursor, delete 204 (disconnects and pauses), then sync 409."""
    conn = (await _connect(api)).json()["connection"]
    r = await api.post(f"/api/connections/{conn['id']}/sync")
    assert r.status_code == 202 and r.json() == {"triggered": True}
    assert ("trigger", api.env.ws, "github") in gateway.schedules
    assert ("trigger", api.env.ws, "code") in gateway.schedules  # the repository card refreshes both rows
    r = await api.post(f"/api/connections/{conn['id']}/reset-cursor")
    assert r.status_code == 200 and r.json()["connection"]["id"] == conn["id"]
    assert (await api.delete(f"/api/connections/{conn['id']}")).status_code == 204
    assert ("pause", api.env.ws, "code") in gateway.schedules
    listed = (await api.get("/api/connections")).json()["connections"]
    assert {c["status"] for c in listed} == {"disconnected"} and all(c["secretLast4"] is None for c in listed)
    r = await api.post(f"/api/connections/{conn['id']}/sync")
    assert r.status_code == 409
    assert (await _connect(api)).status_code == 201


async def test_slack_export_upload(api: Api, gateway: FakeGateway) -> None:
    """A9a: multipart upload of a Slack export creates the connection and starts the import."""
    import io
    import json
    import zipfile

    bad = {"archive": ("export.zip", b"PK\x03\x04fake", "application/zip")}
    r = await api.client.post("/api/connections", data={"provider": "slack_export"}, files=bad,
                              headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_export"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("users.json", json.dumps([{"id": "U1", "name": "ann"}]))
        zf.writestr("channels.json", json.dumps([{"id": "C1", "name": "general"}]))
        zf.writestr("general/2026-10-01.json", json.dumps([{"type": "message", "user": "U1", "ts": "1.0",
                                                             "text": "hello"}]))
    files = {"archive": ("export.zip", buf.getvalue(), "application/zip")}
    r = await api.client.post("/api/connections", data={"provider": "slack_export"}, files=files,
                              headers={"X-CSRF-Token": api.csrf, "Idempotency-Key": "up-1"})
    assert r.status_code == 201, r.text
    assert r.json()["connection"]["config"]["path"].endswith(".zip")
    assert r.json()["connection"]["provider"] == "slack_export"
    assert (api.env.ws, "slack_export", "backfill") in gateway.syncs
    r = await api.client.post("/api/connections", data={"provider": "slack_export"},
                              headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 422
