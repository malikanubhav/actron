"""A-AC-2, A-AC-3: settings validation fails fast and names the setting; empty keys mean stub."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from actron.config import REPO_ROOT, Settings, SettingsError, load_settings

BACKEND = Path(__file__).resolve().parents[2]

SECRET_FIELDS = [
    name for name in Settings.model_fields if name.endswith(("KEY", "TOKEN", "SECRET"))
]
INTEGRATION_FIELDS = [
    "SLACK_BOT_TOKEN",
    "SLACK_CLIENT_ID",
    "SLACK_CLIENT_SECRET",
    "GITHUB_TOKEN",
    "LINEAR_API_KEY",
    "TYPESAFE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MODEL_DECISION",
    "MODEL_WRITING",
    "MODEL_AGENT",
    "MODEL_CODING",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


def build(**overrides: object) -> Settings:
    return load_settings(_env_file=None, **overrides)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ACTRON_ENV", "staging"),
        ("DATABASE_URL", "mysql://x"),
        ("DATABASE_URL", "not a url"),
        ("REDIS_URL", "http://localhost"),
        ("FALKORDB_URL", "localhost:6389"),
        ("TEMPORAL_ADDRESS", "localhost"),
        ("TEMPORAL_ADDRESS", "localhost:abc"),
        ("ACTRON_SECRET_KEY", "short"),
        ("LINK_KEEP_THRESHOLD", "1.5"),
        ("ACTRON_PORT", "eighty"),
        ("ACTRON_MAX_CONCURRENT_BUILDS", "0"),
        ("FALKORDB_BINDING", "magic"),
    ],
)
def test_invalid_setting_names_the_setting_a_ac_2(name: str, value: str) -> None:
    """A-AC-2"""
    with pytest.raises(SettingsError) as err:
        build(**{name: value})
    assert name in str(err.value)


def test_backend_start_fails_fast_with_message_a_ac_2() -> None:
    """A-AC-2: importing settings with a bad environment exits non-zero and names the variable."""
    env = {**os.environ, "ACTRON_ENV": "staging"}
    proc = subprocess.run(
        [sys.executable, "-c", "from actron.config import get_settings; get_settings()"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "ACTRON_ENV" in proc.stderr


def test_malformed_database_url_fails_at_startup_a_ac_2() -> None:
    """A-AC-2"""
    env = {**os.environ, "DATABASE_URL": "postgres//broken"}
    proc = subprocess.run(
        [sys.executable, "-c", "from actron.config import get_settings; get_settings()"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "DATABASE_URL" in proc.stderr


def test_valid_fernet_key_is_accepted() -> None:
    from cryptography.fernet import Fernet

    assert build(ACTRON_SECRET_KEY=Fernet.generate_key().decode()).ACTRON_SECRET_KEY


def test_all_keys_empty_gives_stub_and_not_connected_a_ac_3() -> None:
    """A-AC-3"""
    settings = build(**{name: "" for name in SECRET_FIELDS + INTEGRATION_FIELDS})
    status = settings.integrations()
    assert status["jev"] == "stub"
    assert status["llm"] == "stub"
    assert status["pi"] == "stub"
    assert status["slack"] == "not_connected"
    assert status["github"] == "not_connected"
    assert status["linear"] == "not_connected"
    assert settings.secret_values() == []


def test_empty_strings_become_none_a_ac_3() -> None:
    """A-AC-3"""
    settings = build(SLACK_BOT_TOKEN="", GITHUB_TOKEN="   ", ACTRON_PUBLIC_URL="")
    assert settings.SLACK_BOT_TOKEN is None
    assert settings.GITHUB_TOKEN is None
    assert settings.ACTRON_PUBLIC_URL is None
    assert settings.slack_channels == []
    assert settings.litellm_fallbacks == []


def test_keys_flip_status_to_live() -> None:
    settings = build(
        SLACK_BOT_TOKEN="xoxb-123456789",
        GITHUB_TOKEN="ghp_aaaaaaaaaaaaaaaaaaaaaaaa",
        LINEAR_API_KEY="lin_api_xxxxxxxxxxxxxxxxx",
        TYPESAFE_API_KEY="tsk-123456",
        ANTHROPIC_API_KEY="sk-ant-123456",
        MODEL_DECISION="anthropic/x",
    )
    status = settings.integrations()
    assert status["slack"] == status["github"] == status["linear"] == "live"
    assert status["jev"] == "live"
    assert status["llm"] == "live"


def test_model_key_without_model_name_stays_stub() -> None:
    assert build(ANTHROPIC_API_KEY="sk-ant-123456").integrations()["llm"] == "stub"


def test_defaults_use_non_default_ports() -> None:
    settings = build()
    assert ":5433/" in settings.DATABASE_URL
    assert settings.REDIS_URL.endswith(":6380/0")
    assert settings.FALKORDB_URL.endswith(":6389")
    assert settings.TEMPORAL_NAMESPACE == "actron"
    assert settings.FALKORDB_BINDING == "params"
    assert settings.ACTRON_ONTOLOGY_DIR == REPO_ROOT / "ontology"


def test_secret_values_lists_only_long_secrets() -> None:
    settings = build(SLACK_BOT_TOKEN="xoxb-1234567890", GITHUB_TOKEN="abc")
    values = settings.secret_values()
    assert "xoxb-1234567890" in values
    assert "abc" not in values


def test_env_example_lists_every_setting_name() -> None:
    """Every variable in .env.example is a known setting, so the example never drifts silently."""
    example = (REPO_ROOT / ".env.example").read_text()
    names = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    known = set(Settings.model_fields) | {
        "FRONTEND_PORT",
        "POSTGRES_PORT",
        "REDIS_PORT",
        "TEMPORAL_PORT",
        "FALKORDB_PORT",
    }  # compose-only
    unknown = {n for n in names if n and n.isupper() and n not in known}
    assert not unknown, f"in .env.example but not in Settings: {sorted(unknown)}"
