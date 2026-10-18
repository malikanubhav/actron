"""Connector form definitions, validation, options and setup checks (spec B, B.C7; spec C, C12). W3's forms module."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from actron.api.deps import ApiError, Ctx, current, writer
from actron.flow.events import redis_client

router = APIRouter(tags=["connectors"])
PROVIDERS = ("github", "slack", "linear", "slack_export", "code")
SECRET_TTL_S = 15 * 60


class ValidateIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _forms() -> Any:
    try:
        from actron.connectors import forms
    except Exception as exc:
        raise ApiError(503, "not_ready", "Connector forms are not available in this build.") from exc
    return forms


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ApiError(404, "unknown_provider", f"There is no connector called {provider}.")


@router.get("/api/connectors")
async def list_connectors(ctx: Ctx = Depends(current)) -> dict[str, Any]:
    forms = _forms()
    data = forms.load_forms()
    providers = []
    for p in data.get("providers", []):
        item = dict(p)
        item.setdefault("label", item.get("title", item.get("provider")))
        if item.get("provider") == "slack":
            item.setdefault("oauth", {"enabled": bool(item.get("oauth_available")), "url": "/api/slack/install"})
        providers.append(item)
    return {"providers": providers}


def _secret_fields(provider: str) -> set[str]:
    try:
        return set(_forms().form_for(provider).get("secret_fields") or [])
    except Exception:
        return set()


def _secret_key(ctx: Ctx, provider: str) -> str:
    return f"connector-secret:{ctx.ws}:{ctx.user_id}:{provider}"


async def _remember_secrets(ctx: Ctx, provider: str, values: dict[str, Any], errors: dict[str, Any]) -> None:
    """Keep the secrets of a validate call that the provider accepted, encrypted, for the options calls that
    follow (secrets never go in a URL). Short-lived; never logged or returned."""
    secret = {k: v for k, v in values.items() if k in _secret_fields(provider) and v and k not in errors}
    if not secret:
        return
    from actron.db.crypto import encrypt_secret

    blob = encrypt_secret(secret).decode("ascii")
    await redis_client().set(_secret_key(ctx, provider), blob, ex=SECRET_TTL_S)


async def _recall_secrets(ctx: Ctx, provider: str) -> dict[str, Any]:
    blob = await redis_client().get(_secret_key(ctx, provider))
    if not blob:
        return {}
    from actron.db.crypto import decrypt_secret

    try:
        return decrypt_secret(str(blob).encode("ascii"))
    except Exception:
        return {}


@router.post("/api/connectors/{provider}/validate")
async def validate(provider: str, body: ValidateIn, ctx: Ctx = Depends(writer)) -> dict[str, Any]:
    _check_provider(provider)
    result = await _forms().validate(provider, body.values)
    d = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    field_errors = d.get("field_errors") or {}
    if d.get("ok") or not (set(field_errors) & _secret_fields(provider)):
        await _remember_secrets(ctx, provider, body.values, field_errors)
    errors = [{"field": k, "message": v} for k, v in field_errors.items()]
    return {"ok": bool(d.get("ok")), "found": str(d.get("message") or ""), "details": d.get("details") or {},
            "errors": errors, "warnings": d.get("warnings") or []}


@router.get("/api/connectors/{provider}/options")
async def options(provider: str, request: Request, field: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    _check_provider(provider)
    secret_fields = _secret_fields(provider)
    # Secrets are never read from the URL; they come from this user's last accepted validate call.
    values: dict[str, Any] = {k: v for k, v in request.query_params.items()
                              if k != "field" and k not in secret_fields}
    values.update(await _recall_secrets(ctx, provider))
    try:
        opts = await _forms().options(provider, field, values)
    except KeyError as exc:
        raise ApiError(404, "unknown_field", f"{provider} has no options for {field}.") from exc
    except Exception as exc:
        from actron.connectors.common import ProviderError, ValidationError

        if isinstance(exc, ValidationError):
            raise ApiError(422, "check_first", str(exc)) from exc
        if isinstance(exc, ProviderError):
            raise ApiError(502, "provider_error", f"{provider} did not answer: {type(exc).__name__}.") from exc
        raise
    return {"options": list(opts)}


@router.get("/api/connectors/{provider}/checks")
async def checks(provider: str, ctx: Ctx = Depends(current)) -> dict[str, Any]:
    _check_provider(provider)
    results = await _forms().checks(provider, ctx.ws)
    out = []
    for r in results:
        d = r.as_dict() if hasattr(r, "as_dict") else dict(r)
        status = d.get("status")
        out.append({"id": d.get("id"), "ok": True if status == "ok" else False if status == "failed" else None,
                    "message": d.get("message", ""), "troubleshooting": d.get("troubleshooting"),
                    "title": d.get("title")})
    return {"checks": out}
