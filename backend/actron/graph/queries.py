"""Named graph queries (spec B, B3). Each returns typed rows; `shared_query` composes them into B.C3.

Rules followed everywhere (docs/falkordb.md):
- every lookup by id includes the node label, derived from the id with `ids.parse_id`;
- tombstoned nodes are filtered with `coalesce(n.deleted, false) = false` (indexes do not serve `<>`);
- callers and impact use a backwards variable-length match (`algo.BFS` follows outgoing links only);
- undirected shortest paths use `algo.SPpaths` (Cypher `shortestPath` is directed-only and WITH/RETURN-only);
- every query has an explicit LIMIT and runs read-only with a timeout (2 s for tools, 10 s for the shared query).
"""

from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from actron.flow.findings import (
    MAX_CALLERS,
    MAX_DECISIONS,
    MAX_GRAPH_NODES,
    MAX_OWNERS,
    MAX_RELATED,
    MAX_SEEDS,
    CallerItem,
    Conflict,
    CriticalityItem,
    DecisionItem,
    Findings,
    FindingsGraph,
    GraphEdge,
    GraphNodeBrief,
    Impact,
    NodeBrief,
    OwnerItem,
    ProcedureItem,
    RelatedWorkItem,
    SeedItem,
    SourceRef,
    TestItem,
)
from actron.graph import ids
from actron.logging import get_logger

log = get_logger(__name__)

TOOL_TIMEOUT_MS = 2000
SHARED_TIMEOUT_MS = 10000
MAX_ROWS = 200
# Request graphs: above this many nodes the aggregated view clusters everything except the top findings.
AGGREGATE_ABOVE = 40
AGGREGATE_KEEP_TOP = 12
PATH_ROW_CAP = 5000
RENAME_HOPS = 5

CONSTRAINABLE = ("CodeFunction", "CodeClass", "CodeFile", "CodeComponent", "Feature")
RENAME_REL = {"CodeFunction": "RENAMED_TO", "CodeClass": "CLASS_RENAMED_TO", "CodeFile": "FILE_RENAMED_TO"}
MENTION_SOURCES = (
    "SlackMessage", "LinearIssue", "LinearComment", "GithubIssue", "GithubIssueComment",
    "GithubPullRequest", "GithubReview", "GithubReviewComment", "GitCommit", "CodeDocument",
)
AUTHOR_RELS = "POSTED_BY|REVIEW_COMMENT_BY|COMMENT_BY|ISSUE_CREATED_BY|OPENED_BY|AUTHORED_BY|ISSUE_OPENED_BY"
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has", "have", "how",
    "i", "in", "into", "is", "it", "its", "make", "me", "my", "of", "on", "or", "our", "please", "should", "so",
    "that", "the", "their", "them", "then", "there", "this", "to", "up", "us", "we", "what", "when", "where",
    "which", "why", "will", "with", "would", "you", "your", "add", "change", "new", "every", "all", "any",
    "not", "no",
})

ND = "coalesce({a}.deleted, false) = false"


class QueryError(ValueError):
    """Invalid input to a named query (bad id, unsupported label, out-of-range limit)."""


class GraphReader(Protocol):
    """The part of `GraphStore` the queries need (tests may pass a fake)."""

    def query(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        read_only: bool = False,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]: ...


