"""BuildEnv from settings: clone and push URLs from GITHUB_GIT_URL, fake-Pi variables only outside prod (B-AC-44)."""

from __future__ import annotations

import pytest

from actron.config import get_settings
from actron.flow.build import BuildEnv, BuildInput, preflight


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("ACTRON_BOT_NAME", "Actron Bot")
    monkeypatch.setenv("ACTRON_BOT_EMAIL", "bot@actron.test")
    monkeypatch.setenv("MODEL_CODING", "anthropic/claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000000000000000")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _inp() -> BuildInput:
    return BuildInput(ws="w", request_id="req_1", build_id="b1", revision_hash="a" * 64, ticket={},
                      repository="acme/calc", push_target="acme/calc-fork", upstream="acme/calc")


def test_b_ac_44_push_and_clone_urls_follow_github_git_url(settings_env: pytest.MonkeyPatch) -> None:
    """B-AC-44: the push URL is built from GITHUB_GIT_URL and never carries credentials."""
    env = BuildEnv.from_settings()
    assert preflight(_inp(), env) == ("acme/calc-fork", "https://github.com/acme/calc-fork.git")
    settings_env.setenv("GITHUB_GIT_URL", "file:///srv/git/")
    get_settings.cache_clear()
    env = BuildEnv.from_settings()
    assert preflight(_inp(), env)[1] == "file:///srv/git/acme/calc-fork.git"
    assert get_settings().git_url("acme/calc") == "file:///srv/git/acme/calc.git"


def test_pi_extra_env_is_ignored_in_prod(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("ACTRON_PI_EXTRA_ENV", '{"FAKE_PI_SCENARIO": "fail_then_repair"}')
    get_settings.cache_clear()
    assert BuildEnv.from_settings().pi_extra_env == {"FAKE_PI_SCENARIO": "fail_then_repair"}
    settings_env.setenv("ACTRON_ENV", "prod")
    get_settings.cache_clear()
    assert BuildEnv.from_settings().pi_extra_env == {}


def test_bot_identity_prefers_workspace_settings_then_env(settings_env: pytest.MonkeyPatch) -> None:
    """Settings' stored bot identity wins per field; `.env` fills what Settings leaves empty."""
    env = BuildEnv.from_settings()
    assert (env.bot_name, env.bot_email) == ("Actron Bot", "bot@actron.test")
    both = env.with_bot_identity({"name": "Ws Bot", "email": "ws@example.test"})
    assert (both.bot_name, both.bot_email) == ("Ws Bot", "ws@example.test")
    name_only = env.with_bot_identity({"name": "Ws Bot", "email": " "})
    assert (name_only.bot_name, name_only.bot_email) == ("Ws Bot", "bot@actron.test")
    assert env.with_bot_identity(None) == env
    assert (env.bot_name, env.bot_email) == ("Actron Bot", "bot@actron.test")  # the original is unchanged


def test_bot_identity_from_settings_alone_passes_preflight(settings_env: pytest.MonkeyPatch) -> None:
    """Without `.env` identity, a workspace identity is enough for the preflight check."""
    settings_env.setenv("ACTRON_BOT_NAME", "")
    settings_env.setenv("ACTRON_BOT_EMAIL", "")
    get_settings.cache_clear()
    env = BuildEnv.from_settings()
    with pytest.raises(Exception, match="ACTRON_BOT_NAME"):
        preflight(_inp(), env)
    ok = env.with_bot_identity({"name": "Ws Bot", "email": "ws@example.test"})
    assert preflight(_inp(), ok)[0] == "acme/calc-fork"


def test_deepseek_model_maps_to_pi_provider_and_key(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("MODEL_CODING", "deepseek/deepseek-v4-pro")
    settings_env.setenv("DEEPSEEK_API_KEY", "sk-test-0000000000000000")
    get_settings.cache_clear()
    assert BuildEnv.from_settings().model_choice() == ("deepseek/deepseek-v4-pro", "DEEPSEEK_API_KEY")
