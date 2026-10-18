"""Slack manifests (B-AC-86): parse, contain every scope, event and command, match the backend routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import yaml
from fastapi import FastAPI

from actron.config import REPO_ROOT
from actron.integrations import slack_bot, slack_oauth
from actron.integrations.slack_common import BOT_EVENTS, BOT_SCOPES, USER_SCOPES

SLACK = REPO_ROOT / "infra" / "slack"
HTTP = SLACK / "manifest.yaml"
DEV = SLACK / "manifest.dev.yaml"
HOST = "https://actron.example.com"

# Written out here from spec B, B12a so a change to the constants cannot silently change the manifest.
SPEC_BOT_SCOPES = {
    "app_mentions:read",
    "channels:history",
    "channels:read",
    "chat:write",
    "commands",
    "groups:history",
    "groups:read",
    "im:write",
    "reactions:read",
    "team:read",
    "users:read",
    "users:read.email",
}
SPEC_USER_SCOPES = {"openid", "profile", "email"}
SPEC_EVENTS = {
    "app_mention",
    "message.channels",
    "message.groups",
    "member_joined_channel",
    "channel_rename",
    "app_uninstalled",
    "tokens_revoked",
}

ALLOWED_TOP = {"display_information", "features", "oauth_config", "settings", "_metadata"}
ALLOWED_FEATURES = {
    "app_home",
    "bot_user",
    "slash_commands",
    "shortcuts",
    "unfurl_domains",
    "agent_view",
    "assistant_view",
}
ALLOWED_SETTINGS = {
    "event_subscriptions",
    "interactivity",
    "org_deploy_enabled",
    "socket_mode_enabled",
    "token_rotation_enabled",
    "allowed_ip_address_ranges",
    "function_runtime",
}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_constants_equal_the_spec_lists() -> None:
    assert set(BOT_SCOPES) == SPEC_BOT_SCOPES and len(BOT_SCOPES) == len(SPEC_BOT_SCOPES)
    assert set(USER_SCOPES) == SPEC_USER_SCOPES
    assert set(BOT_EVENTS) == SPEC_EVENTS


@pytest.mark.parametrize("path", [HTTP, DEV], ids=["http", "dev"])
def test_B_AC_86_manifest_has_every_scope_event_and_command(path: Path) -> None:
    """B-AC-86"""
    m = load(path)
    assert set(m["oauth_config"]["scopes"]["bot"]) == SPEC_BOT_SCOPES
    assert set(m["oauth_config"]["scopes"]["user"]) == SPEC_USER_SCOPES
    assert set(m["settings"]["event_subscriptions"]["bot_events"]) == SPEC_EVENTS
    assert [c["command"] for c in m["features"]["slash_commands"]] == ["/actron"]
    assert m["settings"]["interactivity"]["is_enabled"] is True
    assert m["settings"]["org_deploy_enabled"] is False


@pytest.mark.parametrize("path", [HTTP, DEV], ids=["http", "dev"])
def test_B_AC_86_manifest_follows_slacks_schema_limits(path: Path) -> None:
    """Key names and limits from docs.slack.dev/reference/app-manifest (fetched 17 Oct 2026)."""
    m = load(path)
    assert set(m) <= ALLOWED_TOP and {"display_information"} <= set(m)
    info = m["display_information"]
    assert len(info["name"]) <= 35 and len(info.get("description", "")) <= 140
    assert re.fullmatch(r"#[0-9A-Fa-f]{3}|#[0-9A-Fa-f]{6}", info["background_color"])
    f = m["features"]
    assert set(f) <= ALLOWED_FEATURES
    assert re.fullmatch(r"[a-z0-9._-]{1,80}", f["bot_user"]["display_name"])
    for c in f["slash_commands"]:
        assert c["command"].startswith("/") and len(c["command"]) <= 32
        assert 0 < len(c["description"]) <= 2000 and len(c.get("usage_hint", "")) <= 1000
        assert "url" not in c or c["url"].startswith("https://")
    assert set(m["settings"]) <= ALLOWED_SETTINGS
    assert len(m["oauth_config"]["scopes"]["bot"]) <= 255


def test_http_manifest_points_at_the_backend_routes() -> None:
    m = load(HTTP)
    events = m["settings"]["event_subscriptions"]["request_url"]
    interact = m["settings"]["interactivity"]["request_url"]
    command = m["features"]["slash_commands"][0]["url"]
    assert (events, command, interact) == (
        f"{HOST}/slack/events",
        f"{HOST}/slack/commands",
        f"{HOST}/slack/interactions",
    )
    assert m["settings"]["socket_mode_enabled"] is False

    app = FastAPI()
    slack_bot.mount(app)
    app.include_router(slack_oauth.router)
    routes = {(r.path, tuple(sorted(r.methods or ()))) for r in app.routes if hasattr(r, "methods")}  # type: ignore[attr-defined]
    for url in (events, command, interact):
        assert (urlparse(url).path, ("POST",)) in routes, url
    redirects = m["oauth_config"]["redirect_urls"]
    assert f"{HOST}/api/slack/oauth/callback" in redirects  # "Add to Slack"
    assert f"{HOST}/api/auth/slack/callback" in redirects  # Sign in with Slack
    paths = app.openapi()["paths"]  # included routers are resolved lazily; the schema lists them
    assert "get" in paths["/api/slack/oauth/callback"] and "get" in paths["/api/slack/install"]
    assert all(u.startswith("https://") for u in redirects)


def test_every_host_placeholder_is_the_documented_one() -> None:
    hosts = set(re.findall(r"https://[\w.-]+", HTTP.read_text(encoding="utf-8")))
    assert hosts == {"https://actron.example.com"}


def test_dev_manifest_uses_socket_mode_and_has_no_request_urls() -> None:
    m = load(DEV)
    assert m["settings"]["socket_mode_enabled"] is True
    assert "request_url" not in m["settings"]["event_subscriptions"]
    assert "request_url" not in m["settings"]["interactivity"]
    assert "url" not in m["features"]["slash_commands"][0]
    assert "redirect_urls" not in m["oauth_config"]
    assert "example.com" not in DEV.read_text(encoding="utf-8").replace(
        "example.com host to replace", ""
    )


def test_the_install_url_requests_the_manifest_scopes() -> None:
    assert set(BOT_SCOPES) == set(load(HTTP)["oauth_config"]["scopes"]["bot"])