class Row(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# ----------------------------------------------------------------------------------------- helpers


def nd(alias: str) -> str:
    return ND.format(a=alias)


def label_for(node_id: str) -> str:
    try:
        return ids.label_of(node_id)
    except ids.InvalidId as exc:
        raise QueryError(str(exc)) from None


def group_by_label(node_ids: Iterable[str], allowed: Iterable[str] | None = None) -> dict[str, list[str]]:
    allow = set(allowed) if allowed is not None else None
    out: dict[str, list[str]] = defaultdict(list)
    for nid in node_ids:
        try:
            label = ids.label_of(nid)
        except ids.InvalidId:
            continue
        if allow is not None and label not in allow:
            continue
        if nid not in out[label]:
            out[label].append(nid)
    return dict(out)


def _q(
    store: GraphReader, cypher: str, params: Mapping[str, Any] | None = None, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[dict[str, Any]]:
    return store.query(cypher, params or {}, read_only=True, timeout_ms=timeout_ms)


def _clamp(value: int, low: int, high: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise QueryError(f"{name} must be an integer")
    return max(low, min(high, value))


def display_label(node: Mapping[str, Any]) -> str:
    """A short human label for any node."""
    for key in ("qualifiedName", "title", "statement", "displayName", "identifier", "name", "subject",
                "login", "path", "realName", "email"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("text", "body"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return _shorten(value, 80)
    return str(node.get("id", ""))


def _shorten(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def node_time(node: Mapping[str, Any]) -> str | None:
    for key in ("mergedAt", "postedAt", "updatedAt", "createdAt", "authoredAt", "decidedAt", "submittedAt"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def node_url(node: Mapping[str, Any]) -> str | None:
    for key in ("url", "permalink", "sourceUrl"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def group_of(label: str) -> Literal["code", "github", "slack", "linear", "core"]:
    if label.startswith("Slack"):
        return "slack"
    if label.startswith("Linear"):
        return "linear"
    if label.startswith("Github"):
        return "github"
    if label.startswith(("Code", "Git")):
        return "code"
    return "core"


def _stem(word: str) -> str:
    """Strip one common English ending so `shown` also finds `showResult` and `results` finds `result`."""
    for suffix in ("ing", "ed", "es", "s", "n"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def fulltext_query(text: str, *, max_terms: int = 12) -> str:
    """Turn free text into a RediSearch OR query of prefix terms (`term*|term*`).

    Punctuation is dropped (a `-` would mean NOT); camelCase names are split so `evaluateOnSave` also
    searches `evaluate`; short words and stop words are skipped.
    """
    words: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_]+", text):
        parts = [raw, *re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", raw)]
        for part in parts:
            w = part.lower().strip("_")
            if len(w) < 3 or w in STOPWORDS:
                continue
            for form in (w, _stem(w)):
                if form not in words and len(form) >= 3:
                    words.append(form)
    words = words[:max_terms]
    return "|".join(f"{w}*" if len(w) >= 4 else w for w in words)


# ----------------------------------------------------------------------------------------- seeds


class SeedRow(Row):
    id: str
    type: str
    label: str
    snippet: str
    score: float
    rawScore: float
    nameMatch: float = 0.0
    isTest: bool = False
    explicit: bool = False


_IDENT_RE = re.compile(r"\b(?:[a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z]+_[A-Za-z0-9_]+|[A-Z]+[a-z]+[A-Z][A-Za-z0-9]*)\b")


def explicit_identifiers(text: str) -> list[str]:
    """Code-shaped names written in the request (`docFromTextNotation`, `read_log`, `NReplSession`)."""
    out: list[str] = []
    for m in _IDENT_RE.findall(text):
        if m not in out:
            out.append(m)
    for m in re.findall(r"`([A-Za-z_][\w.]*)`", text):
        name = m.rsplit(".", 1)[-1]
        if name not in out:
            out.append(name)
    return out[:10]


def seeds_by_name(store: GraphReader, text: str, *, timeout_ms: int = TOOL_TIMEOUT_MS) -> list[SeedRow]:
    """Functions and classes whose name equals an identifier written in the request (score 1.0)."""
    names = explicit_identifiers(text)
    if not names:
        return []
    rows: list[SeedRow] = []
    for label in ("CodeFunction", "CodeClass"):
        res = _q(
            store,
            f"MATCH (n:{label}) WHERE n.name IN $names AND {nd('n')} AND NOT (n.id CONTAINS '@v') "
            "RETURN n LIMIT 20",
            {"names": names},
            timeout_ms,
        )
        for r in res:
            node = r["n"]
            rows.append(SeedRow(id=str(node["id"]), type=label, label=display_label(node),
                                snippet=_shorten(str(node.get("signature") or node.get("body") or ""), 160),
                                score=1.0, rawScore=0.0, nameMatch=1.0, isTest=bool(node.get("isTest")),
                                explicit=True))
    return rows


def name_words(name: str) -> list[str]:
    """Lowercase words of an identifier or title: `evaluateOnSave` -> evaluate, on, save."""
    out: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9]+", name):
        for part in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", raw) or [raw]:
            w = part.lower()
            if w not in STOPWORDS and len(w) > 1 and w not in out:
                out.append(w)
    return out


def name_overlap(name: str, terms: Sequence[str]) -> float:
    """Share of a name's words that the request's terms match (prefix either way)."""
    words = name_words(name)
    if not words:
        return 0.0
    hit = sum(1 for w in words if any(w.startswith(t) or t.startswith(w) for t in terms if len(t) >= 3))
    return round(hit / len(words), 4)


def _snippet(node: Mapping[str, Any], terms: Sequence[str], fields: Sequence[str]) -> str:
    for field in fields:
        value = node.get(field)
        if not isinstance(value, str) or not value:
            continue
        low = value.lower()
        for term in terms:
            pos = low.find(term)
            if pos >= 0:
                start = max(0, pos - 60)
                return _shorten(value[start : pos + 100], 160)
    for field in fields:
        value = node.get(field)
        if isinstance(value, str) and value:
            return _shorten(value, 160)
    return ""


def seeds_fulltext(
    store: GraphReader,
    text: str,
    *,
    search_fields: Mapping[str, Sequence[str]],
    types: Sequence[str] | None = None,
    limit: int = 20,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> list[SeedRow]:
    """Query each label's full-text index and merge the results by score.

    `search_fields` is `ontology.search_fields()` (the fields in each label's index). Scores are divided by
    the best raw score across labels so the top result is 1.0; `rawScore` keeps FalkorDB's value.
    """
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    q = fulltext_query(text)
    if not q:
        return []
    terms = [t.rstrip("*") for t in q.split("|")]
    labels = [lb for lb in (types or list(search_fields)) if lb in search_fields]
    rows: list[SeedRow] = []
    for label in labels:
        try:
            res = _q(
                store,
                "CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score "
                f"WHERE {nd('node')} AND NOT (node.id CONTAINS '@v') "
                "RETURN node AS n, score ORDER BY score DESC LIMIT $limit",
                {"label": label, "q": q, "limit": limit},
                timeout_ms,
            )
        except Exception as exc:  # a label without an index, or a query the parser rejects
            log.debug("full-text query skipped", extra={"label": label, "error": str(exc)})
            continue
        for r in res:
            node = r["n"]
            nid = node.get("id")
            if not isinstance(nid, str):
                continue
            name = str(node.get("name") or node.get("title") or node.get("path") or display_label(node))
            rows.append(SeedRow(id=nid, type=label, label=display_label(node),
                                snippet=_snippet(node, terms, search_fields[label]),
                                score=0.0, rawScore=float(r["score"]), nameMatch=name_overlap(name, terms),
                                isTest=bool(node.get("isTest"))))
    if not rows:
        return []
    best = max(s.rawScore for s in rows) or 1.0
    merged: dict[str, SeedRow] = {}
    for s in rows:
        s.score = round(s.rawScore / best, 4)
        if s.id not in merged or merged[s.id].score < s.score:
            merged[s.id] = s
    return sorted(merged.values(), key=lambda s: (-s.score, s.id))[:limit]


# ----------------------------------------------------------------------------------------- renames


def expand_renames(store: GraphReader, node_ids: Sequence[str], timeout_ms: int) -> dict[str, list[str]]:
    """For each id, the chain back through earlier names: {target id: [seed id, ..., target id]}.

    Follows `RENAMED_TO` (and the class and file variants) backwards up to 5 hops, so knowledge attached
    to an earlier name (decisions, PRs, owners) carries over (spec A, A6.10). Tombstoned earlier nodes are
    included on purpose: a renamed function's old node is always tombstoned.
    """
    chains: dict[str, list[str]] = {nid: [nid] for nid in node_ids}
    for label, members in group_by_label(node_ids, RENAME_REL).items():
        rel = RENAME_REL[label]
        res = _q(
            store,
            f"UNWIND $ids AS sid MATCH p = (old:`{label}`)-[:`{rel}`*1..{RENAME_HOPS}]->(s:`{label}` {{id: sid}}) "
            "RETURN sid, [n IN nodes(p) | n.id] AS chain LIMIT $cap",
            {"ids": members, "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            chain = list(reversed(r["chain"]))  # seed first, oldest name last
            target = chain[-1]
            if target not in chains or len(chains[target]) > len(chain):
                chains[target] = chain
    return chains


def code_anchors(store: GraphReader, node_ids: Sequence[str], timeout_ms: int) -> dict[str, list[tuple[str, str]]]:
    """Map each id to the functions and classes it stands for: itself, a class's methods, a file's
    functions, a feature's implementing code. Returns {seed id: [(anchor id, label)]}."""
    out: dict[str, list[tuple[str, str]]] = {nid: [] for nid in node_ids}
    groups = group_by_label(node_ids)
    for nid in groups.get("CodeFunction", []):
        out[nid].append((nid, "CodeFunction"))
    for nid in groups.get("CodeClass", []):
        out[nid].append((nid, "CodeClass"))
    queries = {
        "CodeClass": "UNWIND $ids AS sid MATCH (c:CodeClass {id: sid}) WITH * MATCH (c)<-[:METHOD_OF]-(f:CodeFunction) "
                     f"WHERE {nd('f')} RETURN sid, f.id AS aid, 'CodeFunction' AS label LIMIT $cap",
        "CodeFile": "UNWIND $ids AS sid MATCH (file:CodeFile {id: sid}) WITH * MATCH (file)<-[:FUNCTION_DEFINED_IN]-(f:CodeFunction) "
                    f"WHERE {nd('f')} AND coalesce(f.isTest, false) = false "
                    "RETURN sid, f.id AS aid, 'CodeFunction' AS label LIMIT $cap",
        "Feature": "UNWIND $ids AS sid MATCH (ft:Feature {id: sid}) WITH * MATCH (ft)-[:IMPLEMENTED_IN]->(x) "
                   f"WHERE {nd('x')} RETURN sid, x.id AS aid, labels(x)[0] AS label LIMIT $cap",
        "CodeComponent": "UNWIND $ids AS sid MATCH (c:CodeComponent {id: sid}) WITH * MATCH (c)<-[:FILE_IN_COMPONENT]-(:CodeFile)"
                         f"<-[:FUNCTION_DEFINED_IN]-(f:CodeFunction) WHERE {nd('f')} AND coalesce(f.isTest, false) = false "
                         "RETURN sid, f.id AS aid, 'CodeFunction' AS label ORDER BY f.pageRank DESC LIMIT $cap",
    }
    for label, cypher in queries.items():
        members = groups.get(label, [])
        if not members:
            continue
        for r in _q(store, cypher, {"ids": members, "cap": 200}, timeout_ms):
            if r["label"] in ("CodeFunction", "CodeClass") and (r["aid"], r["label"]) not in out[r["sid"]]:
                out[r["sid"]].append((r["aid"], r["label"]))
    return out


# ----------------------------------------------------------------------------------------- decisions


class DecisionRow(Row):
    id: str
    statement: str
    status: str
    quote: str
    decidedAt: str | None = None
    scope: str | None = None
    confidence: float | None = None
    seedId: str
    targetId: str
    source: SourceRef | None = None
    sourceAuthor: str | None = None
    sourceAt: str | None = None
    approvedIn: list[str] = Field(default_factory=list)
    constrains: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)


def decisions_constraining(
    store: GraphReader,
    node_ids: Sequence[str],
    *,
    include_superseded: bool = True,
    limit: int = 50,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> list[DecisionRow]:
    """Decisions with an active `CONSTRAINS` link to the ids (or to earlier names of them), newest first.

    Only `approved`, `proposed` and (optionally) `superseded` decisions that are not tombstoned; links with
    `active = false` (superseded for this target) and tombstoned links are skipped. `path` runs from the seed
    through any earlier names to the decision.
    """
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    statuses = ["approved", "proposed"] + (["superseded"] if include_superseded else [])
    chains = expand_renames(store, list(node_ids), timeout_ms)
    # A feature or class also stands for the code that implements it: a decision on that code constrains
    # the seed too (path: seed -> anchor -> decision). Files are not expanded: that would be too broad.
    wider = [n for n in node_ids if n.startswith(("actron:feature:", "code:class:"))]
    for seed, items in code_anchors(store, wider, timeout_ms).items():
        for aid, _label in items:
            if aid != seed and aid not in chains:
                chains[aid] = [seed, aid]
    by_target = group_by_label(chains, CONSTRAINABLE)
    seed_rank = {s: i for i, s in enumerate(node_ids)}  # ties go to the earlier (better scored) seed
    found: dict[str, DecisionRow] = {}
    for label, targets in by_target.items():
        res = _q(
            store,
            f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[c:CONSTRAINS]-(d:Decision) "
            f"WHERE {nd('d')} AND {nd('c')} AND coalesce(c.active, true) = true AND d.status IN $statuses "
            "OPTIONAL MATCH (d)-[e:EXTRACTED_FROM]->(src) "
            f"OPTIONAL MATCH (src)-[:{AUTHOR_RELS}]->(au) "
            "OPTIONAL MATCH (d)-[:APPROVED_IN]->(ap) "
            "RETURN tid, d, e.quote AS equote, src, labels(src)[0] AS srcLabel, "
            "coalesce(au.realName, au.displayName, au.name, au.login) AS author, collect(DISTINCT ap.id) AS approved "
            "LIMIT $cap",
            {"tids": targets, "statuses": statuses, "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            d = r["d"]
            did = d["id"]
            chain = chains[r["tid"]]
            src = r.get("src")
            if isinstance(src, dict) and src.get("deleted"):
                src = None
            row = found.get(did)
            if row is None:
                row = DecisionRow(
                    id=did,
                    statement=str(d.get("statement", "")),
                    status=str(d.get("status")),
                    quote=str(r.get("equote") or d.get("quote") or ""),
                    decidedAt=d.get("decidedAt"),
                    scope=d.get("scope"),
                    confidence=d.get("confidence"),
                    seedId=chain[0],
                    targetId=r["tid"],
                    source=SourceRef(id=src["id"], type=str(r["srcLabel"]), url=node_url(src)) if src else None,
                    sourceAuthor=r.get("author") if src else None,
                    sourceAt=node_time(src) if src else None,
                    path=[*chain, did],
                )
                found[did] = row
            elif (len(chain) + 1, seed_rank.get(chain[0], 99)) < (len(row.path), seed_rank.get(row.seedId, 99)):
                row.seedId, row.targetId, row.path = chain[0], r["tid"], [*chain, did]
            for ap in r.get("approved") or []:
                if ap and ap not in row.approvedIn:
                    row.approvedIn.append(ap)
            if r["tid"] not in row.constrains:
                row.constrains.append(r["tid"])
    rows = sorted(found.values(), key=lambda x: x.decidedAt or "", reverse=True)
    return rows[:limit]


# ----------------------------------------------------------------------------------------- related work


class RelatedRow(Row):
    id: str
    type: str
    title: str
    state: str | None = None
    url: str | None = None
    at: str | None = None
    author: str | None = None
    path: list[str] = Field(default_factory=list)


def _related_row(node: Mapping[str, Any], label: str, path: list[str]) -> RelatedRow:
    state: str | None
    if label == "GithubPullRequest":
        state = "merged" if node.get("merged") else node.get("state")
    elif label == "LinearIssue":
        state = node.get("stateType")
    else:
        state = node.get("state")
    title = node.get("title") or node.get("identifier") or _shorten(str(node.get("text") or node.get("body") or ""), 100)
    return RelatedRow(id=node["id"], type=label, title=str(title), state=state, url=node_url(node),
                      at=node_time(node), path=path)


def related_work(
    store: GraphReader,
    node_ids: Sequence[str],
    *,
    limit: int = MAX_RELATED,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> list[RelatedRow]:
    """PRs that touched the ids (`PR_TOUCHED`, review comments via `COMMENT_ON_FUNCTION`), Linear tickets
    implemented by those PRs (`IMPLEMENTED_BY`), and issues and messages that mention the ids (`MENTIONS`).
    Earlier names are followed through `RENAMED_TO`. Newest first."""
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    chains = expand_renames(store, list(node_ids), timeout_ms)
    found: dict[str, RelatedRow] = {}

    def keep(row: RelatedRow) -> None:
        if row.id not in found or len(found[row.id].path) > len(row.path):
            found[row.id] = row

    by_target = group_by_label(chains)
    for label, targets in by_target.items():
        params = {"tids": targets, "cap": PATH_ROW_CAP}
        if label == "CodeFunction":
            for r in _q(store, "UNWIND $tids AS tid MATCH (t:CodeFunction {id: tid}) WITH * MATCH (t)<-[:PR_TOUCHED]-(pr:GithubPullRequest) "
                               f"WHERE {nd('pr')} RETURN tid, pr LIMIT $cap", params, timeout_ms):
                keep(_related_row(r["pr"], "GithubPullRequest", [*chains[r["tid"]], r["pr"]["id"]]))
            for r in _q(store, "UNWIND $tids AS tid MATCH (t:CodeFunction {id: tid}) WITH * MATCH (t)<-[:COMMENT_ON_FUNCTION]-"
                               "(rc:GithubReviewComment)-[:COMMENTS_ON_PR]->(pr:GithubPullRequest) "
                               f"WHERE {nd('rc')} AND {nd('pr')} RETURN tid, rc.id AS rcid, pr LIMIT $cap",
                        params, timeout_ms):
                keep(_related_row(r["pr"], "GithubPullRequest", [*chains[r["tid"]], r["rcid"], r["pr"]["id"]]))
        res = _q(
            store,
            f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[m:MENTIONS]-(x) "
            f"WHERE {nd('x')} AND {nd('m')} AND NOT (x.id CONTAINS '@v') "
            "RETURN tid, x, labels(x)[0] AS xl LIMIT $cap",
            params,
            timeout_ms,
        )
        for r in res:
            if r["xl"] in MENTION_SOURCES and r["xl"] not in ("GitCommit", "CodeDocument"):
                keep(_related_row(r["x"], str(r["xl"]), [*chains[r["tid"]], r["x"]["id"]]))
    prs = [row for row in found.values() if row.type == "GithubPullRequest"]
    if prs:
        res = _q(
            store,
            "UNWIND $pids AS pid MATCH (pr:GithubPullRequest {id: pid}) WITH * MATCH (pr)<-[:IMPLEMENTED_BY]-(li:LinearIssue) "
            f"WHERE {nd('li')} RETURN pid, li LIMIT $cap",
            {"pids": [p.id for p in prs], "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            keep(_related_row(r["li"], "LinearIssue", [*found[r["pid"]].path, r["li"]["id"]]))
    rows = sorted(found.values(), key=lambda x: (x.at or "", x.id), reverse=True)
    return rows[:limit]


# ----------------------------------------------------------------------------------------- callers and callees


class CallRow(Row):
    id: str
    label: str
    depth: int
    callSiteLines: list[int] = Field(default_factory=list)
    confidence: float | None = None
    criticalityPercentile: float | None = None
    isTest: bool = False
    path: list[str] = Field(default_factory=list)


def _call_rows(res: list[dict[str, Any]], limit: int) -> list[CallRow]:
    best: dict[str, CallRow] = {}
    for r in res:
        confs = [c for c in (r.get("confs") or []) if isinstance(c, int | float)]
        lines = r.get("lines") or []
        row = CallRow(
            id=r["id"], label=str(r.get("name") or r["id"]), depth=int(r["depth"]),
            callSiteLines=[int(x) for x in lines if isinstance(x, int | float)],
            confidence=min(confs) if confs else None,
            criticalityPercentile=r.get("crit"), isTest=bool(r.get("isTest")),
            path=list(r.get("pathIds") or []),
        )
        cur = best.get(row.id)
        if cur is None or row.depth < cur.depth or (row.depth == cur.depth and (row.confidence or 0) > (cur.confidence or 0)):
            best[row.id] = row
    rows = sorted(best.values(), key=lambda x: (x.depth, -(x.criticalityPercentile or 0.0), x.id))
    return rows[:limit]


FRONTIER_CAP = 400


def reverse_call_walk(
    store: GraphReader,
    label: str,
    start_ids: Sequence[str],
    depth: int,
    timeout_ms: int,
    *,
    rels: str = "CALLS",
) -> list[dict[str, Any]]:
    """Callers of `start_ids` level by level (one query per hop over a deduplicated frontier).

    A `<-[:CALLS*1..3]-` match enumerates every path, which explodes on hub functions with hundreds of
    callers (docs/falkordb.md 17). Here each function is visited once, at its minimum depth; test functions
    are returned but not expanded (nothing calls a test). Rows have the same shape as the path query:
    sid, id, name, crit, isTest, depth, pathIds (start -> caller), confs, lines.
    """
    parents: dict[str, tuple[str, float | None, list[Any]]] = {}
    origin: dict[str, str] = {s: s for s in start_ids}
    out: list[dict[str, Any]] = []
    frontier = list(dict.fromkeys(start_ids))
    frontier_label = label
    seen = set(frontier)
    for level in range(1, depth + 1):
        if not frontier:
            break
        res = _q(
            store,
            # Anchor on the indexed node first: written as one pattern, FalkorDB scans every CodeFunction
            # per frontier id instead (docs/falkordb.md 17).
            f"UNWIND $ids AS fid MATCH (x:`{frontier_label}` {{id: fid}}) WITH x, fid "
            f"MATCH (x)<-[r:{rels}]-(c:CodeFunction) "
            f"WHERE {nd('c')} "
            "RETURN fid, c.id AS id, c.qualifiedName AS name, c.criticalityPercentile AS crit, "
            "c.isTest AS isTest, r.confidence AS conf, r.callSiteLines AS lines LIMIT $cap",
            {"ids": frontier[:FRONTIER_CAP], "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        nxt: list[str] = []
        for r in res:
            cid = str(r["id"])
            if cid in seen:
                continue
            seen.add(cid)
            parent = str(r["fid"])
            parents[cid] = (parent, r.get("conf"), list(r.get("lines") or []))
            origin[cid] = origin[parent]
            path = [cid]
            confs: list[Any] = []
            node = cid
            while node in parents:
                p, conf, _ = parents[node]
                confs.append(conf)
                path.append(p)
                node = p
            path.reverse()
            out.append({"sid": origin[cid], "id": cid, "name": r.get("name"), "crit": r.get("crit"),
                        "isTest": r.get("isTest"), "depth": level, "pathIds": path,
                        "confs": list(reversed(confs)), "lines": parents[cid][2]})
            if not r.get("isTest"):
                nxt.append(cid)
        frontier = nxt
        frontier_label = "CodeFunction"
    return out


def callers(
    store: GraphReader, function_id: str, depth: int = 3, *, limit: int = MAX_ROWS, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[CallRow]:
    """Distinct functions that call `function_id` within `depth` hops (backwards over CALLS), each at its
    minimum depth. `callSiteLines` are the lines in the caller where it makes the call; `confidence` is the
    weakest edge on the path; `path` runs from the function to the caller."""
    if label_for(function_id) != "CodeFunction":
        raise QueryError("callers needs a function id (code:fn:...)")
    depth = _clamp(depth, 1, 3, "depth")
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    return _call_rows(reverse_call_walk(store, "CodeFunction", [function_id], depth, timeout_ms), limit)


def callees(
    store: GraphReader, function_id: str, depth: int = 3, *, limit: int = MAX_ROWS, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[CallRow]:
    """Distinct functions that `function_id` calls within `depth` hops (forward over CALLS)."""
    if label_for(function_id) != "CodeFunction":
        raise QueryError("callees needs a function id (code:fn:...)")
    depth = _clamp(depth, 1, 3, "depth")
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    res = _q(
        store,
        f"MATCH p = (f:CodeFunction {{id: $id}})-[:CALLS*1..{depth}]->(c:CodeFunction) "
        "WHERE all(n IN nodes(p)[1..] WHERE coalesce(n.deleted, false) = false) "
        "RETURN c.id AS id, c.qualifiedName AS name, c.criticalityPercentile AS crit, c.isTest AS isTest, "
        "length(p) AS depth, [n IN nodes(p) | n.id] AS pathIds, [r IN relationships(p) | r.confidence] AS confs, "
        "head(relationships(p)).callSiteLines AS lines LIMIT $cap",
        {"id": function_id, "cap": PATH_ROW_CAP},
        timeout_ms,
    )
    return _call_rows(res, limit)


# ----------------------------------------------------------------------------------------- impact


class ImpactFunction(Row):
    id: str
    label: str
    depth: int
    criticalityPercentile: float | None = None
    path: list[str] = Field(default_factory=list)


class ImpactFile(Row):
    id: str
    path: str


class ImpactTest(Row):
    id: str
    label: str
    targetId: str
    method: str | None = None
    confidence: float | None = None
    path: list[str] = Field(default_factory=list)


class ImpactComponent(Row):
    id: str
    name: str


class ImpactResult(Row):
    functions: list[ImpactFunction] = Field(default_factory=list)
    files: list[ImpactFile] = Field(default_factory=list)
    tests: list[ImpactTest] = Field(default_factory=list)
    components: list[ImpactComponent] = Field(default_factory=list)


def tests_for(
    store: GraphReader, node_ids: Sequence[str], *, limit: int = MAX_ROWS, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[ImpactTest]:
    """Test functions that exercise the ids (`TESTS` for functions, `TESTS_CLASS` for classes; files,
    features and components are resolved to their functions first)."""
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    anchors = code_anchors(store, list(node_ids), timeout_ms)
    seed_of: dict[str, str] = {}
    fn_ids: list[str] = []
    cls_ids: list[str] = []
    for seed, items in anchors.items():
        for aid, label in items:
            seed_of.setdefault(aid, seed)
            (fn_ids if label == "CodeFunction" else cls_ids).append(aid)
    out: dict[str, ImpactTest] = {}
    for label, rel, members in (("CodeFunction", "TESTS", fn_ids), ("CodeClass", "TESTS_CLASS", cls_ids)):
        if not members:
            continue
        res = _q(
            store,
            f"UNWIND $ids AS tid MATCH (x:`{label}` {{id: tid}}) WITH * MATCH (x)<-[r:`{rel}`]-(t:CodeFunction) "
            f"WHERE {nd('t')} AND {nd('r')} RETURN tid, t.id AS id, t.qualifiedName AS name, r.method AS method, "
            "r.confidence AS conf LIMIT $cap",
            {"ids": list(dict.fromkeys(members)), "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            seed = seed_of[r["tid"]]
            path = [seed, r["id"]] if seed == r["tid"] else [seed, r["tid"], r["id"]]
            row = ImpactTest(id=r["id"], label=str(r["name"] or r["id"]), targetId=r["tid"], method=r.get("method"),
                             confidence=r.get("conf"), path=path)
            cur = out.get(row.id)
            if cur is None or (row.confidence or 0) > (cur.confidence or 0):
                out[row.id] = row
    rows = sorted(out.values(), key=lambda t: (-(t.confidence or 0), t.id))
    return rows[:limit]


def impact(
    store: GraphReader,
    node_ids: Sequence[str],
    depth: int = 3,
    *,
    limit: int = MAX_ROWS,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> ImpactResult:
    """Everything that could break if the ids change: callers backwards over `CALLS` and `INSTANTIATES`
    (depth <= 3; a class also starts from its methods via `METHOD_OF`), their files and components, and the
    tests that cover the ids or their callers."""
    depth = _clamp(depth, 1, 3, "depth")
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    anchors = code_anchors(store, list(node_ids), timeout_ms)
    starts: dict[str, list[str]] = defaultdict(list)
    seed_of: dict[str, str] = {}
    for seed, items in anchors.items():
        for aid, label in items:
            if aid not in starts[label]:
                starts[label].append(aid)
            seed_of.setdefault(aid, seed)
    raw: list[dict[str, Any]] = []
    for label, members in starts.items():
        raw.extend(reverse_call_walk(store, label, members, depth, timeout_ms, rels="CALLS|INSTANTIATES"))
    start_ids = {aid for members in starts.values() for aid in members}
    best: dict[str, ImpactFunction] = {}
    for r in raw:
        if r["id"] in start_ids or r.get("isTest"):
            continue
        seed = seed_of[r["sid"]]
        path = list(r["pathIds"])
        if seed != path[0]:
            path = [seed, *path]
        row = ImpactFunction(id=r["id"], label=str(r.get("name") or r["id"]), depth=int(r["depth"]),
                             criticalityPercentile=r.get("crit"), path=path)
        if row.id not in best or row.depth < best[row.id].depth:
            best[row.id] = row
    functions = sorted(best.values(), key=lambda f: (f.depth, -(f.criticalityPercentile or 0.0), f.id))[:limit]
    fn_ids = [f.id for f in functions] + list(starts.get("CodeFunction", []))
    files: dict[str, ImpactFile] = {}
    components: dict[str, ImpactComponent] = {}
    if fn_ids:
        res = _q(
            store,
            "UNWIND $ids AS fid MATCH (f:CodeFunction {id: fid}) WITH * MATCH (f)-[:FUNCTION_DEFINED_IN]->(file:CodeFile) "
            f"WHERE {nd('file')} OPTIONAL MATCH (file)-[:FILE_IN_COMPONENT]->(comp:CodeComponent) "
            "RETURN DISTINCT file.id AS id, file.path AS path, comp.id AS cid, comp.name AS cname LIMIT $cap",
            {"ids": fn_ids, "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            files[r["id"]] = ImpactFile(id=r["id"], path=str(r["path"]))
            if r.get("cid"):
                components[r["cid"]] = ImpactComponent(id=r["cid"], name=str(r.get("cname") or r["cid"]))
    tests = tests_for(store, [*node_ids, *[f.id for f in functions]], limit=limit, timeout_ms=timeout_ms)
    for t in tests:
        if t.path and t.path[0] not in node_ids:
            caller = best.get(t.path[0])
            if caller is not None:
                t.path = [*caller.path, t.id]
    return ImpactResult(
        functions=functions,
        files=sorted(files.values(), key=lambda f: f.path)[:limit],
        tests=tests,
        components=sorted(components.values(), key=lambda c: c.id)[:limit],
    )


# ----------------------------------------------------------------------------------------- criticality


class CriticalityRow(Row):
    id: str
    pageRank: float | None = None
    callerCount: int | None = None
    transitiveCallerCount: int | None = None
    criticalityPercentile: float | None = None


def criticality(store: GraphReader, node_ids: Sequence[str], *, timeout_ms: int = TOOL_TIMEOUT_MS) -> list[CriticalityRow]:
    """Stored criticality metrics for functions (PageRank over CALLS, caller counts, percentile)."""
    members = group_by_label(node_ids, ["CodeFunction"]).get("CodeFunction", [])
    if not members:
        return []
    res = _q(
        store,
        "UNWIND $ids AS fid MATCH (f:CodeFunction {id: fid}) "
        "RETURN f.id AS id, f.pageRank AS pr, f.callerCount AS cc, f.transitiveCallerCount AS tc, "
        "f.criticalityPercentile AS pct LIMIT $cap",
        {"ids": members[:MAX_ROWS], "cap": MAX_ROWS},
        timeout_ms,
    )
    rows = [CriticalityRow(id=r["id"], pageRank=r.get("pr"), callerCount=r.get("cc"),
                           transitiveCallerCount=r.get("tc"), criticalityPercentile=r.get("pct")) for r in res]
    return sorted(rows, key=lambda r: (-(r.criticalityPercentile or 0.0), r.id))


# ----------------------------------------------------------------------------------------- shortest path


class PathNode(Row):
    id: str
    type: str
    label: str


class PathLink(Row):
    from_: str = Field(alias="from")
    to: str
    type: str


class PathResult(Row):
    found: bool
    nodes: list[PathNode] = Field(default_factory=list)
    links: list[PathLink] = Field(default_factory=list)
    method: Literal["algo.SPpaths", "bfs"] | None = None


def shortest_path(
    store: GraphReader,
    from_id: str,
    to_id: str,
    max_hops: int = 6,
    *,
    use_procedure: bool = True,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> PathResult:
    """Shortest path between two nodes in either direction ("how is this connected").

    Uses `algo.SPpaths(... relDirection: 'both')`; when the procedure is unavailable or fails, falls back to a
    breadth-first search in Python over labelled neighbour lookups. Both return one shortest path.
    """
    max_hops = _clamp(max_hops, 1, 6, "maxHops")
    la, lb = label_for(from_id), label_for(to_id)
    if from_id == to_id:
        node = fetch_nodes(store, [from_id], timeout_ms).get(from_id)
        if not node:
            return PathResult(found=False)
        return PathResult(found=True, nodes=[PathNode(id=from_id, type=la, label=display_label(node))])
    if use_procedure:
        try:
            res = _q(
                store,
                f"MATCH (a:`{la}` {{id: $a}}), (b:`{lb}` {{id: $b}}) "
                f"CALL algo.SPpaths({{sourceNode: a, targetNode: b, relDirection: 'both', maxLen: {max_hops}}}) "
                "YIELD path RETURN [n IN nodes(path) | n] AS ns, "
                "[r IN relationships(path) | [startNode(r).id, type(r), endNode(r).id]] AS rs LIMIT 1",
                {"a": from_id, "b": to_id},
                timeout_ms,
            )
        except Exception as exc:
            log.info("algo.SPpaths failed; using BFS", extra={"error": str(exc)})
        else:
            if not res:
                return PathResult(found=False, method="algo.SPpaths")
            ns = res[0]["ns"]
            return PathResult(
                found=True,
                nodes=[PathNode(id=n["id"], type=str(n.get("_label")), label=display_label(n)) for n in ns],
                links=[PathLink(**{"from": s, "to": e, "type": t}) for s, t, e in res[0]["rs"]],
                method="algo.SPpaths",
            )
    return _bfs_path(store, from_id, to_id, max_hops, timeout_ms)


def neighbours(
    store: GraphReader, node_id: str, *, limit: int = 200, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[tuple[str, str, str, bool]]:
    """(neighbour id, neighbour label, relationship type, outgoing?) for one node, both directions."""
    label = label_for(node_id)
    res = _q(
        store,
        f"MATCH (n:`{label}` {{id: $id}})-[r]-(m) "
        "RETURN m.id AS id, labels(m)[0] AS label, type(r) AS type, startNode(r).id = n.id AS out LIMIT $limit",
        {"id": node_id, "limit": limit},
        timeout_ms,
    )
    return [(r["id"], str(r["label"]), str(r["type"]), bool(r["out"])) for r in res if isinstance(r.get("id"), str)]


def _bfs_path(store: GraphReader, a: str, b: str, max_hops: int, timeout_ms: int) -> PathResult:
    deadline = time.monotonic() + timeout_ms / 1000.0
    parent: dict[str, tuple[str, str, bool] | None] = {a: None}
    frontier = [a]
    for _ in range(max_hops):
        nxt: list[str] = []
        for nid in frontier:
            if time.monotonic() > deadline:
                return PathResult(found=False, method="bfs")
            try:
                nbrs = neighbours(store, nid, timeout_ms=timeout_ms)
            except QueryError:
                continue
            for mid, _label, rtype, out in nbrs:
                if mid in parent:
                    continue
                parent[mid] = (nid, rtype, out)
                if mid == b:
                    return _bfs_result(store, parent, b, timeout_ms)
                nxt.append(mid)
        frontier = nxt
        if not frontier:
            break
    return PathResult(found=False, method="bfs")


def _bfs_result(store: GraphReader, parent: Mapping[str, tuple[str, str, bool] | None], end: str,
                timeout_ms: int) -> PathResult:
    chain: list[str] = [end]
    links: list[PathLink] = []
    cur = end
    while (step := parent[cur]) is not None:
        prev, rtype, out = step
        links.append(PathLink(**{"from": prev if out else cur, "to": cur if out else prev, "type": rtype}))
        chain.append(prev)
        cur = prev
    chain.reverse()
    links.reverse()
    nodes = fetch_nodes(store, chain, timeout_ms)
    return PathResult(
        found=True,
        nodes=[PathNode(id=n, type=label_for(n), label=display_label(nodes.get(n, {"id": n}))) for n in chain],
        links=links,
        method="bfs",
    )


def fetch_nodes(store: GraphReader, node_ids: Iterable[str], timeout_ms: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for label, members in group_by_label(node_ids).items():
        for r in _q(store, f"UNWIND $ids AS nid MATCH (n:`{label}` {{id: nid}}) RETURN n LIMIT $cap",
                    {"ids": members, "cap": len(members)}, timeout_ms):
            out[r["n"]["id"]] = r["n"]
    return out


# ----------------------------------------------------------------------------------------- owners and procedures


class OwnerRow(Row):
    personId: str | None
    name: str
    basis: list[str] = Field(default_factory=list)
    score: float
    path: list[str] = Field(default_factory=list)


_SIGNAL_BASIS = {"commits": "commits", "blame": "blame", "reviews": "reviews", "tickets": "tickets", "slack": "slack"}


def owners(
    store: GraphReader, node_ids: Sequence[str], *, limit: int = MAX_OWNERS, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[OwnerRow]:
    """People who own or know the ids: `KNOWS_ABOUT` (score, signals), `OWNS` (CODEOWNERS or dominant blame)
    and `BLAME_OWNS` through `IS_GIT_AUTHOR` identities. A person's score is the strongest signal:
    KNOWS_ABOUT score, blame line share, 1.0 for a CODEOWNERS owner (0.8 for other OWNS)."""
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    chains = expand_renames(store, list(node_ids), timeout_ms)
    people: dict[str, OwnerRow] = {}

    def add(key: str, person_id: str | None, name: str, basis: Iterable[str], score: float, path: list[str]) -> None:
        row = people.get(key)
        if row is None:
            row = people[key] = OwnerRow(personId=person_id, name=name, basis=[], score=0.0, path=path)
        for b in basis:
            if b and b not in row.basis:
                row.basis.append(b)
        if score > row.score:
            row.score = round(score, 4)
            row.path = path

    for label, targets in group_by_label(chains, CONSTRAINABLE).items():
        params = {"tids": targets, "cap": PATH_ROW_CAP}
        for r in _q(store, f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[k:KNOWS_ABOUT]-(p:Person) "
                           f"WHERE {nd('p')} AND {nd('k')} RETURN tid, p.id AS pid, p.displayName AS name, "
                           "k.score AS score, k.signals AS signals LIMIT $cap", params, timeout_ms):
            signals = [str(s) for s in (r.get("signals") or [])]
            add(r["pid"], r["pid"], str(r["name"]), [_SIGNAL_BASIS.get(s, s) for s in signals] or ["knows"],
                float(r.get("score") or 0.0), [*chains[r["tid"]], r["pid"]])
        for r in _q(store, f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[o:OWNS]-(p:Person) "
                           f"WHERE {nd('p')} AND {nd('o')} RETURN tid, p.id AS pid, p.displayName AS name, "
                           "o.basis AS basis LIMIT $cap", params, timeout_ms):
            basis = str(r.get("basis") or "owner")
            add(r["pid"], r["pid"], str(r["name"]), [basis], 1.0 if basis == "codeowners" else 0.8,
                [*chains[r["tid"]], r["pid"]])
        rel = {"CodeFunction": "BLAME_OWNS", "CodeFile": "BLAME_OWNS_FILE"}.get(label)
        if rel:
            for r in _q(store, f"UNWIND $tids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[b:`{rel}`]-(a:GitAuthor) "
                               f"WHERE {nd('a')} "
                               "OPTIONAL MATCH (a)<-[:IS_GIT_AUTHOR]-(i:Identity)<-[:HAS_IDENTITY]-(p:Person) "
                               "RETURN tid, a.id AS aid, coalesce(a.name, a.email) AS aname, b.lineShare AS share, "
                               "i.id AS iid, p.id AS pid, p.displayName AS pname LIMIT $cap", params, timeout_ms):
                pid = r.get("pid")
                path = [*chains[r["tid"]], r["aid"]] + ([r["iid"], pid] if pid else [])
                add(pid or r["aid"], pid, str(r.get("pname") or r["aname"]), ["blame"],
                    float(r.get("share") or 0.0), path)
    rows = sorted(people.values(), key=lambda o: (-o.score, o.name))
    return rows[:limit]


class ProcedureRow(Row):
    procedureId: str
    title: str
    testCommand: str | None = None
    coChangedPaths: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)


def procedures_for(
    store: GraphReader, node_ids: Sequence[str], *, limit: int = 20, timeout_ms: int = TOOL_TIMEOUT_MS
) -> list[ProcedureRow]:
    """Procedures (how changes are made here) that apply to the ids, or to the files that hold them."""
    limit = _clamp(limit, 1, MAX_ROWS, "limit")
    out: dict[str, ProcedureRow] = {}

    def add(r: Mapping[str, Any], path: list[str]) -> None:
        p = r["p"]
        if p["id"] in out and len(out[p["id"]].path) <= len(path):
            return
        out[p["id"]] = ProcedureRow(procedureId=p["id"], title=str(p.get("title", "")), testCommand=p.get("testCommand"),
                                    coChangedPaths=list(p.get("coChangedPaths") or []), steps=list(p.get("steps") or []),
                                    path=path)

    for label, members in group_by_label(node_ids, CONSTRAINABLE).items():
        for r in _q(store, f"UNWIND $ids AS tid MATCH (t:`{label}` {{id: tid}}) WITH * MATCH (t)<-[:APPLIES_TO]-(p:Procedure) "
                           f"WHERE {nd('p')} RETURN tid, p LIMIT $cap", {"ids": members, "cap": MAX_ROWS}, timeout_ms):
            add(r, [r["tid"], r["p"]["id"]])
        if label == "CodeFunction":
            for r in _q(store, "UNWIND $ids AS tid MATCH (t:CodeFunction {id: tid}) WITH * MATCH (t)-[:FUNCTION_DEFINED_IN]->(f:CodeFile)"
                               f"<-[:APPLIES_TO]-(p:Procedure) WHERE {nd('p')} RETURN tid, f.id AS fid, p LIMIT $cap",
                        {"ids": members, "cap": MAX_ROWS}, timeout_ms):
                add(r, [r["tid"], r["fid"], r["p"]["id"]])
    return sorted(out.values(), key=lambda p: p.procedureId)[:limit]


# ----------------------------------------------------------------------------------------- subgraphs


class SubgraphNode(Row):
    id: str
    type: str
    label: str
    group: Literal["code", "github", "slack", "linear", "core"]
    count: int | None = None
    props: dict[str, Any] | None = None


class SubgraphLink(Row):
    from_: str = Field(alias="from")
    to: str
    type: str
    method: str | None = None
    confidence: float | None = None
    count: int | None = None


class Subgraph(Row):
    mode: Literal["aggregated", "expanded"]
    nodes: list[SubgraphNode] = Field(default_factory=list)
    links: list[SubgraphLink] = Field(default_factory=list)
    truncated: bool = False


def subgraph_for_ids(
    store: GraphReader,
    ordered_ids: Sequence[str],
    *,
    mode: Literal["aggregated", "expanded"] = "aggregated",
    keep: Iterable[str] = (),
    budget: int = MAX_GRAPH_NODES,
    aggregate_above: int | None = None,
    timeout_ms: int = TOOL_TIMEOUT_MS,
) -> Subgraph:
    """Nodes for the ids (in priority order) and every link among them.

    Up to `budget` nodes are returned one by one. Above it, `expanded` keeps the first `budget` ids and marks
    the result truncated; `aggregated` keeps the `keep` ids (request, seeds, decisions) individually and
    collapses the rest into one node per type with a count.
    """
    unique = list(dict.fromkeys(i for i in ordered_ids if _valid(i)))
    nodes = fetch_nodes(store, unique, timeout_ms)
    unique = [i for i in unique if i in nodes]
    links = _links_among(store, unique, timeout_ms)
    limit = budget if mode == "expanded" or aggregate_above is None else min(budget, aggregate_above)
    if len(unique) <= limit:
        return Subgraph(mode=mode, nodes=[_sg_node(nodes[i]) for i in unique], links=links, truncated=False)
    if mode == "expanded":
        kept = set(unique[:budget])
        return Subgraph(mode=mode, nodes=[_sg_node(nodes[i]) for i in unique[:budget]],
                        links=[lk for lk in links if lk.from_ in kept and lk.to in kept], truncated=True)
    keep_set = {i for i in keep if i in nodes}
    rep: dict[str, str] = {}
    groups: dict[str, int] = defaultdict(int)
    for i in unique:
        if i in keep_set:
            rep[i] = i
        else:
            # Test functions get their own cluster so "200 tests" reads apart from callers.
            label = str(nodes[i].get("_label"))
            bucket = f"{label}:test" if nodes[i].get("isTest") else label
            rep[i] = f"group:{bucket}"
            groups[bucket] += 1
    out_nodes = [_sg_node(nodes[i]) for i in unique if i in keep_set]
    for bucket, n in sorted(groups.items()):
        lb, _, test = bucket.partition(":")
        one, many = ("test", "tests") if test else _PLAIN_NAMES.get(lb, (lb, lb))
        name = f"{n:,} {one if n == 1 else many}"
        out_nodes.append(SubgraphNode(id=f"group:{bucket}", type=lb, label=name, group=group_of(lb), count=n))
    agg: dict[tuple[str, str, str], SubgraphLink] = {}
    for lk in links:
        key = (rep[lk.from_], rep[lk.to], lk.type)
        if key[0] == key[1]:
            continue
        if key in agg:
            agg[key].count = (agg[key].count or 1) + 1
        else:
            agg[key] = SubgraphLink(**{"from": key[0], "to": key[1], "type": lk.type, "method": lk.method,
                                       "confidence": lk.confidence, "count": 1})
    return Subgraph(mode="aggregated", nodes=out_nodes, links=list(agg.values()), truncated=False)


# Cluster names a reader understands ("21 functions", not "21 CodeFunction").
_PLAIN_NAMES: dict[str, tuple[str, str]] = {
    "CodeFunction": ("function", "functions"), "CodeClass": ("class", "classes"), "CodeFile": ("file", "files"),
    "CodeChunk": ("code chunk", "code chunks"), "CodeDocument": ("doc section", "doc sections"),
    "GitCommit": ("commit", "commits"), "GithubPullRequest": ("pull request", "pull requests"),
    "GithubReviewComment": ("review comment", "review comments"), "GithubIssue": ("issue", "issues"),
    "SlackMessage": ("message", "messages"), "LinearIssue": ("ticket", "tickets"),
    "Decision": ("decision", "decisions"), "Person": ("person", "people"), "Feature": ("feature", "features"),
}


def _valid(node_id: str) -> bool:
    try:
        ids.label_of(node_id)
    except ids.InvalidId:
        return False
    return True


def _sg_node(node: Mapping[str, Any]) -> SubgraphNode:
    label = str(node.get("_label"))
    return SubgraphNode(id=str(node["id"]), type=label, label=display_label(node), group=group_of(label))


def _links_among(store: GraphReader, node_ids: Sequence[str], timeout_ms: int) -> list[SubgraphLink]:
    wanted = set(node_ids)
    out: dict[tuple[str, str, str], SubgraphLink] = {}
    for label, members in group_by_label(node_ids).items():
        res = _q(
            store,
            f"UNWIND $ids AS nid MATCH (a:`{label}` {{id: nid}}) WITH * MATCH (a)-[r]->(b) WHERE b.id IN $all AND {nd('r')} "
            "RETURN a.id AS a, type(r) AS t, b.id AS b, r.method AS m, r.confidence AS c LIMIT $cap",
            {"ids": members, "all": list(wanted), "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in res:
            key = (r["a"], r["b"], r["t"])
            out[key] = SubgraphLink(**{"from": r["a"], "to": r["b"], "type": r["t"], "method": r.get("m"),
                                       "confidence": r.get("c")})
    return sorted(out.values(), key=lambda lk: (lk.from_, lk.to, lk.type))


def subgraph_for_request(
    store: GraphReader,
    request_id: str,
    mode: Literal["aggregated", "expanded"] = "aggregated",
    *,
    budget: int = MAX_GRAPH_NODES,
    timeout_ms: int = SHARED_TIMEOUT_MS,
) -> Subgraph:
    """The request node, its `ABOUT` seeds, everything its latest `Investigation` `FOUND`, and the nodes on
    the stored paths between them (aggregated mode clusters by type above AGGREGATE_ABOVE nodes, keeping the
    request, seeds, decisions and the top findings with their paths)."""
    rid = request_graph_id(request_id)
    res = _q(
        store,
        "MATCH (r:Request {id: $rid}) OPTIONAL MATCH (r)-[:ABOUT]->(s) "
        "WITH r, collect(DISTINCT s.id) AS seeds "
        "OPTIONAL MATCH (r)-[:HAS_INVESTIGATION]->(i:Investigation) "
        "RETURN seeds, i.id AS iid, i.startedAt AS started ORDER BY started DESC LIMIT 1",
        {"rid": rid},
        timeout_ms,
    )
    if not res:
        return Subgraph(mode=mode)
    seeds = [s for s in (res[0].get("seeds") or []) if s]
    ordered: list[str] = [rid, *seeds]
    keep: list[str] = [rid, *seeds]
    iid = res[0].get("iid")
    if iid:
        found = _q(
            store,
            "MATCH (i:Investigation {id: $iid})-[f:FOUND]->(e) "
            "RETURN e.id AS id, labels(e)[0] AS label, f.role AS role, f.rank AS rank, f.path AS path "
            "ORDER BY f.rank LIMIT $cap",
            {"iid": iid, "cap": PATH_ROW_CAP},
            timeout_ms,
        )
        for r in found:
            ordered.append(r["id"])
            top = isinstance(r.get("rank"), int | float) and r["rank"] < AGGREGATE_KEEP_TOP
            if r.get("label") == "Decision" or top:
                keep.append(r["id"])
                keep.extend(p for p in (r.get("path") or []) if isinstance(p, str))
        for r in found:
            ordered.extend(p for p in (r.get("path") or []) if isinstance(p, str))
    return subgraph_for_ids(store, ordered, mode=mode, keep=keep, budget=budget,
                            aggregate_above=AGGREGATE_ABOVE, timeout_ms=timeout_ms)


# ----------------------------------------------------------------------------------------- shared query


def request_graph_id(request_id: str) -> str:
    return request_id if request_id.startswith("actron:request:") else ids.request(request_id)


StepRecorder = Callable[[str, dict[str, Any], list[str], float, str | None], None]


class SharedQueryResult(Row):
    findings: Findings
    details: dict[str, NodeBrief] = Field(default_factory=dict)


def shared_query(
    store: GraphReader,
    request_id: str,
    seed_ids: Sequence[str],
    seed_scores: Mapping[str, float] | None = None,
    *,
    record: StepRecorder | None = None,
    timeout_ms: int = SHARED_TIMEOUT_MS,
) -> SharedQueryResult:
    """Compose the named queries into the B.C3 findings for a request and its seeds.

    Ordering and limits: seeds by score (10); decisions by decidedAt, newest first (15; the investigation
    re-sorts by conflict probability after J6); related work by recency (15); callers by depth then
    criticality (50); owners (5); graph nodes (300). Each item's path starts at the request node.
    `record(tool, args, nodeIds, durationMs, error)` is called once per named query, so the pipeline can
    show each graph query on the timeline.
    """
    rid = request_graph_id(request_id)
    scores = dict(seed_scores or {})
    valid_seeds = [s for s in dict.fromkeys(seed_ids) if _valid(s)]
    existing = fetch_nodes(store, valid_seeds, timeout_ms)
    seeds = sorted((s for s in valid_seeds if s in existing and not existing[s].get("deleted")),
                   key=lambda s: (-scores.get(s, 0.0), valid_seeds.index(s)))[:MAX_SEEDS]
    details: dict[str, NodeBrief] = {}

    def step(tool: str, args: dict[str, Any], fn: Callable[[], Any], node_ids_of: Callable[[Any], list[str]]) -> Any:
        started = time.monotonic()
        try:
            out = fn()
        except Exception as exc:
            if record:
                record(tool, args, [], (time.monotonic() - started) * 1000, str(exc))
            raise
        if record:
            record(tool, args, node_ids_of(out), (time.monotonic() - started) * 1000, None)
        return out

    seed_items = [SeedItem(id=s, type=str(existing[s].get("_label")), score=round(scores.get(s, 0.0), 4), path=[rid, s])
                  for s in seeds]
    for s in seeds:
        details[s] = NodeBrief(id=s, type=str(existing[s].get("_label")), title=display_label(existing[s]),
                               url=node_url(existing[s]), at=node_time(existing[s]))
    if not seeds:
        return SharedQueryResult(findings=Findings(requestId=rid, label="nothing_found",
                                                   graph=FindingsGraph()), details=details)

    drows: list[DecisionRow] = step("decisions_for", {"ids": seeds, "includeSuperseded": True},
                                    lambda: decisions_constraining(store, seeds, include_superseded=True,
                                                                   limit=MAX_DECISIONS, timeout_ms=timeout_ms),
                                    lambda rows: [r.id for r in rows])
    decisions = [
        DecisionItem(id=d.id, statement=d.statement, status=d.status, quote=d.quote,
                     source=d.source, conflict=Conflict(), path=[rid, *d.path], decidedAt=d.decidedAt)
        for d in drows
    ]
    for d in drows:
        details[d.id] = NodeBrief(id=d.id, type="Decision", title=d.statement, url=d.source.url if d.source else None,
                                  author=d.sourceAuthor, at=d.sourceAt or d.decidedAt, quote=d.quote,
                                  confidence=d.confidence)
        if d.source:
            details.setdefault(d.source.id, NodeBrief(id=d.source.id, type=d.source.type, title=d.quote,
                                                      url=d.source.url, author=d.sourceAuthor, at=d.sourceAt))

    rrows: list[RelatedRow] = step("related_work", {"ids": seeds},
                                   lambda: related_work(store, seeds, limit=MAX_RELATED, timeout_ms=timeout_ms),
                                   lambda rows: [r.id for r in rows])
    related = [RelatedWorkItem(id=r.id, type=r.type, title=r.title, state=r.state, url=r.url, at=r.at,
                               path=[rid, *r.path]) for r in rrows]
    for r in rrows:
        details[r.id] = NodeBrief(id=r.id, type=r.type, title=r.title, url=r.url, at=r.at)

    imp: ImpactResult = step("impact", {"ids": seeds, "depth": 3},
                             lambda: impact(store, seeds, 3, limit=MAX_ROWS, timeout_ms=timeout_ms),
                             lambda res: [f.id for f in res.functions] + [t.id for t in res.tests])
    callers_items = [CallerItem(id=f.id, depth=f.depth, path=[rid, *f.path]) for f in imp.functions][:MAX_CALLERS]
    seed_tests = [t for t in imp.tests if t.path and t.path[0] in seeds]
    tests = [TestItem(id=t.id, path=[rid, *t.path]) for t in seed_tests]
    for f in imp.functions:
        details[f.id] = NodeBrief(id=f.id, type="CodeFunction", title=f.label)
    for t in seed_tests:
        details[t.id] = NodeBrief(id=t.id, type="CodeFunction", title=t.label, confidence=t.confidence)

    anchors = code_anchors(store, seeds, timeout_ms)
    fn_anchor_path: dict[str, list[str]] = {}
    for seed, items in anchors.items():
        for aid, label in items:
            if label == "CodeFunction":
                fn_anchor_path.setdefault(aid, [rid, seed] if aid == seed else [rid, seed, aid])
    crows: list[CriticalityRow] = step("criticality", {"ids": list(fn_anchor_path)},
                                       lambda: criticality(store, list(fn_anchor_path), timeout_ms=timeout_ms),
                                       lambda rows: [r.id for r in rows])
    crit = [CriticalityItem(id=c.id, percentile=float(c.criticalityPercentile), path=fn_anchor_path[c.id])
            for c in crows if c.criticalityPercentile is not None and not math.isnan(c.criticalityPercentile)]

    orows: list[OwnerRow] = step("owners", {"ids": seeds},
                                 lambda: owners(store, seeds, limit=MAX_OWNERS, timeout_ms=timeout_ms),
                                 lambda rows: [r.personId for r in rows if r.personId])
    owner_items = [OwnerItem(personId=o.personId, name=o.name, basis=o.basis, score=o.score, path=[rid, *o.path])
                   for o in orows]
    prows: list[ProcedureRow] = step("procedures_for", {"ids": seeds},
                                     lambda: procedures_for(store, seeds, timeout_ms=timeout_ms),
                                     lambda rows: [r.procedureId for r in rows])
    procs = [ProcedureItem(id=p.procedureId, testCommand=p.testCommand, path=[rid, *p.path]) for p in prows]
    for p in prows:
        details[p.procedureId] = NodeBrief(id=p.procedureId, type="Procedure", title=p.title)

    from actron.flow.labels import compute_label

    label = compute_label(
        restricts=[],
        seed_count=len(seeds),
        decision_count=len(decisions),
        max_seed_criticality=max((c.percentile for c in crit), default=None),
    )
    findings = Findings(
        requestId=rid,
        seeds=seed_items,
        decisions=decisions,
        relatedWork=related,
        impact=Impact(callers=callers_items, tests=tests, criticality=crit),
        owners=owner_items,
        procedures=procs,
        label=label,
    )
    findings.graph = findings_graph(store, findings, timeout_ms=timeout_ms)
    return SharedQueryResult(findings=findings, details=details)


def findings_graph(store: GraphReader, findings: Findings, *, timeout_ms: int = SHARED_TIMEOUT_MS) -> FindingsGraph:
    """The appendix D `graph`: every node on a finding's path (max 300, in priority order) and the links among them."""
    ordered: list[str] = [findings.requestId]
    paths: list[list[str]] = [s.path for s in findings.seeds] + [d.path for d in findings.decisions]
    paths += [r.path for r in findings.relatedWork] + [t.path for t in findings.impact.tests]
    paths += [c.path for c in findings.impact.callers] + [o.path for o in findings.owners]
    paths += [p.path for p in findings.procedures]
    for path in paths:
        ordered.extend(path)
    for d in findings.decisions:
        if d.source:
            ordered.append(d.source.id)
    sg = subgraph_for_ids(store, ordered, mode="expanded", budget=MAX_GRAPH_NODES, timeout_ms=timeout_ms)
    nodes = [GraphNodeBrief(id=n.id, type=n.type, label=n.label) for n in sg.nodes]
    edges = [GraphEdge(**{"from": lk.from_, "to": lk.to, "type": lk.type}) for lk in sg.links]
    # The request node may not be mirrored into the graph yet, and the investigation writes ABOUT links
    # later; add both so every path can be drawn from the request.
    node_ids = {n.id for n in nodes}
    if findings.requestId not in node_ids:
        nodes = [GraphNodeBrief(id=findings.requestId, type="Request", label="Request"), *nodes][:MAX_GRAPH_NODES]
        node_ids = {n.id for n in nodes}
        edges = [e for e in edges if e.from_ in node_ids and e.to in node_ids]
    present = {(e.from_, e.to) for e in edges}
    for s in findings.seeds:
        if (findings.requestId, s.id) not in present and findings.requestId in node_ids and s.id in node_ids:
            edges.append(GraphEdge(**{"from": findings.requestId, "to": s.id, "type": "ABOUT"}))
    return FindingsGraph(nodes=nodes, edges=edges)
