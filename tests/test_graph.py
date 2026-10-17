"""Approved narrow safety seam: literal binding against a real FalkorDB server."""

import json
import os
import uuid
from collections.abc import Iterator

import pytest

from actron.graph import FalkorStore


@pytest.fixture
def store() -> Iterator[FalkorStore]:
    graph = FalkorStore(
        os.getenv("ACTRON_REDIS_URL", "redis://127.0.0.1:6389/0"),
        "binding_" + uuid.uuid4().hex,
    )
    try:
        yield graph
    finally:
        graph.redis.execute_command("GRAPH.DELETE", graph.graph)


def test_store_treats_attack_text_and_placeholder_tokens_as_data(store: FalkorStore) -> None:
    kind = 'Policy"}) MATCH (n) DETACH DELETE n // $payload'
    key = "$payload $kind $key \\ \" ' \n 👋"
    payload = {
        "id": key,
        "text": '"} SET n.payload="poisoned" // $key $kind $payload',
        "unicode": "café 👋",
        "control": "\u0000\t\n\\end",
    }
    sentinel = {"id": "sentinel", "text": "preserve independently stored evidence"}
    store.put("Sentinel", "sentinel", sentinel)
    store.put(kind, key, payload)
    assert store.get(kind, key) == payload
    assert store.get("Sentinel", "sentinel") == sentinel
    assert store.list(kind) == [payload]
    assert store.query("MATCH (n:Record) RETURN count(n)") == [[2]]
    provenance = {"source": key, "content": payload["text"]}
    store.link(kind, key, "SUPPORTED_BY", "Sentinel", "sentinel", provenance)
    rows = store.query("MATCH ()-[r:SUPPORTED_BY]->() RETURN r.provenance")
    assert json.loads(rows[0][0]) == provenance


def test_binding_rejects_missing_unused_or_unsafe_parameters_before_writing(
    store: FalkorStore,
) -> None:
    store.put("Sentinel", "sentinel", {"id": "sentinel"})
    with pytest.raises(ValueError, match="exactly"):
        store.query("MERGE (n:Record {key:$key})", key="x", unused="y")
    with pytest.raises(ValueError, match="exactly"):
        store.query("MERGE (n:Record {key:$key})")
    with pytest.raises(ValueError, match="invalid parameter"):
        store.query("RETURN 1", **{"bad-name": "x"})
    with pytest.raises(ValueError):
        store.query("RETURN $number", number=float("nan"))
    with pytest.raises(ValueError, match="JSON scalars"):
        store.query("RETURN $mapping", mapping={"key": "value"})
    assert store.query("MATCH (n:Record) RETURN count(n)") == [[1]]
