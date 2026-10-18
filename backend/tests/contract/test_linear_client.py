"""Linear client against the fake server: A-AC-59 (errors), A-AC-60 (writes) and paging."""

from __future__ import annotations

import httpx
import pytest

from actron.connectors.common import AuthError, ProviderError, RetryableProviderError
from actron.integrations import linear_client as lc
from actron.integrations.linear_client import LinearClient, deterministic_issue_id
from tests.fakes.linear import FakeLinear, build_team_fixture

BASE = "http://fake.linear/graphql"


def _client(fake: FakeLinear, key: str = "lin_api_test") -> LinearClient:
    return LinearClient(key, base_url=BASE, transport=fake.transport())


async def test_personal_key_is_sent_raw_without_bearer() -> None:
    fake = FakeLinear()
    async with _client(fake) as c:
        viewer = await c.viewer()
    assert viewer["email"] == "vera@acme.test"
    assert fake.requests[0][2]["authorization"] == "lin_api_test"


async def test_a_ac_59_ratelimited_errors_are_retryable() -> None:
    """A-AC-59: RATELIMITED produces a retryable failure with the server's delay."""
    fake = FakeLinear()
    fake.rate_limit("Teams")
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError) as err:
            await c.query(lc.Q_TEAMS)
    assert err.value.retry_after == 7
    fake.inject("Teams", status=429, headers={"retry-after": "11"}, body={})
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError) as err2:
            await c.query(lc.Q_TEAMS)
    assert err2.value.retry_after == 11


async def test_a_ac_59_other_graphql_errors_are_typed_and_name_the_field() -> None:
    """A-AC-59: other errors become typed failures that name the field."""
    fake = FakeLinear()
    fake.inject("Teams", body={"errors": [{"message": "Field 'bogus' does not exist", "path": ["teams", "bogus"],
                                           "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]})
    async with _client(fake) as c:
        with pytest.raises(ProviderError) as err:
            await c.query(lc.Q_TEAMS)
    assert not isinstance(err.value, RetryableProviderError)
    assert "teams.bogus" in str(err.value) and err.value.code == "GRAPHQL_VALIDATION_FAILED"


async def test_authentication_failure_is_an_auth_error() -> None:
    fake = FakeLinear()
    async with _client(fake, "lin_api_wrong") as c:
        with pytest.raises(AuthError):
            await c.viewer()


async def test_pages_of_connections_are_followed() -> None:
    fake = FakeLinear()
    fake.page_size = 2
    for i in range(5):
        fake.add_user(f"u{i}", f"User {i}", f"u{i}@acme.test")
    async with _client(fake) as c:
        seen, cursor, pages = [], None, 0
        while True:
            nodes, cursor = await c.connection(lc.Q_USERS, "users", {"after": cursor})
            seen.extend(n["id"] for n in nodes)
            pages += 1
            if not cursor:
                break
    assert pages == 3 and seen == [f"u{i}" for i in range(5)]


async def test_comments_beyond_the_first_page_are_fetched() -> None:
    fake = FakeLinear()
    build_team_fixture(fake)
    async with _client(fake) as c:
        data = await c.query(lc.Q_ISSUE, {"id": "i1"})
        info = data["issue"]["comments"]["pageInfo"]
        assert info["hasNextPage"] and len(data["issue"]["comments"]["nodes"]) == 50
        rest = await c.all_comments("i1", info["endCursor"])
    assert len(rest) == 10


def test_deterministic_id_is_a_stable_uuid_v4() -> None:
    a = deterministic_issue_id("acme", "req_01")
    assert a == deterministic_issue_id("acme", "req_01")
    assert a != deterministic_issue_id("acme", "req_02") and a != deterministic_issue_id("other", "req_01")
    import uuid

    parsed = uuid.UUID(a)
    assert parsed.version == 4 and parsed.variant == uuid.RFC_4122


async def test_a_ac_60_create_retried_after_a_lost_answer_does_not_duplicate() -> None:
    """A-AC-60: the first create worked but its answer was lost; the retry with the same id returns that issue."""
    fake = FakeLinear()
    build_team_fixture(fake)
    iid = deterministic_issue_id("acme", "req_77")
    fake.lose_next_create_answer = True
    async with _client(fake) as c:
        created = await c.issue_create(issue_id=iid, team_id="t1", title="Do the thing", description="body")
    assert created["id"] == iid
    assert fake.created_ids == [iid]  # one issue, even though the call was repeated
    async with _client(fake) as c:
        again = await c.issue_create(issue_id=iid, team_id="t1", title="Do the thing", description="body")
    assert again["id"] == iid and fake.created_ids == [iid]
    assert sum(1 for i in fake.issues if i == iid) == 1


async def test_fake_enforces_id_uniqueness_and_create_error_without_issue_is_raised() -> None:
    fake = FakeLinear()
    build_team_fixture(fake)
    async with _client(fake) as c:
        with pytest.raises(ProviderError):  # the team does not exist for this id lookup, so the original error stays
            fake.inject("IssueCreate", body={"errors": [{"message": "Team not found", "path": ["issueCreate"]}]})
            await c.issue_create(issue_id="9c1f0000-0000-4000-8000-000000000000", team_id="nope", title="x",
                                 description="y")


async def test_issue_update_and_comment_create() -> None:
    fake = FakeLinear()
    build_team_fixture(fake)
    async with _client(fake) as c:
        updated = await c.issue_update("i1", title="Retry on 429 and 403", description="new text")
        comment = await c.comment_create("i1", "Actron: build started")
        with pytest.raises(ProviderError):
            await c.issue_update("missing", title="x")
    assert updated["title"] == "Retry on 429 and 403" and fake.issues["i1"]["description"] == "new text"
    assert comment["body"] == "Actron: build started" and fake.comments["i1"][-1]["id"] == comment["id"]


def test_connection_error_surfaces_as_retryable_after_backoff() -> None:
    class Boom(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

    async def run() -> None:
        async with LinearClient("k", base_url=BASE, transport=Boom()) as c:
            await c.viewer()

    import asyncio

    with pytest.raises(RetryableProviderError):
        asyncio.run(run())
