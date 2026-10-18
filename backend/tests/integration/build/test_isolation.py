"""Credential isolation of the Pi and test containers (spec B, B-AC-45 and B-AC-46)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from actron.flow import test_runner as tr
from actron.flow.build import (
    CREDENTIAL_HELPER,
    BuildEnv,
    BuildInput,
    BuildPaths,
    LocalBuildSteps,
    pi_docker_command,
    run_build,
)
from tests.integration.build.conftest import (
    GITHUB_TOKEN,
    MODEL_KEY,
    Events,
    FakeGitHub,
    SyntheticRepo,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]

FORBIDDEN = ("GITHUB_TOKEN", "SLACK_", "LINEAR_", "DATABASE_URL", "ACTRON_SECRET_KEY", "SESSION_SECRET",
             "TYPESAFE_API_KEY")
MODEL_KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")
HOST_SECRETS = {
    "GITHUB_TOKEN": GITHUB_TOKEN, "SLACK_BOT_TOKEN": "xoxb-host-secret-123456", "LINEAR_API_KEY": "lin_api_host0000000000000000",
    "DATABASE_URL": "postgresql://u:p@db/x", "ACTRON_SECRET_KEY": "host-fernet-key-000000000000",
    "OPENROUTER_API_KEY": "sk-or-host-0000000000000000",
}


def _forbidden(name: str) -> bool:
    return any(name == f or (f.endswith("_") and name.startswith(f)) for f in FORBIDDEN)


def test_pi_docker_command_has_one_model_key_and_no_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-AC-45: the docker run arguments and environment contain exactly one model key and no other credential."""
    for k, v in HOST_SECRETS.items():
        monkeypatch.setenv(k, v)
    env = BuildEnv(host_dir=tmp_path, model_coding="anthropic/claude-sonnet-4-5",
                   model_keys={"ANTHROPIC_API_KEY": MODEL_KEY, "OPENROUTER_API_KEY": "sk-or-x" * 4,
                               "GEMINI_API_KEY": "g" * 30, "GROQ_API_KEY": "q" * 30},
                   github_token=GITHUB_TOKEN, bot_name="b", bot_email="b@x")
    inp = BuildInput(ws="w", request_id="req_1", build_id="b1", revision_hash="h" * 64, ticket={})
    cmd = pi_docker_command(inp, env, attempt=1, run_token="run_tok_secret")
    argv = " ".join(cmd.argv)
    # Secrets never appear as values in the arguments.
    for secret in [MODEL_KEY, GITHUB_TOKEN, "run_tok_secret", *HOST_SECRETS.values()]:
        assert secret not in argv
    passed = [cmd.argv[i + 1].split("=", 1)[0] for i, a in enumerate(cmd.argv) if a == "-e"]
    assert [n for n in passed if n in MODEL_KEY_NAMES] == ["ANTHROPIC_API_KEY"]
    assert not [n for n in passed if _forbidden(n)]
    assert set(passed) == {"ANTHROPIC_API_KEY", "ACTRON_MCP_URL", "ACTRON_RUN_TOKEN"}
    # The docker CLI's own environment carries only the selected key (docker forwards only `-e` names).
    assert [k for k in cmd.env if k in MODEL_KEY_NAMES] == ["ANTHROPIC_API_KEY"]
    assert not [k for k in cmd.env if _forbidden(k)]
    assert cmd.env["ANTHROPIC_API_KEY"] == MODEL_KEY
    # The B9 flags.
    for flag in ("--rm", "--read-only", "--network", "--cpus", "--memory", "--pids-limit", "--tmpfs"):
        assert flag in cmd.argv
    assert cmd.argv[cmd.argv.index("--network") + 1] == "actron-build"
    assert f"{tmp_path / 'b1' / 'context'}:/context:ro" in cmd.argv


