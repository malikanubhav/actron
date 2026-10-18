"""`GET /api/health` (spec A, A1): stores and integrations; 503 when a store is down."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from actron.config import get_settings
from actron.health import all_stores_ok, check_health

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> JSONResponse:
    result: dict[str, Any] = await check_health(get_settings())
    return JSONResponse(result, status_code=200 if all_stores_ok(result) else 503)
