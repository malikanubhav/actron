"""Loads ontology/*.json, expands node groups, validates upserts, creates indexes (spec A, A.C1, A3).

The files are the source of truth: nothing creates or renames types at runtime.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from actron.graph.store import GraphStore

FILE_ORDER = ("slack", "linear", "github", "code", "core")
FABRIC_FILES = frozenset({"slack", "linear"})
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OntologyError(Exception):
    """The ontology files are inconsistent (names the file, the item and the reason)."""


class UnknownNodeType(OntologyError):
    pass


class UnknownRelationship(OntologyError):
    pass


class OntologyViolation(ValueError):
    """An upsert does not match the ontology (wrong type, missing or unknown property)."""


@dataclass(frozen=True)
class PropertyDef:
    name: str
    type: str
    required: bool
    indexed: bool
    unique: bool
    full_text: bool
    allowed: tuple[str, ...] | None = None


@dataclass(frozen=True)
class NodeDef:
    name: str
    primary_key: str
    display_name: str
    properties: dict[str, PropertyDef]
    source_file: str


@dataclass(frozen=True)
class RelDef:
    name: str
    from_node: str
    to_node: str
    cardinality: str
    temporal: bool
    source_file: str
    allowed_properties: frozenset[str] = frozenset()


@dataclass
class IndexReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped_relationships: list[tuple[str, str, str, str]] = field(default_factory=list)


_ENUM_ITEM = re.compile(r"^[a-z][a-z0-9_]*$|^[A-Z][A-Z0-9_]+$")


def _parse_enum(description: str) -> tuple[str, ...] | None:
    """Extract allowed values from descriptions like "a, b or c" or "one of a, b, c"."""
    text = re.sub(r"\s*\(.*?\)\s*", " ", description).strip().rstrip(".")
    text = re.sub(r"^(?i:one of)\s+", "", text)
    if " or " not in text and not description.lower().startswith("one of"):
        return None
    parts = re.split(r",\s*|\s+or\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2 or not all(_ENUM_ITEM.match(p) for p in parts):
        return None
    return tuple(parts)


def _parse_rel_properties(description: str) -> frozenset[str]:
    m = re.search(r"Properties:\s*(.+)$", description)
    names: set[str] = set()
    if m:
        body = re.sub(r"\(.*?\)", "", m.group(1))
        for chunk in body.split(","):
            word = chunk.strip().split(" ")[0].rstrip(".;")
            if SAFE_NAME.match(word):
                names.add(word)
    elif "Properties include" in description:
        # e.g. EXTRACTED_FROM: "Properties include the exact quote and span."
        names.update({"quote", "span", "quoteSpan"})
    return frozenset(names)


def _prop(raw: Mapping[str, Any]) -> PropertyDef:
    desc = str(raw.get("description", ""))
    ptype = str(raw.get("type", "string"))
    return PropertyDef(
        name=str(raw["name"]),
        type=ptype,
        required=bool(raw.get("required", False)),
        indexed=bool(raw.get("indexed", False)),
        unique=bool(raw.get("unique", False)),
        full_text="full-text indexed" in desc,
        allowed=_parse_enum(desc) if ptype == "string" else None,
    )


class Ontology:
    def __init__(
        self,
        version: str,
        nodes: dict[str, NodeDef],
        relationships: dict[tuple[str, str, str], RelDef],
        common_node_properties: dict[str, PropertyDef],
        common_relationship_properties: dict[str, PropertyDef],
        groups: dict[str, list[str]],
        skipped: list[tuple[str, str, str, str]],
    ) -> None:
        self.version = version
        self.nodes = nodes
        self.relationships = relationships
        self.common_node_properties = common_node_properties
        self.common_relationship_properties = common_relationship_properties
        self.groups = groups
        self.skipped_relationships = skipped
        self._rel_names = {name for name, _, _ in relationships}

    def node(self, name: str) -> NodeDef:
        try:
            return self.nodes[name]
        except KeyError:
            raise UnknownNodeType(f"unknown node type {name!r}") from None

    def rel(self, name: str, from_node: str, to_node: str) -> RelDef:
        try:
            return self.relationships[(name, from_node, to_node)]
        except KeyError:
            raise UnknownRelationship(
                f"unknown relationship ({from_node})-[:{name}]->({to_node})"
            ) from None

    def has_rel_name(self, name: str) -> bool:
        return name in self._rel_names

    def full_text_fields(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for node in self.nodes.values():
            fields = [
                p.name for p in node.properties.values() if p.full_text and SAFE_NAME.match(p.name)
            ]
            if fields:
                out[node.name] = fields
        return out

    def search_fields(self) -> dict[str, list[str]]:
        """Fields in each label's full-text index: the ontology's full-text fields plus name-like fields.

        Names and titles are added so a search for `activate` or a ticket title finds the node; this is an
        index choice, not an ontology change (recorded in BUILD-LOG.md).
        """
        extra = (
            "name",
            "qualifiedName",
            "title",
            "path",
            "identifier",
            "description",
            "body",
            "text",
        )
        searchable_labels = {
            "LinearIssue",
            "LinearComment",
            "CodeFile",
            "CodeDocument",
            "GithubPullRequest",
            "GithubIssue",
            "Feature",
            "Procedure",
            "CodeComponent",
            "Person",
            "SlackChannel",
            "SlackUser",
            "LinearUser",
            "GithubUser",
            "GitAuthor",
        }
        out = self.full_text_fields()
        for node in self.nodes.values():
            if node.name not in out and node.name not in searchable_labels:
                continue
            fields = list(out.get(node.name, []))
            for name in extra:
                prop = node.properties.get(name)
                if prop and prop.type == "string" and name not in fields:
                    fields.append(name)
            if fields:
                out[node.name] = fields
        return out

    def _check_value(self, where: str, prop: PropertyDef, value: Any) -> None:
        if value is None:
            return
        t = prop.type
        ok: bool
        if t == "string":
            ok = isinstance(value, str)
        elif t == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif t in ("float", "number"):
            ok = isinstance(value, int | float) and not isinstance(value, bool)
        elif t == "boolean":
            ok = isinstance(value, bool)
        elif t == "date":
            ok = isinstance(value, date) and not isinstance(value, datetime)
            if isinstance(value, str):
                try:
                    date.fromisoformat(value[:10])
                    ok = len(value) >= 10
                except ValueError:
                    ok = False
        elif t == "datetime":
            ok = isinstance(value, datetime)
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                    ok = True
                except ValueError:
                    ok = False
        elif t == "array":
            ok = isinstance(value, list) and all(
                v is None or isinstance(v, str | int | float | bool) for v in value
            )
        elif t == "object":
            ok = isinstance(value, str | dict)
        else:
            ok = True
        if not ok:
            raise OntologyViolation(
                f"{where}.{prop.name}: expected {t}, got {type(value).__name__}"
            )
        if prop.allowed and isinstance(value, str) and value not in prop.allowed:
            raise OntologyViolation(
                f"{where}.{prop.name}: {value!r} is not one of {', '.join(prop.allowed)}"
            )

    def validate_node(self, name: str, props: Mapping[str, Any], *, partial: bool = False) -> None:
        node = self.node(name)
        for key, value in props.items():
            prop = node.properties.get(key) or self.common_node_properties.get(key)
            if prop is None:
                raise OntologyViolation(f"{name}: unknown property {key!r}")
            self._check_value(name, prop, value)
        if partial:
            return
        for prop in [*node.properties.values(), *self.common_node_properties.values()]:
            if prop.required and props.get(prop.name) is None and SAFE_NAME.match(prop.name):
                raise OntologyViolation(f"{name}: missing required property {prop.name!r}")

    def validate_rel(
        self, name: str, from_node: str, to_node: str, props: Mapping[str, Any]
    ) -> None:
        rel = self.rel(name, from_node, to_node)
        for key, value in props.items():
            if key in self.common_relationship_properties:
                self._check_value(name, self.common_relationship_properties[key], value)
            elif key not in rel.allowed_properties:
                raise OntologyViolation(f"{name}: unknown relationship property {key!r}")


def _read(directory: Path, stem: str) -> dict[str, Any]:
    path = directory / f"{stem}.json"
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OntologyError(f"{path.name}: file missing") from None
    except json.JSONDecodeError as exc:
        raise OntologyError(f"{path.name}: invalid JSON ({exc})") from None
    return data


def load_ontology(directory: Path) -> Ontology:
    files = {stem: _read(directory, stem) for stem in FILE_ORDER}
    nodes: dict[str, NodeDef] = {}
    for stem, data in files.items():
        for raw in data.get("nodes", []):
            name = str(raw["name"])
            if name in nodes:
                raise OntologyError(
                    f"{stem}.json: node {name!r}: duplicate node name (already in {nodes[name].source_file})"
                )
            props = {str(p["name"]): _prop(p) for p in raw.get("properties", [])}
            nodes[name] = NodeDef(
                name=name,
                primary_key=str(raw.get("primary_key", "id")),
                display_name=str(raw.get("display_name", "name")),
                properties=props,
                source_file=f"{stem}.json",
            )

    core = files["core"]
    groups: dict[str, list[str]] = {k: list(v) for k, v in core.get("node_groups", {}).items()}
    for group, members in groups.items():
        for member in members:
            if member not in nodes:
                raise OntologyError(f"core.json: group {group!r}: member {member!r} is not a node")

    common_node = {str(p["name"]): _prop(p) for p in core.get("common_node_properties", [])}
    common_rel = {str(p["name"]): _prop(p) for p in core.get("common_relationship_properties", [])}

    rels: dict[tuple[str, str, str], RelDef] = {}
    skipped: list[tuple[str, str, str, str]] = []
    for stem, data in files.items():
        for raw in data.get("relationships", []):
            name = str(raw["name"])
            frm, to = str(raw["from_node"]), str(raw["to_node"])
            from_members = groups.get(frm, [frm])
            to_members = groups.get(to, [to])
            missing = [n for n in (*from_members, *to_members) if n not in nodes]
            if missing:
                if stem in FABRIC_FILES:
                    skipped.append((f"{stem}.json", name, frm, to))
                    continue
                raise OntologyError(
                    f"{stem}.json: relationship {name!r} ({frm} -> {to}): undefined endpoint {missing[0]!r}"
                )
            allowed = _parse_rel_properties(str(raw.get("description", "")))
            for f_member in from_members:
                for t_member in to_members:
                    key = (name, f_member, t_member)
                    if key in rels:
                        raise OntologyError(
                            f"{stem}.json: relationship {name!r} ({f_member} -> {t_member}): duplicate"
                        )
                    rels[key] = RelDef(
                        name=name,
                        from_node=f_member,
                        to_node=t_member,
                        cardinality=str(raw.get("cardinality", "")),
                        temporal=bool(raw.get("temporal", False)),
                        source_file=f"{stem}.json",
                        allowed_properties=allowed,
                    )

    version = "|".join(f"{stem}:{files[stem].get('version', '?')}" for stem in FILE_ORDER)
    return Ontology(version, nodes, rels, common_node, common_rel, groups, skipped)


def _index_rows(graph: GraphStore) -> list[dict[str, Any]]:
    try:
        return graph.query("CALL db.indexes()", read_only=True)
    except Exception:
        return []


def _existing_unique(graph: GraphStore) -> set[str]:
    try:
        rows = graph.query("CALL db.constraints()", read_only=True)
    except Exception:
        return set()
    return {
        str(r["label"])
        for r in rows
        if r.get("type") == "UNIQUE"
        and r.get("entitytype") == "NODE"
        and r.get("properties") == ["id"]
    }


def ensure_indexes(
    graph: GraphStore, ontology: Ontology, *, constraints: bool | None = None
) -> IndexReport:
    """Idempotently create range indexes (id + indexed props), unique id constraints and full-text indexes.

    `constraints=None` follows `Settings.unique_constraints_enabled`: on, except when ACTRON_ENV=test.
    FalkorDB v4.22.1 cannot replay its append-only file after a graph that had a unique constraint was
    deleted (see docs/falkordb.md, limitation 12), so test graphs, which are dropped, get none.
    Constraints that exist are detected first, so a second run writes nothing to the append-only file.
    """
    if constraints is None:
        from actron.config import get_settings

        constraints = get_settings().unique_constraints_enabled
    use_constraints = constraints
    report = IndexReport(skipped_relationships=list(ontology.skipped_relationships))
    existing_unique = _existing_unique(graph) if use_constraints else set()
    existing_range: set[tuple[str, str]] = set()
    existing_ft: set[tuple[str, str]] = set()
    for row in _index_rows(graph):
        label = str(row.get("label"))
        props = row.get("properties") or []
        types = row.get("types") or {}
        for p in props:
            kinds = types.get(p, []) if isinstance(types, dict) else []
            if "FULLTEXT" in kinds:
                existing_ft.add((label, str(p)))
            if "RANGE" in kinds or not kinds:
                existing_range.add((label, str(p)))

    for node in ontology.nodes.values():
        label = node.name
        if not SAFE_NAME.match(label):
            continue
        wanted = ["id"] + [
            p.name
            for p in node.properties.values()
            if p.indexed and p.name != "id" and not p.full_text and SAFE_NAME.match(p.name)
        ]
        for prop in wanted:
            tag = f"range:{label}.{prop}"
            if (label, prop) in existing_range:
                report.existing.append(tag)
                continue
            try:
                graph.query(f"CREATE INDEX FOR (n:`{label}`) ON (n.`{prop}`)")
                report.created.append(tag)
            except Exception as exc:
                if "already" in str(exc).lower():
                    report.existing.append(tag)
                else:
                    report.failed.append(f"{tag}: {exc}")
        if not use_constraints:
            continue
        tag = f"unique:{label}.id"
        if label in existing_unique:
            report.existing.append(tag)
            continue
        try:
            graph.create_unique_constraint(label, "id")
            report.created.append(tag)
        except Exception as exc:
            msg = str(exc).lower()
            if "already" in msg or "exists" in msg:
                report.existing.append(tag)
            else:
                report.failed.append(f"{tag}: {exc}")

    for label, fields in ontology.search_fields().items():
        missing = [f for f in fields if (label, f) not in existing_ft]
        tag = f"fulltext:{label}({','.join(fields)})"
        if not missing:
            report.existing.append(tag)
            continue
        args = ", ".join(f"'{f}'" for f in missing)
        try:
            graph.query(f"CALL db.idx.fulltext.createNodeIndex('{label}', {args})")
            report.created.append(tag)
        except Exception as exc:
            if "already" in str(exc).lower():
                report.existing.append(tag)
            else:
                report.failed.append(f"{tag}: {exc}")
    return report


def default_ontology() -> Ontology:
    from actron.config import get_settings

    return _cached(str(get_settings().ACTRON_ONTOLOGY_DIR))


_CACHE: dict[str, Ontology] = {}


def _cached(directory: str) -> Ontology:
    if directory not in _CACHE:
        _CACHE[directory] = load_ontology(Path(directory))
    return _CACHE[directory]


def relationship_endpoints(ontology: Ontology, name: str) -> Sequence[tuple[str, str]]:
    return [(f, t) for (n, f, t) in ontology.relationships if n == name]