async def test_real_run_container_env_and_push_never_expose_token(
    build_env_factory: Callable[..., BuildEnv], make_input: Callable[..., BuildInput], events: Events,
    fake_github: FakeGitHub, synthetic_repo: SyntheticRepo, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-AC-45: inside the Pi container only one model key exists; the push uses the helper, never argv or URL."""
    for k, v in HOST_SECRETS.items():
        monkeypatch.setenv(k, v)
    env = build_env_factory("env_dump")
    inp = make_input()
    steps = LocalBuildSteps(env, emit=events, github_transport=fake_github.transport)
    result = await run_build(inp, steps)
    assert result.status == "passed", result
    notes = (BuildPaths.for_build(env.host_dir, inp.build_id).context / "notes.md").read_text()
    names = notes.split("ENV\n", 1)[1].split()
    assert [n for n in names if n in MODEL_KEY_NAMES] == ["ANTHROPIC_API_KEY"]
    assert not [n for n in names if _forbidden(n)], names
    # Every recorded command: the token is never in the arguments.
    for rec in steps.runner.records:
        assert GITHUB_TOKEN not in " ".join(rec.argv)
        if rec.argv[0] == "git":
            assert "GITHUB_TOKEN" not in rec.env or any(a in rec.argv for a in ("push", "clone", "fetch"))
    push = next(r for r in steps.runner.records if "push" in r.argv)
    assert push.env["GITHUB_TOKEN"] == GITHUB_TOKEN
    assert any(a.startswith("credential.helper=/") for a in push.argv)
    repo = BuildPaths.for_build(env.host_dir, inp.build_id).repo
    url = subprocess.run(["git", "remote", "get-url", "actron-push"], cwd=repo, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert url == str(synthetic_repo.fork) and GITHUB_TOKEN not in url
    config = (repo / ".git" / "config").read_text()
    assert GITHUB_TOKEN not in config


def test_credential_helper_reads_token_from_its_environment(tmp_path: Path) -> None:
    """B-AC-45: the helper answers `get` from GITHUB_TOKEN in its own environment and nothing else."""
    helper = tmp_path / "helper"
    helper.write_text(CREDENTIAL_HELPER)
    helper.chmod(0o700)
    out = subprocess.run([str(helper), "get"], input="protocol=https\nhost=github.com\n\n", capture_output=True,
                         text=True, env={"PATH": os.environ["PATH"], "GITHUB_TOKEN": "tok-123"})
    assert out.stdout.splitlines() == ["username=x-access-token", "password=tok-123"]
    assert subprocess.run([str(helper), "store"], capture_output=True, text=True,
                          env={"GITHUB_TOKEN": "tok-123"}).stdout == ""
    assert subprocess.run([str(helper), "get"], capture_output=True, text=True, env={}).stdout == ""
    assert "tok-123" not in CREDENTIAL_HELPER


async def test_test_containers_inspected_no_network_no_credentials(
    tmp_path: Path, test_runner_image: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-AC-46: `docker inspect` shows the run container has no network and the prepare container no credentials."""
    for k, v in HOST_SECRETS.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "requirements.txt").write_text("# no dependencies\n")
    (repo / "tests" / "test_one.py").write_text("def test_one():\n    assert 1 + 1 == 2\n")
    cfg = tr.TestRunConfig(image=test_runner_image, cache_root=tmp_path / "cache", timeout_seconds=120)
    result = await tr.run_tests(repo, tmp_path / "reports", "iso1", "pytest -q", "repo_default", cfg)
    assert result.passed == 1 and result.failed == 0 and result.parser == "junit"
    assert result.isolation is not None and result.isolation.network_mode == "none"
    assert result.prepare_isolation is not None
    assert result.prepare_isolation.network_mode != "none"
    for iso in (result.isolation, result.prepare_isolation):
        assert not [n for n in iso.env_names if _forbidden(n) or n in MODEL_KEY_NAMES], iso.env_names
    assert subprocess.run(["docker", "inspect", "actron-test-run-iso1"], capture_output=True).returncode != 0
    # The second run reuses the dependency cache: no prepare container.
    again = await tr.run_tests(repo, tmp_path / "reports", "iso2", "pytest -q", "repo_default", cfg)
    assert again.prepare_isolation is None and again.passed == 1


async def test_offline_container_really_has_no_network(tmp_path: Path, test_runner_image: str) -> None:
    """B-AC-46: a test that tries the network fails inside the run container."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pytest.ini").write_text("[pytest]\n")
    (repo / "tests" / "test_net.py").write_text(
        "import socket\n\ndef test_net():\n    socket.create_connection(('1.1.1.1', 53), timeout=2)\n")
    cfg = tr.TestRunConfig(image=test_runner_image, cache_root=tmp_path / "cache", timeout_seconds=120)
    result = await tr.run_tests(repo, tmp_path / "reports", "net1", "pytest -q", "repo_default", cfg)
    assert result.failed == 1 and result.failing[0].name.endswith("test_net")
