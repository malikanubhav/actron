"""FalkorDB persistence and fail-closed per-request serialization."""

import json
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import redis

from .contracts import Payload, Unavailable, canonical


class FalkorStore:
    """Persist JSON envelopes and typed provenance relationships in one graph.

    Locks deliberately have no TTL: a killed holder requires operator recovery;
    another worker must never proceed while an old external write may be alive.
    """

    def __init__(
        self, url: str | None = None, graph: str = "actron", lock_wait: float = 5.0
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", graph):
            raise ValueError("invalid graph name")
        self.graph = graph
        resolved_url = str(url or os.getenv("ACTRON_REDIS_URL", "redis://localhost:6379"))
        self.redis: redis.Redis = redis.Redis.from_url(
            resolved_url, decode_responses=True, socket_timeout=10
        )
        self.lock_wait = lock_wait

    def query(self, query: str, **parameters: Any) -> list[Any]:
        """Bind data literals into a trusted query template in one substitution pass.

        FalkorDB 4.12 mutates a ``CYPHER`` parameter-prefix buffer before writing
        it to AOF. Literal queries avoid that replay corruption. Substitution is
        deliberately one pass: parameter-looking text inside a bound value must
        never become a second placeholder or executable query text.
        """
        for name in parameters:
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
                raise ValueError("invalid parameter")
        placeholder = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
        expected = {match.group(1) for match in placeholder.finditer(query)}
        if expected != set(parameters):
            raise ValueError("query template parameters must match supplied values exactly")

        def literal(value: Any) -> str:
            if value is not None and not isinstance(value, (str, bool, int, float, list)):
                raise ValueError("query parameters support JSON scalars and lists only")
            if isinstance(value, list):
                return "[" + ",".join(literal(item) for item in value) + "]"
            return json.dumps(value, ensure_ascii=True, allow_nan=False)

        encoded = {name: literal(value) for name, value in parameters.items()}
        statement = placeholder.sub(lambda match: encoded[match.group(1)], query)
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self.graph, statement)
            return list(result[1]) if len(result) > 2 else []
        except (redis.RedisError, OSError) as exc:
            raise Unavailable(f"FalkorDB unavailable: {exc}") from exc

    def get(self, kind: str, key: str) -> Payload | None:
        rows = self.query(
            "MATCH (n:Record {kind:$kind,key:$key}) RETURN n.payload", kind=kind, key=key
        )
        return json.loads(rows[0][0]) if rows else None

    def put(self, kind: str, key: str, value: Payload) -> None:
        self.query(
            "MERGE (n:Record {kind:$kind,key:$key}) SET n.payload=$payload",
            kind=kind,
            key=key,
            payload=canonical(value),
        )

    def list(self, kind: str) -> list[Payload]:
        rows = self.query(
            "MATCH (n:Record {kind:$kind}) RETURN n.payload ORDER BY n.key", kind=kind
        )
        return [json.loads(row[0]) for row in rows]

    def link(
        self,
        left_kind: str,
        left: str,
        relation: str,
        right_kind: str,
        right: str,
        provenance: Payload,
    ) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", relation):
            raise ValueError("invalid relationship name")
        self.query(
            "MATCH (a:Record {kind:$lk,key:$left}), (b:Record {kind:$rk,key:$right}) "
            f"MERGE (a)-[r:{relation}]->(b) SET r.provenance=$provenance",
            lk=left_kind,
            left=left,
            rk=right_kind,
            right=right,
            provenance=canonical(provenance),
        )

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        lock_key = f"actron:{self.graph}:lock:{key}"
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self.lock_wait
        try:
            while not self.redis.set(lock_key, token, nx=True):
                if time.monotonic() >= deadline:
                    raise Unavailable(f"request lock busy: {key}; inspect holder before recovery")
                time.sleep(0.025)
        except (redis.RedisError, OSError) as exc:
            raise Unavailable(f"request lock unavailable: {exc}") from exc
        try:
            yield
        finally:
            try:
                released = self.redis.eval(
                    "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    token,
                )
                if released != 1:
                    raise Unavailable("request lock ownership lost")
            except (redis.RedisError, OSError) as exc:
                raise Unavailable(f"request lock release unavailable: {exc}") from exc
