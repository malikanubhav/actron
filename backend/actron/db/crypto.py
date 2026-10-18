"""Connector secrets encrypted at rest with Fernet (ACTRON_SECRET_KEY), spec A, A2."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from actron.config import get_settings


class SecretKeyMissing(RuntimeError):
    """ACTRON_SECRET_KEY is not set, so secrets cannot be stored."""


class SecretDecryptError(RuntimeError):
    """The stored secret cannot be decrypted with the configured key."""


def _fernet(key: str | None = None) -> Fernet:
    key = key or get_settings().ACTRON_SECRET_KEY
    if not key:
        raise SecretKeyMissing(
            "ACTRON_SECRET_KEY is not set; generate one with Fernet.generate_key()"
        )
    return Fernet(key.encode())


def encrypt_secret(secret: dict[str, Any], key: str | None = None) -> bytes:
    return _fernet(key).encrypt(json.dumps(secret, sort_keys=True).encode())


def decrypt_secret(blob: bytes, key: str | None = None) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(_fernet(key).decrypt(blob))
    except InvalidToken:
        raise SecretDecryptError(
            "stored secret cannot be decrypted with this ACTRON_SECRET_KEY"
        ) from None
    return data


def last4(value: str | None) -> str | None:
    if not value:
        return None
    return value[-4:]
