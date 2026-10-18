"""GitHub REST client (spec A, A8): auth, timeouts, Link paging, ETags and rate-limit errors."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from actron.config import get_settings
from actron.connectors.common import (
    DEFAULT_TIMEOUT,
    AuthError,
    ForbiddenError,
    NotFoundError,
    ProviderError,
    RetryableProviderError,
    TransientError,
    parse_link_header,
    parse_retry_after,
    transport_for,
    with_backoff,
)

API_VERSION = "2022-11-28"


@dataclass
class Page:
    """One HTTP answer. `status == 304` means nothing changed since the ETag; `data` is then None."""

    status: int
    data: Any
    next_url: str | None = None
    etag: str | None = None
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class GithubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or get_settings().GITHUB_API_URL).rstrip("/")
        self.token = token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "actron",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            transport=transport or transport_for("github"),
        )
        self.rate_remaining: int | None = None
        self.rate_limit: int | None = None
        self.rate_reset: int | None = None
        self.requests_made = 0

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GithubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _absolute(self, path_or_url: str) -> str:
        if path_or_url.startswith("http"):
            # Paging URLs come back from the server; only follow them on the same host.
            if urlsplit(path_or_url).netloc != urlsplit(self.base_url).netloc:
                raise ProviderError(f"refusing to follow a link to another host: {path_or_url}")
            return path_or_url
        return path_or_url if path_or_url.startswith("/") else "/" + path_or_url

    def _note_rate(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.rate_remaining = int(remaining)
        limit = response.headers.get("x-ratelimit-limit")
        if limit is not None and limit.isdigit():
            self.rate_limit = int(limit)
        reset = response.headers.get("x-ratelimit-reset")
        if reset is not None and reset.isdigit():
            self.rate_reset = int(reset)

    def _rate_limited(self, response: httpx.Response) -> RetryableProviderError | None:
        if response.status_code not in (403, 429):
            return None
        headers = response.headers
        retry_after = parse_retry_after(headers.get("retry-after"))
        exhausted = headers.get("x-ratelimit-remaining") == "0"
        text = response.text[:300].lower() if response.status_code == 403 else ""
        secondary = "secondary rate limit" in text or "abuse" in text
        if retry_after is None and not exhausted and response.status_code == 403 and not secondary:
            return None
        if retry_after is None:
            reset = headers.get("x-ratelimit-reset")
            if exhausted and reset and reset.isdigit():
                retry_after = max(1.0, min(3600.0, float(reset) - time.time()))
            else:
                retry_after = 60.0
        return RetryableProviderError(
            f"GitHub rate limit; retry after {retry_after:.0f} s",
            retry_after=retry_after,
            status=response.status_code,
            code="rate_limited",
            url=str(response.request.url),
        )

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
        json: Any = None,
    ) -> httpx.Response:
        url = self._absolute(path_or_url)
        headers = {"If-None-Match": etag} if etag else {}

        async def attempt() -> httpx.Response:
            self.requests_made += 1
            response = await self._client.request(
                method, url, params=params, headers=headers, json=json
            )
            self._note_rate(response)
            if response.status_code >= 500:
                raise TransientError(f"GitHub answered {response.status_code}")
            return response

        response = await with_backoff(attempt)
        status = response.status_code
        if status in (200, 201, 204, 304):
            return response
        limited = self._rate_limited(response)
        if limited is not None:
            raise limited
        shown = str(response.request.url)
        message = _message(response)
        if status == 401:
            raise AuthError(f"GitHub rejected the token: {message}", status=401, url=shown)
        if status == 403:
            raise ForbiddenError(f"GitHub refused: {message}", status=403, url=shown)
        if status == 404:
            raise NotFoundError(f"GitHub could not find {shown}", status=404, url=shown)
        raise ProviderError(f"GitHub answered {status}: {message}", status=status, url=shown)

    async def page(
        self, path_or_url: str, params: dict[str, Any] | None = None, etag: str | None = None
    ) -> Page:
        response = await self.request("GET", path_or_url, params=params, etag=etag)
        url = str(response.request.url)
        headers = {k.lower(): v for k, v in response.headers.items()}
        if response.status_code == 304:
            return Page(304, None, None, etag, url, headers)
        links = parse_link_header(response.headers.get("link"))
        return Page(
            response.status_code,
            response.json(),
            links.get("next"),
            response.headers.get("etag"),
            url,
            headers,
        )

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return (await self.page(path, params)).data

    async def post_json(self, path: str, payload: Any) -> Any:
        response = await self.request("POST", path, json=payload)
        return response.json() if response.content else None

    # Calls used by the connect form and the setup checks
    async def repository(self, full_name: str) -> dict[str, Any]:
        data = await self.get_json(f"/repos/{full_name}")
        assert isinstance(data, dict)
        return data

    async def pull_count(self, full_name: str) -> int | None:
        """Number of pull requests (all states), read from the last page link of a one-item page."""
        response = await self.request(
            "GET", f"/repos/{full_name}/pulls", params={"state": "all", "per_page": 1}
        )
        links = parse_link_header(response.headers.get("link"))
        last = links.get("last")
        if last:
            from urllib.parse import parse_qs

            page = parse_qs(urlsplit(last).query).get("page")
            return int(page[0]) if page else None
        data = response.json()
        return len(data) if isinstance(data, list) else None

    async def branches(self, full_name: str, *, limit: int = 300) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = await self.page(f"/repos/{full_name}/branches", {"per_page": 100})
        while True:
            out.extend(page.data or [])
            if not page.next_url or len(out) >= limit:
                break
            page = await self.page(page.next_url)
        return out[:limit]

    async def commit(self, full_name: str, ref: str) -> dict[str, Any]:
        data = await self.get_json(f"/repos/{full_name}/commits/{ref}")
        assert isinstance(data, dict)
        return data


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])
    except ValueError:
        pass
    return response.text[:200]
