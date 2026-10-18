"""API test fixtures (W6): the FastAPI app over httpx, signed-in clients with CSRF, and a fake gateway."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest_asyncio

from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401


@dataclass
class Api:
    client: httpx.AsyncClient
    csrf: str
    env: W6Env
    user_id: str

    def _headers(self, extra: dict[str, str] | None, csrf: bool, key: str | None) -> dict[str, str]:
        h = {"Idempotency-Key": key or str(uuid.uuid4())}
        if csrf:
            h["X-CSRF-Token"] = self.csrf
        h.update(extra or {})
        return h

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.get(url, **kw)

    async def post(self, url: str, json: Any = None, *, csrf: bool = True, key: str | None = None,
                   headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return await self.client.post(url, json=json, headers=self._headers(headers, csrf, key), **kw)

    async def put(self, url: str, json: Any = None, *, csrf: bool = True, key: str | None = None) -> httpx.Response:
        return await self.client.put(url, json=json, headers=self._headers(None, csrf, key))

    async def patch(self, url: str, json: Any = None, *, csrf: bool = True) -> httpx.Response:
        return await self.client.patch(url, json=json, headers=self._headers(None, csrf, None))

    async def delete(self, url: str, *, csrf: bool = True) -> httpx.Response:
        return await self.client.delete(url, headers=self._headers(None, csrf, None))


async def signed_in(app: Any, env: W6Env, user_id: str) -> Api:
    from actron.api.deps import CSRF_COOKIE, SESSION_COOKIE, create_session

    token, csrf = await create_session(user_id, env.ws)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                               cookies={SESSION_COOKIE: token, CSRF_COOKIE: csrf})
    return Api(client=client, csrf=csrf, env=env, user_id=user_id)


@pytest_asyncio.fixture
async def app(w6: W6Env) -> Any:  # noqa: F811
    from actron.api.app import create_app

    return create_app()


@pytest_asyncio.fixture
async def api(app: Any, w6: W6Env) -> AsyncIterator[Api]:  # noqa: F811
    a = await signed_in(app, w6, w6.owner_id)
    try:
        yield a
    finally:
        await a.client.aclose()


@pytest_asyncio.fixture
async def anon(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()
