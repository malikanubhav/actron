"""A-AC-1 (stores side): check_health reports each store and the integration summary; compose lists every service."""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from actron.config import REPO_ROOT, get_settings, load_settings
from actron.health import all_stores_ok, app_version, check_health

pytestmark = pytest.mark.integration

REQUIRED_SERVICES = {
    "falkordb",
    "postgres",
    "redis",
    "temporal",
    "temporal-ui",
    "backend",
    "worker",
    "frontend",
    "backup",
}


async def test_all_stores_ok_against_running_stack_a_ac_1(
    falkordb_url: str, db_url: str, redis_url: str, temporal_address: str
) -> None:
    """A-AC-1: the health call returns the A1 shape with every store ok."""
    settings = load_settings(DATABASE_URL=db_url)
    health = await check_health(settings)
    assert {k: health[k] for k in ("falkordb", "postgres", "redis", "temporal")} == {
        "falkordb": "ok",
        "postgres": "ok",
        "redis": "ok",
        "temporal": "ok",
    }
    assert all_stores_ok(health)
    assert set(health["integrations"]) >= {"jev", "llm", "slack", "github", "linear"}
    assert health["version"] == app_version()
    assert health["falkordb_binding"] in ("params", "literal")


async def test_one_dead_store_is_reported_without_hanging_a_ac_1(
    falkordb_url: str, redis_url: str
) -> None:
    """A-AC-1: an unreachable store shows `error`, the others stay `ok`, and the call is quick."""
    settings = load_settings(
        REDIS_URL="redis://127.0.0.1:1/0",
        DATABASE_URL=get_settings().DATABASE_URL.replace(":5433", ":1"),
    )
    start = time.monotonic()
    health = await check_health(settings)
    assert time.monotonic() - start < 8
    assert health["redis"] == "error"
    assert health["postgres"] == "error"
    assert health["falkordb"] == "ok"
    assert not all_stores_ok(health)


async def test_dead_temporal_is_error_a_ac_1(falkordb_url: str) -> None:
    """A-AC-1"""
    settings = load_settings(TEMPORAL_ADDRESS="127.0.0.1:1")
    health = await check_health(settings)
    assert health["temporal"] == "error"


async def test_health_never_contains_secret_values(falkordb_url: str) -> None:
    """A-AC-4: the health payload only has statuses."""
    settings = load_settings(SLACK_BOT_TOKEN="xoxb-should-not-appear-123456")
    health = await check_health(settings)
    assert "xoxb-should-not-appear" not in json.dumps(health)
    assert health["integrations"]["slack"] == "live"


def test_compose_defines_every_service_a_ac_1() -> None:
    """A-AC-1: `make up` starts these services (the compose file is valid and lists them all)."""
    out = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPO_ROOT / "infra" / "compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    services = set(json.loads(out.stdout)["services"])
    assert services >= REQUIRED_SERVICES


def test_compose_pins_images_a_ac_1() -> None:
    """A-AC-1: no `latest` tags, so the demo cannot change underneath us."""
    out = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPO_ROOT / "infra" / "compose.yaml"),
            "--profile",
            "images",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    for name, svc in json.loads(out.stdout)["services"].items():
        image = svc.get("image", "")
        if name in {"backend", "frontend", "worker"} or image.startswith("actron-"):
            continue
        assert ":" in image and not image.endswith(":latest"), f"{name}: {image}"
