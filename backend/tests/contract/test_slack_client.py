"""Slack client against the fake server: A-AC-53 and error mapping."""

from __future__ import annotations

import pytest

from actron.connectors.common import AuthError, RetryableProviderError
from actron.integrations.slack_client import SlackApiError, SlackClient
from tests.fakes.slack import FakeSlack

BASE = "http://fake.slack/api/"


def _client(fake: FakeSlack, token: str = "xoxb-test-token") -> SlackClient:
    return SlackClient(token, base_url=BASE, transport=fake.transport())


async def test_a_ac_53_ratelimited_raises_retryable_with_retry_after() -> None:
    """A-AC-53: `ratelimited` with Retry-After: 3 raises a retryable error with 3 s."""
    fake = FakeSlack()
    fake.ratelimit("users.list", 3)
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError) as err:
            await c.users_list()
    assert err.value.retry_after == 3


async def test_scopes_are_read_from_the_response_header() -> None:
    fake = FakeSlack(scopes=["chat:write", "channels:read"])
    async with _client(fake) as c:
        body = await c.auth_test()
    assert body["team_id"] == "T0001" and body["user_id"] == "UBOT"
    assert c.scopes == ["chat:write", "channels:read"]


async def test_auth_errors_are_not_retryable() -> None:
    fake = FakeSlack()
    async with _client(fake, "xoxb-wrong") as c:
        with pytest.raises(AuthError) as err:
            await c.auth_test()
    assert err.value.code == "invalid_auth"


async def test_missing_scope_names_the_scope() -> None:
    fake = FakeSlack(scopes=["chat:write"])
    async with _client(fake) as c:
        with pytest.raises(AuthError) as err:
            await c.users_list()
    assert err.value.code == "missing_scope" and "users:read" in str(err.value)


async def test_other_errors_are_typed_with_the_code() -> None:
    fake = FakeSlack()
    fake.add_channel("C1", "eng", is_member=False)
    async with _client(fake) as c:
        with pytest.raises(SlackApiError) as err:
            await c.conversations_history("C1", oldest=None)
    assert err.value.code == "not_in_channel"


async def test_cursor_paging_over_two_pages() -> None:
    fake = FakeSlack()
    for i in range(5):
        fake.add_user(f"U{i + 10}", f"user{i}")
    async with _client(fake) as c:
        pages = [p async for p in c.paginate("users.list", "members", limit=3)]
    assert [len(p) for p in pages] == [3, 3]  # 6 users including the bot


async def test_server_error_is_retryable() -> None:
    fake = FakeSlack()
    fake.fail("auth.test", "internal_error")
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError):
            await c.auth_test()


async def test_socket_mode_open_checks_the_app_token() -> None:
    fake = FakeSlack()
    fake.add_app_token("xapp-good")
    async with _client(fake) as c:
        assert (await c.open_socket_mode("xapp-good"))["url"].startswith("wss://")
        with pytest.raises(AuthError):
            await c.open_socket_mode("xapp-bad")


async def test_app_token_call_does_not_replace_the_bot_scopes() -> None:
    """Real Slack answers `apps.connections.open` with the app token's own scopes in the header; the bot's stay."""
    fake = FakeSlack(scopes=["chat:write", "channels:read"])
    fake.add_app_token("xapp-good")
    async with _client(fake) as c:
        await c.auth_test()
        await c.open_socket_mode("xapp-good")
    assert c.scopes == ["chat:write", "channels:read"]
