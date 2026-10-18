"""HTTP mode signature verification (B-AC-55)."""

from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi import FastAPI

from actron.config import get_settings
from actron.integrations import slack_bot
from tests.integration.slack.slack_fixtures import Bot, sign

PATHS = ("/slack/events", "/slack/commands", "/slack/interactions")
BODY = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()


@pytest.mark.parametrize("path", PATHS)
async def test_B_AC_55_bad_signature_is_401(bot: Bot, path: str) -> None:
    """B-AC-55"""
    headers = sign(BODY, secret="not-the-secret")
    r = await bot.post(path, BODY, "application/json", headers=headers)
    assert r.status_code == 401


async def test_B_AC_55_missing_headers_is_401(bot: Bot) -> None:
    r = await bot.post("/slack/events", BODY, "application/json", headers={})
    assert r.status_code == 401


async def test_B_AC_55_timestamp_older_than_five_minutes_is_401(bot: Bot) -> None:
    old = sign(BODY, ts=int(time.time()) - 6 * 60)  # correctly signed, but stale
    assert (
        await bot.post("/slack/events", BODY, "application/json", headers=old)
    ).status_code == 401
    future = sign(BODY, ts=int(time.time()) + 6 * 60)
    assert (
        await bot.post("/slack/events", BODY, "application/json", headers=future)
    ).status_code == 401


async def test_B_AC_55_tampered_body_is_401(bot: Bot) -> None:
    headers = sign(BODY)
    r = await bot.post("/slack/events", BODY + b" ", "application/json", headers=headers)
    assert r.status_code == 401


async def test_B_AC_55_valid_request_passes_and_nothing_runs_on_rejection(bot: Bot) -> None:
    ok = await bot.post("/slack/events", BODY, "application/json")
    assert ok.status_code == 200 and "abc123" in ok.text
    bad = await bot.command("do it")  # valid, for contrast
    assert bad.status_code == 200
    from urllib.parse import urlencode

    form = urlencode(
        {
            "command": "/actron",
            "text": "evil",
            "team_id": "T123",
            "channel_id": "C1",
            "user_id": "U1",
            "trigger_id": "x.1",
        }
    ).encode()
    rejected = await bot.post(
        "/slack/commands",
        form,
        "application/x-www-form-urlencoded",
        headers=sign(form, secret="bad"),
    )
    assert rejected.status_code == 401
    await slack_bot.drain()
    assert [c["text"] for c in bot.flow.of("create_request")] == ["do it"]


async def test_routes_answer_503_when_no_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "")
    get_settings.cache_clear()
    app = FastAPI()
    slack_bot.mount(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/slack/events", content=BODY, headers=sign(BODY))
    get_settings.cache_clear()
    assert r.status_code == 503
