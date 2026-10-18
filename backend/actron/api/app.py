"""FastAPI app (spec B, B12; B.C7). Run with `uvicorn actron.api.app:app`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from actron.api.deps import ApiError, error_response
from actron.config import Settings, get_settings
from actron.flow.service import ServiceError
from actron.logging import get_logger, request_id_var

log = get_logger(__name__)

_HTTP_CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 422: "invalid", 429: "rate_limited"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("api starting", extra={"env": get_settings().ACTRON_ENV})
    yield


def _install_errors(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> Response:
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> Response:
        return error_response(exc.status, exc.code, exc.message, exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> Response:
        fields = [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "message": e.get("msg", "")}
                  for e in exc.errors()]
        return error_response(422, "invalid", "Some fields are not valid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> Response:
        code = _HTTP_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> Response:
        log.exception("unhandled error", extra={"error": type(exc).__name__})
        return error_response(500, "internal", "Something went wrong on our side. Try again.")


def _install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


def _mount_slack(app: FastAPI) -> None:
    """W9's Slack HTTP handlers and OAuth routes, when installed."""
    try:
        from actron.integrations import slack_bot

        slack_bot.mount(app)
    except Exception as exc:
        log.info("slack bot not mounted", extra={"error": type(exc).__name__})
    try:
        from actron.integrations.slack_oauth import router as slack_oauth_router

        app.include_router(slack_oauth_router)
    except Exception as exc:
        log.info("slack oauth not mounted", extra={"error": type(exc).__name__})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Actron API", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/api/docs",
                  redoc_url=None, lifespan=lifespan)
    _install_errors(app)
    _install_request_id(app)
    from actron.api import auth, sse
    from actron.api.routes import (
        connections,
        connectors,
        graph,
        health,
        ingestion,
        notifications,
        replay,
        requests,
        webhooks,
    )
    from actron.api.routes import (
        settings as settings_routes,
    )

    app.include_router(auth.router)
    if settings.ACTRON_ENV != "prod":
        app.include_router(auth.dev_router)
    for module in (requests, connectors, connections, ingestion, graph, notifications, settings_routes, replay,
                   health, webhooks, sse):
        app.include_router(module.router)
    _mount_slack(app)
    return app


_BUILT: dict[str, FastAPI] = {}


def __getattr__(name: str) -> Any:
    # `uvicorn actron.api.app:app` builds the app on first access, after settings are loaded.
    if name == "app":
        if "app" not in _BUILT:
            _BUILT["app"] = create_app()
        return _BUILT["app"]
    raise AttributeError(name)
