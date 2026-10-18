"""A-AC-5: FalkorDB runtime config equals the values in spec A1 (GRAPH.CONFIG GET) and append-only is on."""

from __future__ import annotations

from typing import Any

import pytest
import redis

pytestmark = pytest.mark.integration

EXPECTED = {
    "THREAD_COUNT": 8,
    "TIMEOUT_MAX": 60000,
    "TIMEOUT_DEFAULT": 15000,
    "MAX_QUEUED_QUERIES": 2000,
    "RESULTSET_SIZE": 10000,
}


@pytest.fixture
def raw(falkordb_url: str) -> Any:
    client = redis.Redis.from_url(falkordb_url)
    yield client
    client.close()


def test_graph_config_matches_spec_a_ac_5(raw: Any) -> None:
    """A-AC-5"""
    config = {
        k.decode() if isinstance(k, bytes) else k: v
        for k, v in raw.execute_command("GRAPH.CONFIG", "GET", "*")
    }
    for name, value in EXPECTED.items():
        assert config[name] == value, f"{name}: {config[name]!r} != {value!r}"


@pytest.mark.parametrize(("name", "value"), list(EXPECTED.items()))
def test_each_setting_individually_a_ac_5(raw: Any, name: str, value: int) -> None:
    """A-AC-5"""
    _, got = raw.execute_command("GRAPH.CONFIG", "GET", name)
    assert got == value


def test_append_only_persistence_is_on_a_ac_5(raw: Any) -> None:
    """A-AC-5"""
    assert raw.config_get("appendonly")["appendonly"] == "yes"


def test_server_version_is_pinned_a_ac_5(raw: Any) -> None:
    """A-AC-5: the image pinned in compose is the one that answers."""
    info = raw.info("server")
    assert "redis_version" in info
    names = {
        str(m.get("name", m.get(b"name", ""))).lower().strip("b'\"") for m in raw.module_list()
    }
    assert "graph" in names
