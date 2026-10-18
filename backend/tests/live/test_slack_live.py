"""Live Slack checks (opt-in): bot token, app token, channel membership and history on the real workspace.

Run: `./scripts/live_smoke.sh slack` with SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env. Read-only; it never posts.
The demo channel is `#arctron-demo` (the typo is real). A bot that is not in it is reported, not fixed:
the user runs `/invite @actron` there.
"""

from __future__ import annotations

import os

import pytest

from actron.integrations.slack_client import SlackClient

pytestmark = [pytest.mark.live, pytest.mark.timeout(120)]
DEMO_CHANNEL = "arctron-demo"


@pytest.fixture
def token() -> str:
    value = os.environ.get("SLACK_BOT_TOKEN", "")
    if not value:
        pytest.skip("SLACK_BOT_TOKEN is not set")
    return value


async def test_bot_token_and_scopes(token: str) -> None:
    async with SlackClient(token) as client:
        auth = await client.auth_test()
        assert auth["ok"] and auth["user_id"] and auth["team_id"]
        assert (await client.team_info())["team"]["id"] == auth["team_id"]
        assert client.scopes, "Slack returned no x-oauth-scopes header"
        for needed in ("channels:history", "channels:read", "chat:write", "commands", "users:read"):
            assert needed in client.scopes, f"bot token lacks scope {needed}"


async def test_app_token_opens_socket_mode() -> None:
    app = os.environ.get("SLACK_APP_TOKEN", "")
    if not app:
        pytest.skip("SLACK_APP_TOKEN is not set")
    async with SlackClient(None) as client:
        opened = await client.open_socket_mode(app)
    assert str(opened["url"]).startswith("wss://")


async def test_demo_channel_is_visible_and_the_bot_is_a_member(token: str) -> None:
    async with SlackClient(token) as client:
        auth = await client.auth_test()
        channels: list[dict[str, object]] = []
        async for page in client.paginate("conversations.list", "channels", {"types": "public_channel,private_channel"}):
            channels.extend(page)
        demo = next((c for c in channels if c.get("name") == DEMO_CHANNEL), None)
        assert demo is not None, f"#{DEMO_CHANNEL} not found by the bot"
        assert demo.get("is_member") is True, f"the bot is not in #{DEMO_CHANNEL}: run /invite @actron there"
        members = await client.conversations_members(str(demo["id"]))
        assert auth["user_id"] in members["members"]
        history = await client.conversations_history(str(demo["id"]), oldest=None, limit=20)
        assert any(m.get("text") for m in history["messages"]), "no readable message in the demo channel"
