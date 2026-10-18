"""A-AC-7: connector secrets are encrypted at rest; a wrong key fails with a typed error. A-AC-8 (last4 only)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from actron.db.crypto import (
    SecretDecryptError,
    SecretKeyMissing,
    decrypt_secret,
    encrypt_secret,
    last4,
)

KEY = Fernet.generate_key().decode()
OTHER = Fernet.generate_key().decode()


def test_round_trip_a_ac_7() -> None:
    """A-AC-7"""
    secret = {"token": "ghp_" + "x" * 36, "nested": {"a": [1, 2]}, "unicode": "café"}
    blob = encrypt_secret(secret, KEY)
    assert decrypt_secret(blob, KEY) == secret


def test_ciphertext_does_not_contain_plaintext_a_ac_7() -> None:
    """A-AC-7"""
    blob = encrypt_secret({"token": "plain-token-value-123456"}, KEY)
    assert b"plain-token-value-123456" not in blob
    assert b"token" not in blob


def test_wrong_key_raises_typed_error_a_ac_7() -> None:
    """A-AC-7"""
    blob = encrypt_secret({"token": "abc"}, KEY)
    with pytest.raises(SecretDecryptError):
        decrypt_secret(blob, OTHER)


def test_garbage_blob_raises_typed_error_a_ac_7() -> None:
    """A-AC-7"""
    with pytest.raises(SecretDecryptError):
        decrypt_secret(b"not a fernet token", KEY)


def test_missing_key_raises_typed_error_a_ac_7(monkeypatch: pytest.MonkeyPatch) -> None:
    """A-AC-7"""
    from actron.config import get_settings

    monkeypatch.setenv("ACTRON_SECRET_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(SecretKeyMissing):
            encrypt_secret({"a": "b"})
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_last4_a_ac_8() -> None:
    """A-AC-8: only the last four characters are ever shown."""
    assert last4("xoxb-123456789-abcd") == "abcd"
    assert last4("ab") == "ab"
    assert last4(None) is None
    assert last4("") is None
