"""Updates when new commits land: graph state, rename detection, re-pointing callers (spec A, A6.10).

The graph keeps one node per current function, class and file. Renamed or moved symbols get `RENAMED_TO`
(`CLASS_RENAMED_TO`, `FILE_RENAMED_TO`) from the tombstoned old node to the new one. Bodies are compared with
the symbol's own name masked and indentation removed, so a pure rename or a move into a class still counts as
the same body (similarity 1.0); otherwise token Jaccard similarity of at least 0.8 is required.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from actron.connectors.code.model import Symbol, sha256_text
from actron.graph.store import GraphStore, LinkRow

RENAME_THRESHOLD = 0.8
_TOKEN = re.compile(r"[A-Za-z_$][\w$]*|\d+|\S")
PAGE = 5000


def normalized_body(sym: Symbol) -> str:
    body = re.sub(rf"(?<![\w$]){re.escape(sym.name)}(?![\w$])", "\x00", sym.body) if sym.name else sym.body
    return "\n".join(line.strip() for line in body.split("\n") if line.strip())


def normalized_hash(sym: Symbol) -> str:
    return sha256_text(normalized_body(sym))


def tokens(sym: Symbol) -> set[str]:
    return set(_TOKEN.findall(normalized_body(sym)))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@dataclass
class RenameCandidate:
    id: str
    sym: Symbol


@dataclass
class RenameMatch:
    old_id: str
    new_id: str
    kind: str  # function or class
    similarity: float
    commit_sha: str


def match_renames(deleted: Sequence[RenameCandidate], added: Sequence[RenameCandidate], commit_sha: str,
                  threshold: float = RENAME_THRESHOLD) -> list[RenameMatch]:
    """Best match per deleted symbol among symbols added in the same commit (same kind); each added symbol is
    used at most once, highest similarity first."""
    scored: list[tuple[float, int, int]] = []
    add_hash = [normalized_hash(a.sym) for a in added]
    add_tok = [tokens(a.sym) for a in added]
    for i, d in enumerate(deleted):
        d_hash = normalized_hash(d.sym)
        d_tok = tokens(d.sym)
        for j, a in enumerate(added):
            if a.sym.kind != d.sym.kind:
                continue
            sim = 1.0 if add_hash[j] == d_hash else jaccard(d_tok, add_tok[j])
            if sim >= threshold:
                scored.append((sim, i, j))
    scored.sort(key=lambda t: -t[0])
    used_d: set[int] = set()
    used_a: set[int] = set()
    out: list[RenameMatch] = []
    for sim, i, j in scored:
        if i in used_d or j in used_a:
            continue
        used_d.add(i)
        used_a.add(j)
        out.append(RenameMatch(deleted[i].id, added[j].id, deleted[i].sym.kind, round(sim, 4), commit_sha))
    return out


def scan(store: GraphStore, label: str, prefix: str, fields: Iterable[str]) -> Iterator[dict[str, Any]]:
    """All nodes of `label` whose id starts with `prefix`, in pages (the server caps result sets)."""
    store._label(label)  # validates the label before it is put into Cypher
    cols = ", ".join(f"n.{f} AS {f}" for f in fields if re.match(r"^[A-Za-z_]\w*$", f))
    skip = 0
    while True:
        rows = store.query(
            f"MATCH (n:`{label}`) WHERE n.id STARTS WITH $p RETURN n.id AS id, "
            f"coalesce(n.deleted, false) AS deleted{', ' + cols if cols else ''} ORDER BY n.id SKIP $s LIMIT $l",
            {"p": prefix, "s": skip, "l": PAGE}, read_only=True, timeout_ms=60000,
        )
        yield from rows
        if len(rows) < PAGE:
            return
        skip += PAGE


@dataclass
class GraphState:
    """What the graph already holds for one repository."""

    files: dict[str, dict[str, Any]] = field(default_factory=dict)  # file id -> row
    functions: dict[str, dict[str, Any]] = field(default_factory=dict)
    classes: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunks: dict[str, dict[str, Any]] = field(default_factory=dict)
    docs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.files


def load_state(store: GraphStore, repo: str) -> GraphState:
    r = repo.lower()
    st = GraphState()
    st.files = {x["id"]: x for x in scan(store, "CodeFile", f"code:file:{r}:", ["path", "contentHash"])}
    sym_fields = ["contentHash", "startLine", "endLine"]
    st.functions = {x["id"]: x for x in scan(store, "CodeFunction", f"code:fn:{r}:", sym_fields)}
    st.classes = {x["id"]: x for x in scan(store, "CodeClass", f"code:class:{r}:", sym_fields)}
    st.chunks = {x["id"]: x for x in scan(store, "CodeChunk", f"code:chunk:{r}:", [])}
    st.docs = {x["id"]: x for x in scan(store, "CodeDocument", f"code:doc:{r}:", [])}
    return st


def replace_out_links(store: GraphStore, rel: str, from_label: str, to_label: str, from_ids: Sequence[str],
                      desired: Sequence[LinkRow]) -> tuple[int, int]:
    """Make the outgoing `rel` links of `from_ids` equal `desired`: delete the others, upsert these."""
    store._rel(rel, from_label, to_label)
    existing: set[tuple[str, str]] = set()
    ids_list = list(dict.fromkeys(from_ids))
    for i in range(0, len(ids_list), 500):
        rows = store.query(
            f"UNWIND $ids AS x MATCH (a:`{from_label}` {{id: x}}) WITH * MATCH (a)-[:`{rel}`]->(b:`{to_label}`) "
            "RETURN a.id AS a, b.id AS b",
            {"ids": ids_list[i : i + 500]}, read_only=True, timeout_ms=60000,
        )
        existing.update((r["a"], r["b"]) for r in rows)
    want = {(row.from_id, row.to_id) for row in desired}
    stale = sorted(existing - want)
    removed = store.delete_links(rel, from_label, to_label, stale) if stale else 0
    created = store.upsert_links(rel, from_label, to_label, list(desired)).created if desired else 0
    return created, removed


def repoint_callers(store: GraphStore, renames: Sequence[RenameMatch]) -> int:
    """Move CALLS and TESTS links from callers that still exist to the new node of a renamed function."""
    moved = 0
    for m in renames:
        if m.kind != "function":
            continue
        for rel in ("CALLS", "TESTS"):
            rows = store.query(
                f"MATCH (c:CodeFunction)-[r:`{rel}`]->(o:CodeFunction {{id: $old}}) "
                "WHERE coalesce(c.deleted, false) = false RETURN c.id AS c, properties(r) AS p",
                {"old": m.old_id}, read_only=True,
            )
            if not rows:
                continue
            links = [LinkRow(r["c"], m.new_id, {k: v for k, v in (r["p"] or {}).items() if k != "createdAt"})
                     for r in rows if r["c"] != m.new_id]
            if links:
                store.upsert_links(rel, "CodeFunction", "CodeFunction", links)
                store.delete_links(rel, "CodeFunction", "CodeFunction", [(r["c"], m.old_id) for r in rows])
                moved += len(links)
    return moved


def write_renames(store: GraphStore, renames: Sequence[RenameMatch]) -> int:
    fn_rows = [LinkRow(m.old_id, m.new_id, {"method": "structural", "confidence": m.similarity,
                                             "commitSha": m.commit_sha, "similarity": m.similarity})
               for m in renames if m.kind == "function"]
    cls_rows = [LinkRow(m.old_id, m.new_id, {"method": "structural", "confidence": m.similarity,
                                              "commitSha": m.commit_sha, "similarity": m.similarity})
                for m in renames if m.kind == "class"]
    n = 0
    if fn_rows:
        n += store.upsert_links("RENAMED_TO", "CodeFunction", "CodeFunction", fn_rows).created
    if cls_rows:
        n += store.upsert_links("CLASS_RENAMED_TO", "CodeClass", "CodeClass", cls_rows).created
    return n
