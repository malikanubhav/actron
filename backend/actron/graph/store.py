"""FalkorDB access for one workspace graph: safe binding, typed upserts, UNWIND batches (spec A, A.C2, A4).

Labels and relationship names are validated against the ontology before they are put into Cypher
(they cannot be parameters). Values are always bound as parameters, or through the safe literal
binder when `binding="literal"`.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from falkordb import FalkorDB
from falkordb.edge import Edge
from falkordb.node import Node
from falkordb.path import Path as FPath

from actron.graph import ids
from actron.graph.ontology import SAFE_NAME, Ontology, OntologyViolation
from actron.logging import get_logger

log = get_logger(__name__)

Binding = Literal["params", "literal"]
_PARAM_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class GraphError(RuntimeError):
    """A FalkorDB query failed."""


class GraphTimeout(GraphError):
    """A FalkorDB query exceeded its timeout."""


class InvalidName(ValueError):
    """A label or relationship name is not allowed (not in the ontology, or unsafe)."""


@dataclass(frozen=True)
class LinkRow:
    from_id: str
    to_id: str
    props: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class LinkResult:
    created: int = 0
    missing: list[tuple[str, str]] = field(default_factory=list)

    def __int__(self) -> int:
        return self.created


def not_deleted(alias: str = "n", *, include_deleted: bool = False) -> str:
    """Cypher condition that hides tombstoned nodes (A4). Written with `coalesce` because indexes skip `<>`."""
    if not SAFE_NAME.match(alias):
        raise InvalidName(f"invalid alias {alias!r}")
    return "true" if include_deleted else f"coalesce({alias}.deleted, false) = false"


# Condition that hides `@v<n>` history copies of edited records (see actron.graph.versions).
NOT_VERSION = "NOT ({a}.id CONTAINS '@v')"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_graph_value(value: Any) -> Any:
    """Convert Python values to what FalkorDB stores: datetimes as ISO strings, dicts as JSON strings."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, list | tuple):
        return [to_graph_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"})


def _string_literal(value: str) -> str:
    """A Cypher string literal. FalkorDB does not decode `\\uXXXX`, so JSON's ASCII escaping would store the
    escape text itself (verified on v4.22.1). Only backslash, quote, CR, LF and tab are escaped; every other
    character, including emoji and control characters, goes in as-is. NUL cannot be sent in a literal.
    """
    if "\x00" in value:
        raise ValueError("a string containing NUL cannot be bound as a literal")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("a string with lone surrogates cannot be bound as a literal") from None
    return '"' + value.translate(_ESCAPES) + '"'


# Literal binder (A4): single pass, escaped scalars, lists and maps; substituted text is never re-scanned.
def _literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot be bound")
        return repr(value)
    if isinstance(value, str):
        return _string_literal(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if not isinstance(k, str) or not SAFE_NAME.match(k):
                raise ValueError(f"map key {k!r} is not a safe name")
            parts.append(f"`{k}`: {_literal(v)}")
        return "{" + ", ".join(parts) + "}"
    raise ValueError(f"cannot bind value of type {type(value).__name__}")


def bind_literal(template: str, params: Mapping[str, Any]) -> str:
    for name in params:
        if not SAFE_NAME.match(name):
            raise ValueError(f"invalid parameter name {name!r}")
    used = set(_PARAM_RE.findall(template))
    if used != set(params):
        raise ValueError(
            f"parameters do not match: template uses {sorted(used)}, given {sorted(params)}"
        )
    return _PARAM_RE.sub(lambda m: _literal(params[m.group(1)]), template)


def _convert(value: Any) -> Any:
    if isinstance(value, Node):
        props = dict(value.properties)
        labels = list(value.labels or [])
        props["_label"] = labels[0] if labels else None
        return props
    if isinstance(value, Edge):
        props = dict(value.properties)
        props["_type"] = value.relation
        props["_src"] = value.src_node
        props["_dst"] = value.dest_node
        return props
    if isinstance(value, FPath):
        return {
            "nodes": [_convert(n) for n in value.nodes()],
            "edges": [_convert(e) for e in value.edges()],
        }
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def _chunks(rows: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class GraphStore:
    def __init__(
        self,
        url: str,
        graph_name: str,
        ontology: Ontology,
        *,
        timeout_ms: int = 15000,
        workspace_id: str | None = None,
        binding: Binding = "params",
        source: str | None = None,
    ) -> None:
        if not SAFE_NAME.match(graph_name):
            raise InvalidName(f"invalid graph name {graph_name!r}")
        parsed = urlparse(url)
        self._db = FalkorDB(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            password=parsed.password,
            socket_timeout=120,
        )
        self.graph_name = graph_name
        self._graph = self._db.select_graph(graph_name)
        self.ontology = ontology
        self.timeout_ms = timeout_ms
        self.workspace_id = workspace_id or graph_name
        self.binding: Binding = binding
        self.default_source = source

    # Low level
    def query(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        read_only: bool = False,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        timeout = timeout_ms if timeout_ms is not None else self.timeout_ms
        bound_params: dict[str, Any] | None = dict(params) if params else None
        text = cypher
        if self.binding == "literal" and bound_params:
            text = bind_literal(cypher, bound_params)
            bound_params = None
        try:
            if read_only:
                try:
                    res = self._graph.ro_query(text, bound_params, timeout=timeout)
                except Exception as exc:
                    if "empty key" not in str(exc).lower():
                        raise
                    # A graph that was never written has no key yet; a plain read creates it empty.
                    self._graph.query("MATCH (n) RETURN count(n) AS c")
                    res = self._graph.ro_query(text, bound_params, timeout=timeout)
            else:
                res = self._graph.query(text, bound_params, timeout=timeout)
        except Exception as exc:  # redis.ResponseError and connection errors
            msg = str(exc)
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                raise GraphTimeout(msg) from exc
            raise GraphError(msg) from exc
        header = [h[1] if isinstance(h, list | tuple) else h for h in (res.header or [])]
        out: list[dict[str, Any]] = []
        for row in res.result_set or []:
            out.append({str(k): _convert(v) for k, v in zip(header, row, strict=False)})
        return out

    def create_unique_constraint(self, label: str, prop: str) -> None:
        self._label(label)
        try:
            self._graph.create_node_unique_constraint(label, prop)
        except Exception as exc:
            raise GraphError(str(exc)) from exc

    # Validation helpers
    def _label(self, label: str) -> str:
        if not SAFE_NAME.match(label) or label not in self.ontology.nodes:
            raise InvalidName(f"invalid node label {label!r}")
        return label

    def _rel(self, rel: str, from_label: str, to_label: str) -> str:
        if not SAFE_NAME.match(rel):
            raise InvalidName(f"invalid relationship name {rel!r}")
        self._label(from_label)
        self._label(to_label)
        if (rel, from_label, to_label) not in self.ontology.relationships:
            raise InvalidName(
                f"relationship ({from_label})-[:{rel}]->({to_label}) is not in the ontology"
            )
        return rel

    def _meta(self, source: str | None) -> dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "ontologyVersion": self.ontology.version,
            "refreshedAt": now_iso(),
            **({"source": source} if source else {}),
        }

    # Upserts
    def upsert_nodes(
        self,
        label: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        batch_size: int = 500,
        partial: bool = False,
        source: str | None = None,
    ) -> int:
        """MERGE on id, SET properties. `partial=True` skips the required-property check (updates)."""
        label = self._label(label)
        if not rows:
            return 0
        src = source or self.default_source or _source_for(label)
        prepared: list[dict[str, Any]] = []
        for row in rows:
            if not row.get("id"):
                raise OntologyViolation(f"{label}: row without id")
            props = {k: to_graph_value(v) for k, v in row.items() if v is not None}
            props.update(self._meta(src))
            self.ontology.validate_node(
                label, {**props, "ingestedAt": props["refreshedAt"]}, partial=partial
            )
            prepared.append({"id": props["id"], "ingestedAt": props["refreshedAt"], "props": props})
        cypher = (
            f"UNWIND $rows AS row MERGE (n:`{label}` {{id: row.id}}) "
            "ON CREATE SET n.ingestedAt = row.ingestedAt SET n += row.props"
        )
        return self._batched(cypher, prepared, batch_size)

    def update_nodes(
        self, label: str, rows: Sequence[Mapping[str, Any]], *, batch_size: int = 500
    ) -> int:
        """SET properties on existing nodes only (MATCH, never create)."""
        label = self._label(label)
        prepared = []
        for row in rows:
            props = {k: to_graph_value(v) for k, v in row.items()}
            self.ontology.validate_node(label, props, partial=True)
            node_id = props.pop("id")
            props["refreshedAt"] = now_iso()
            prepared.append({"id": node_id, "props": props})
        cypher = f"UNWIND $rows AS row MATCH (n:`{label}` {{id: row.id}}) SET n += row.props RETURN count(n) AS c"
        total = 0
        for batch in _chunks(prepared, batch_size):
            res = self.query(cypher, {"rows": list(batch)})
            total += int(res[0]["c"]) if res else 0
        return total

    def _batched(self, cypher: str, rows: Sequence[dict[str, Any]], batch_size: int) -> int:
        done = 0
        pending = list(rows)
        size = max(1, batch_size)
        while pending:
            batch = pending[:size]
            try:
                self.query(cypher, {"rows": batch})
            except GraphTimeout:
                if size <= 50:
                    raise
                size = max(50, size // 2)
                log.warning("graph batch timed out; halving", extra={"batch_size": size})
                continue
            done += len(batch)
            pending = pending[size:]
        return done

    def upsert_links(
        self,
        rel: str,
        from_label: str,
        to_label: str,
        rows: Sequence[LinkRow],
        *,
        batch_size: int = 500,
    ) -> LinkResult:
        rel = self._rel(rel, from_label, to_label)
        result = LinkResult()
        if not rows:
            return result
        created_at = now_iso()
        prepared = []
        for row in rows:
            props = {k: to_graph_value(v) for k, v in row.props.items() if v is not None}
            props.setdefault("createdAt", created_at)
            if "method" not in props or "confidence" not in props:
                raise OntologyViolation(f"{rel}: link props must include method and confidence")
            self.ontology.validate_rel(rel, from_label, to_label, props)
            prepared.append({"a": row.from_id, "b": row.to_id, "props": props})
        cypher = (
            f"UNWIND $rows AS row MATCH (a:`{from_label}` {{id: row.a}}) MATCH (b:`{to_label}` {{id: row.b}}) "
            f"MERGE (a)-[r:`{rel}`]->(b) SET r += row.props RETURN row.a AS a, row.b AS b"
        )
        for batch in _chunks(prepared, batch_size):
            res = self.query(cypher, {"rows": list(batch)})
            found = {(r["a"], r["b"]) for r in res}
            result.created += len(found)
            for item in batch:
                if (item["a"], item["b"]) not in found:
                    result.missing.append((item["a"], item["b"]))
        if result.missing:
            log.info(
                "links with missing endpoints", extra={"rel": rel, "missing": len(result.missing)}
            )
        return result

    def tombstone(self, label: str, node_ids: Sequence[str], at: datetime | None = None) -> int:
        label = self._label(label)
        when = to_graph_value(at or datetime.now(UTC))
        res = self.query(
            f"UNWIND $ids AS nid MATCH (n:`{label}` {{id: nid}}) "
            "SET n.deleted = true, n.deletedAt = $at, n.refreshedAt = $at RETURN count(n) AS c",
            {"ids": list(node_ids), "at": when},
        )
        return int(res[0]["c"]) if res else 0

    def tombstone_links(
        self,
        rel: str,
        from_label: str,
        to_label: str,
        pairs: Sequence[tuple[str, str]],
        at: datetime | None = None,
    ) -> int:
        rel = self._rel(rel, from_label, to_label)
        when = to_graph_value(at or datetime.now(UTC))
        res = self.query(
            f"UNWIND $pairs AS p MATCH (a:`{from_label}` {{id: p[0]}})-[r:`{rel}`]->(b:`{to_label}` {{id: p[1]}}) "
            "SET r.deleted = true, r.deletedAt = $at RETURN count(r) AS c",
            {"pairs": [list(p) for p in pairs], "at": when},
        )
        return int(res[0]["c"]) if res else 0

    def delete_links(
        self, rel: str, from_label: str, to_label: str, pairs: Sequence[tuple[str, str]]
    ) -> int:
        rel = self._rel(rel, from_label, to_label)
        res = self.query(
            f"UNWIND $pairs AS p MATCH (a:`{from_label}` {{id: p[0]}})-[r:`{rel}`]->(b:`{to_label}` {{id: p[1]}}) "
            "DELETE r RETURN count(*) AS c",
            {"pairs": [list(p) for p in pairs]},
        )
        return int(res[0]["c"]) if res else 0

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        try:
            label = ids.label_of(node_id)
        except ids.InvalidId:
            return None
        if label not in self.ontology.nodes:
            return None
        res = self.query(
            f"MATCH (n:`{label}` {{id: $id}}) RETURN n LIMIT 1", {"id": node_id}, read_only=True
        )
        if not res:
            return None
        node: dict[str, Any] = res[0]["n"]
        return node

    def list_nodes(
        self,
        label: str,
        *,
        include_deleted: bool = False,
        include_versions: bool = False,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Nodes of one label. Tombstoned nodes and `@v<n>` history copies are left out by default."""
        label = self._label(label)
        where = " AND ".join(
            [not_deleted("n", include_deleted=include_deleted)]
            + ([] if include_versions else [NOT_VERSION.format(a="n")])
        )
        res = self.query(
            f"MATCH (n:`{label}`) WHERE {where} RETURN n ORDER BY n.id LIMIT $limit",
            {"limit": int(limit)},
            read_only=True,
        )
        return [r["n"] for r in res]

    def count(self, label: str | None = None) -> int:
        if label is not None:
            self._label(label)
            res = self.query(f"MATCH (n:`{label}`) RETURN count(n) AS c", read_only=True)
        else:
            res = self.query("MATCH (n) RETURN count(n) AS c", read_only=True)
        return int(res[0]["c"]) if res else 0

    def has_unique_constraints(self) -> bool:
        try:
            rows = self.query("CALL db.constraints()", read_only=True)
        except GraphError:
            return False
        return any(r.get("type") == "UNIQUE" for r in rows)

    def drop(self, *, allow_constrained: bool = False) -> None:
        """Delete the graph (tests only).

        Refuses when the graph has unique constraints: on FalkorDB v4.22.1 that leaves an append-only file
        the server cannot load on the second restart (docs/falkordb.md, limitation 12).
        """
        if not allow_constrained and self.has_unique_constraints():
            raise GraphError(
                "refusing to delete a graph with unique constraints: it would corrupt append-only "
                "replay on FalkorDB v4.22.1 (docs/falkordb.md, limitation 12)"
            )
        try:
            self._graph.delete()
        except Exception as exc:
            if "empty key" not in str(exc).lower() and "invalid graph" not in str(exc).lower():
                raise

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._db.close()


def _source_for(label: str) -> str:
    if label.startswith("Slack"):
        return "slack"
    if label.startswith("Linear"):
        return "linear"
    if label.startswith("Github"):
        return "github"
    if label.startswith("Git"):
        return "git"
    if label.startswith("Code"):
        return "code"
    return "actron"


_STORES: dict[str, GraphStore] = {}


def store_for(ws: str) -> GraphStore:
    """Cached store for a workspace graph (one graph per workspace)."""
    from actron.config import get_settings
    from actron.graph.ontology import default_ontology

    settings = get_settings()
    name = ids.graph_name(settings.FALKORDB_GRAPH_PREFIX, ws)
    if name not in _STORES:
        _STORES[name] = GraphStore(
            settings.FALKORDB_URL,
            name,
            default_ontology(),
            workspace_id=ws,
            binding=settings.FALKORDB_BINDING,
        )
    return _STORES[name]
