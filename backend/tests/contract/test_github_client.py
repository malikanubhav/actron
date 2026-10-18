"""GitHub client against the fake server: A-AC-44."""

from __future__ import annotations

import pytest

from actron.connectors.common import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    RetryableProviderError,
    parse_link_header,
    parse_retry_after,
)
from actron.integrations.github_client import GithubClient
from tests.fakes.github import FakeGithub, user

BASE = "http://fake.github"


def _client(fake: FakeGithub, token: str | None = "t0ken") -> GithubClient:
    return GithubClient(token, base_url=BASE, transport=fake.transport())


def _seed(fake: FakeGithub, n: int = 5) -> None:
    fake.add_repo("acme/widgets", repo_id=1)
    for i in range(1, n + 1):
        fake.add_pull("acme/widgets", i, title=f"PR {i}", author=user(1, "a"),
                      updated_at=f"2026-01-{i:02d}T00:00:00Z")


async def test_a_ac_44_paging_over_three_pages() -> None:
    """A-AC-44: three pages followed through the Link header."""
    fake = FakeGithub()
    _seed(fake, 5)
    async with _client(fake) as c:
        seen: list[int] = []
        page = await c.page("/repos/acme/widgets/pulls", {"state": "all", "per_page": 2})
        pages = 1
        while True:
            seen.extend(p["number"] for p in page.data)
            if not page.next_url:
                break
            page = await c.page(page.next_url)
            pages += 1
    assert pages == 3
    assert sorted(seen) == [1, 2, 3, 4, 5]


async def test_a_ac_44_etag_304_short_circuits() -> None:
    """A-AC-44: a stored ETag turns an unchanged listing into a 304 with no data."""
    fake = FakeGithub()
    _seed(fake)
    async with _client(fake) as c:
        first = await c.page("/repos/acme/widgets/pulls", {"state": "all"})
        again = await c.page("/repos/acme/widgets/pulls", {"state": "all"}, etag=first.etag)
        assert first.status == 200 and first.etag
        assert again.status == 304 and again.data is None
        fake.touch_pull("acme/widgets", 1, "2026-02-01T00:00:00Z", title="changed")
        changed = await c.page("/repos/acme/widgets/pulls", {"state": "all"}, etag=first.etag)
        assert changed.status == 200


async def test_a_ac_44_429_with_retry_after_is_retryable() -> None:
    """A-AC-44: 429 with Retry-After raises a retryable error carrying that delay."""
    fake = FakeGithub()
    _seed(fake)
    fake.inject("/pulls$", 429, headers={"retry-after": "17"})
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError) as err:
            await c.page("/repos/acme/widgets/pulls")
    assert err.value.retry_after == 17


async def test_a_ac_44_403_rate_limit_is_retryable() -> None:
    """A-AC-44: 403 with x-ratelimit-remaining 0 likewise, delay from the reset header."""
    import time

    fake = FakeGithub()
    _seed(fake)
    reset = str(int(time.time()) + 42)
    fake.inject("/pulls$", 403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset})
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError) as err:
            await c.page("/repos/acme/widgets/pulls")
    assert err.value.retry_after is not None and 35 <= err.value.retry_after <= 43


async def test_a_ac_44_plain_403_is_forbidden_not_retryable() -> None:
    fake = FakeGithub()
    _seed(fake)
    fake.inject("/pulls$", 403, body={"message": "Resource not accessible by personal access token"})
    async with _client(fake) as c:
        with pytest.raises(ForbiddenError):
            await c.page("/repos/acme/widgets/pulls")


async def test_a_ac_44_404_and_401_are_typed() -> None:
    fake = FakeGithub()
    _seed(fake)
    async with _client(fake) as c:
        with pytest.raises(NotFoundError):
            await c.get_json("/repos/acme/widgets/pulls/99")
    fake.inject("/repos/acme/widgets$", 401)
    async with _client(fake) as c:
        with pytest.raises(AuthError):
            await c.repository("acme/widgets")


async def test_server_errors_are_retried_then_raised_retryable() -> None:
    fake = FakeGithub()
    _seed(fake)
    fake.inject("/repos/acme/widgets$", 502, times=2)
    async with _client(fake) as c:
        assert (await c.repository("acme/widgets"))["id"] == 1  # third attempt succeeds
    fake.inject("/repos/acme/widgets$", 502, times=10)
    async with _client(fake) as c:
        with pytest.raises(RetryableProviderError):
            await c.repository("acme/widgets")


async def test_rate_remaining_is_recorded_and_token_sent() -> None:
    fake = FakeGithub()
    _seed(fake)
    fake.rate_remaining = 123
    async with _client(fake, "abc") as c:
        await c.repository("acme/widgets")
        assert c.rate_remaining == 123
    sent = fake.requests[-1][2]
    assert sent["authorization"] == "Bearer abc"
    assert sent["x-github-api-version"] == "2022-11-28"
    async with _client(fake, None) as c:
        await c.repository("acme/widgets")
    assert "authorization" not in fake.requests[-1][2]


async def test_refuses_links_to_other_hosts() -> None:
    fake = FakeGithub()
    async with _client(fake) as c:
        with pytest.raises(Exception, match="another host"):
            await c.page("https://evil.example/repos/a/b/pulls")


def test_link_header_and_retry_after_parsing() -> None:
    header = '<https://x/p?page=2>; rel="next", <https://x/p?page=9>; rel="last"'
    assert parse_link_header(header) == {"next": "https://x/p?page=2", "last": "https://x/p?page=9"}
    assert parse_link_header(None) == {}
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None
