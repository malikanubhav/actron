"""No secrets in any response (spec B, B12; B-AC-60, A-AC-8)."""

from __future__ import annotations

from typing import Any

import pytest

from actron.config import get_settings
from tests.api._fixtures import FakeGateway, W6Env
from tests.api.conftest import Api

CONNECTOR_SECRET = "ghp_" + "S" * 36
WEBHOOK_SECRET = "whsec-very-secret-value"


@pytest.fixture
def ok_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    from actron.connectors import forms

    class R:
        def as_dict(self) -> dict[str, Any]:
            return {"ok": True, "message": "ok", "field_errors": {}, "details": {}, "warnings": []}

    async def validate(provider: str, values: dict[str, Any]) -> R:
        return R()

    monkeypatch.setattr(forms, "validate", validate)


async def test_no_secret_in_any_json_response(api: Api, w6: W6Env, gateway: FakeGateway, ok_forms: None) -> None:
    """B-AC-60: scan every GET response (after storing a connector secret) for setting secrets and the
    connector's token, webhook secret and encrypted blob."""
    r = await api.post("/api/connections", {"provider": "github",
                                            "config": {"repository": "o/r", "workingBranch": "main"},
                                            "secret": {"access_token": CONNECTOR_SECRET,
                                                       "webhook_secret": WEBHOOK_SECRET}})
    assert r.status_code == 201
    rid = (await api.post("/api/requests", {"text": "Add an export", "kindHint": "feature"})).json()["request"]["id"]
    bodies = [r.text]
    for path in ("/api/me", "/api/connections", "/api/settings", "/api/ingestion/status", "/api/ingestion/runs",
                 "/api/requests", f"/api/requests/{rid}", f"/api/requests/{rid}/ticket/revisions",
                 "/api/notifications", "/api/connectors", "/api/openapi.json", "/api/graph/stats"):
        resp = await api.get(path)
        assert resp.status_code == 200, path
        bodies.append(resp.text)
    forbidden = [CONNECTOR_SECRET, WEBHOOK_SECRET, "secret_encrypted", "secretEncrypted"]
    forbidden += [v for v in get_settings().secret_values() if len(v) >= 8]
    for body in bodies:
        for secret in forbidden:
            assert secret not in body
    assert CONNECTOR_SECRET[-4:] in bodies[0]
