"""Explicit references (spec A, A12.2): patterns, stored kinds, resolution, pending references,
PR <-> Linear `IMPLEMENTED_BY`, and link tombstones when a reference is edited out (A12.4a).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow
from actron.linking.common import (
    TextNode,
    default_repo,
    excerpt,
    is_version,
    label_of,
    load_texts,
    now_iso,
)
from actron.logging import get_logger

log = get_logger(__name__)

# Pattern name -> stored Reference.kind (core.json values only).
STORED_KIND = {
    "linear_issue": "linear_issue",
    "linear_url": "linear_issue",
    "github_pr_or_issue": "github_pr",
    "github_url": "github_pr",
    "commit": "commit",
    "file": "file",
    "symbol": "symbol",
    "slack_permalink": "slack_message",
    "branch": "linear_issue",
}
# Reference kinds re-checked after a run of each source (resolve_pending).
KINDS_BY_SOURCE: dict[str, tuple[str, ...]] = {
    "linear": ("linear_issue",),
    "github": ("github_pr", "github_issue", "commit"),
    "code": ("commit", "file", "symbol"),
    "git": ("commit",),
    "slack": ("slack_message",),
}
# Prefixes that look like ticket keys but are standards or encodings (A12.2 false positives).
NOT_TEAM_KEYS = frozenset(
    {
        "HTTP",
        "HTTPS",
        "UTF",
        "ISO",
        "SHA",
        "RFC",
        "TLS",
        "SSL",
        "MD",
        "AES",
        "RSA",
        "UTC",
        "GMT",
        "CVE",
        "PEP",
        "ES",
        "ECMA",
        "IEEE",
        "ASCII",
        "WCAG",
        "TCP",
        "UDP",
        "IP",
        "IPV",
        "SMTP",
        "HTML",
        "CSS",
        "JSON",
        "UUID",
        "COVID",
        "LTS",
        "ARM",
        "X",
        "Y",
        "Z",
        "JDK",
        "JSR",
        "CP",
        "WIN",
        "GPL",
        "AGPL",
        "LGPL",
        "BSD",
        "MIT",
        "CC",
        "EPL",
        "MPL",
        "VS",
        "NODE",
        "PY",
        "V",
    }
)
SYMBOL_STOPWORDS = frozenset(
    {
        "true",
        "false",
        "null",
        "nil",
        "none",
        "undefined",
        "self",
        "this",
        "async",
        "await",
        "return",
        "const",
        "let",
        "var",
        "def",
        "defn",
        "npm",
        "yarn",
        "git",
        "main",
        "master",
        "dev",
        "todo",
    }
)

LINEAR_URL = re.compile(r"https://linear\.app/[^/\s]+/issue/([A-Z][A-Z0-9]+-\d+)[^\s)>\]]*")
GITHUB_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/(pull|issues)/(\d+)[^\s)>\]]*")
COMMIT_URL = re.compile(
    r"https://github\.com/([\w.-]+)/([\w.-]+)/commit/([0-9a-f]{7,40})\b[^\s)>\]]*"
)
SLACK_PERMALINK = re.compile(
    r"https://[\w-]+\.slack\.com/archives/(C\w+)/p(\d{10})(\d{6})[^\s)>\]]*"
)
ANY_URL = re.compile(r"https?://[^\s)>\]]+")
LINEAR_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b")
REPO_ISSUE = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d{1,7})\b")
BARE_ISSUE = re.compile(r"(?<![\w/&#])#(\d{1,7})\b")
COMMIT_WORD = re.compile(r"(?i)\bcommits?\b\s*[:#]?\s*`?([0-9a-f]{7,40})\b")
FENCED = re.compile(r"```.*?(?:```|\Z)", re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
FILE_TOKEN = re.compile(r"(?<![\w/.:@-])((?:[\w.@-]+/)+[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,7})(?![\w/])")
SYMBOL_BODY = re.compile(r"^[A-Za-z_$][\w$!?*-]*(?:[./][A-Za-z_$][\w$!?*-]*)*(?:\(\))?$")
CALL_TOKEN = re.compile(r"(?<![\w.$`])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\(\)")
HEX = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class RefMatch:
    pattern: str
    kind: str
    key: str
    raw: str
    start: int
    end: int


@dataclass(frozen=True)
class RefContext:
    repo: str | None = None
    team_keys: frozenset[str] = frozenset()


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < e and s < end for s, e in spans)


def _mask(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def is_team_key(prefix: str, team_keys: frozenset[str]) -> bool:
    if team_keys:
        return prefix in team_keys
    return prefix not in NOT_TEAM_KEYS


def find_references(text: str, ctx: RefContext | None = None) -> list[RefMatch]:
    """All explicit references in `text` (A12.2), in text order, without overlaps."""
    ctx = ctx or RefContext()
    out: list[RefMatch] = []
    taken: list[tuple[int, int]] = []

    def add(
        pattern: str, key: str, m: re.Match[str], group: int = 0, kind: str | None = None
    ) -> None:
        start, end = m.start(group), m.end(group)
        if _overlaps(taken, start, end):
            return
        out.append(RefMatch(pattern, kind or STORED_KIND[pattern], key, m.group(group), start, end))
        taken.append((start, end))

    for m in LINEAR_URL.finditer(text):
        add("linear_url", m.group(1), m)
    for m in GITHUB_URL.finditer(text):
        repo = f"{m.group(1)}/{m.group(2)}".lower()
        add(
            "github_url",
            f"{repo}#{m.group(4)}",
            m,
            kind="github_pr" if m.group(3) == "pull" else "github_issue",
        )
    for m in COMMIT_URL.finditer(text):
        add("commit", m.group(3).lower(), m)
    for m in SLACK_PERMALINK.finditer(text):
        add("slack_permalink", f"{m.group(1)}:{m.group(2)}.{m.group(3)}", m)
    urls = _mask(text, ANY_URL)  # other URLs hide the paths and keys inside them
    taken.extend(urls)

    fenced = _mask(text, FENCED)
    inline = [(m.start(), m.end()) for m in INLINE_CODE.finditer(text)]

    for m in LINEAR_KEY.finditer(text):
        if is_team_key(m.group(1), ctx.team_keys) and not _overlaps(fenced, m.start(), m.end()):
            add("linear_issue", f"{m.group(1)}-{int(m.group(2))}", m)
    for m in REPO_ISSUE.finditer(text):
        if not _overlaps(fenced, m.start(), m.end()) and "/" in m.group(1):
            add("github_pr_or_issue", f"{m.group(1).lower()}#{int(m.group(2))}", m)
    if ctx.repo:
        for m in BARE_ISSUE.finditer(text):
            if not _overlaps(fenced + inline, m.start(), m.end()):
                add("github_pr_or_issue", f"{ctx.repo}#{int(m.group(1))}", m)

    for m in COMMIT_WORD.finditer(text):
        add("commit", m.group(1).lower(), m, group=1)
    for m in INLINE_CODE.finditer(text):
        token = m.group(1).strip()
        if HEX.match(token):
            add("commit", token, m, group=1)
    for m in FILE_TOKEN.finditer(text):
        if not _overlaps(fenced, m.start(), m.end()):
            add("file", m.group(1).lstrip("./"), m, group=1)
    for m in INLINE_CODE.finditer(text):
        token = m.group(1).strip()
        if SYMBOL_BODY.match(token) and not HEX.match(token):
            name = token.removesuffix("()")
            if (
                len(name) >= 3
                and name.lower() not in SYMBOL_STOPWORDS
                and not _looks_like_file(name)
            ):
                add("symbol", name, m, group=1)
    for m in CALL_TOKEN.finditer(text):
        name = m.group(1)
        if (
            len(name) >= 3
            and name.lower() not in SYMBOL_STOPWORDS
            and not _overlaps(fenced, m.start(), m.end())
        ):
            add("symbol", name, m, group=1)
    out.sort(key=lambda r: r.start)
    return out


def _looks_like_file(token: str) -> bool:
    return "/" in token and re.search(r"\.[A-Za-z][A-Za-z0-9]{0,7}$", token) is not None


def branch_keys(head_ref: str, team_keys: frozenset[str]) -> list[str]:
    """Linear keys inside a PR branch name (`eng-12-fix-paste` -> `ENG-12`)."""
    keys: list[str] = []
    for m in re.finditer(
        r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,6})(?![0-9])", head_ref
    ):
        prefix = m.group(1).upper()
        if team_keys and prefix not in team_keys:
            continue
        if not team_keys:
            continue  # without known team keys a branch word like `feature-12` is too ambiguous
        key = f"{prefix}-{int(m.group(2))}"
        if key not in keys:
            keys.append(key)
    return keys


# Graph side


@dataclass
class RefReport:
    texts: int = 0
    references: int = 0
    resolved: int = 0
    pending: int = 0
    ambiguous: int = 0
    mentions: int = 0
    implemented_by: int = 0
    tombstoned: int = 0
    resolved_ids: list[str] = field(default_factory=list)

    def add(self, other: RefReport) -> None:
        for name in (
            "texts",
            "references",
            "resolved",
            "pending",
            "ambiguous",
            "mentions",
            "implemented_by",
            "tombstoned",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.resolved_ids.extend(other.resolved_ids)


def team_keys(store: GraphStore) -> frozenset[str]:
    rows = store.query(
        "MATCH (t:LinearTeam) WHERE t.key IS NOT NULL RETURN t.key AS k", read_only=True
    )
    return frozenset(str(r["k"]).upper() for r in rows)


def _targets(store: GraphStore, kind: str, key: str) -> list[tuple[str, str]]:
    """(label, id) of the nodes a reference points at; several means ambiguous."""
    if kind == "linear_issue":
        rows = store.query(
            "MATCH (i:LinearIssue {identifier: $k}) WHERE NOT i.id CONTAINS '@v' "
            "AND coalesce(i.deleted, false) = false RETURN i.id AS id",
            {"k": key},
            read_only=True,
        )
        return [("LinearIssue", str(r["id"])) for r in rows]
    if kind in ("github_pr", "github_issue"):
        repo, _, number = key.partition("#")
        found: list[tuple[str, str]] = []
        for label, nid in (
            ("GithubPullRequest", ids.github_pr(repo, int(number))),
            ("GithubIssue", ids.github_issue(repo, int(number))),
        ):
            if store.query(
                f"MATCH (n:`{label}` {{id: $id}}) RETURN n.id AS id", {"id": nid}, read_only=True
            ):
                found.append((label, nid))
        return found[:1]  # a number is either a PR or an issue
    if kind == "commit":
        rows = store.query(
            "MATCH (c:GitCommit) WHERE c.sha STARTS WITH $p RETURN c.id AS id LIMIT 5",
            {"p": key},
            read_only=True,
        )
        return [("GitCommit", str(r["id"])) for r in rows]
    if kind == "file":
        rows = store.query(
            "MATCH (f:CodeFile) WHERE (f.path = $s OR f.path ENDS WITH ('/' + $s)) "
            "AND coalesce(f.deleted, false) = false RETURN f.id AS id LIMIT 5",
            {"s": key},
            read_only=True,
        )
        return [("CodeFile", str(r["id"])) for r in rows]
    if kind == "symbol":
        return _symbol_targets(store, key)
    if kind == "slack_message":
        channel, _, ts = key.partition(":")
        rows = store.query(
            "MATCH (c:SlackChannel) WHERE c.id = $cid OR $ch IN coalesce(c.aliases, []) RETURN c.id AS id",
            {"cid": ids.slack_channel(channel), "ch": channel},
            read_only=True,
        )
        out: list[tuple[str, str]] = []
        for r in rows:
            real = str(r["id"]).removeprefix("slack:channel:")
            mid = ids.slack_msg(real, ts)
            if store.query(
                "MATCH (m:SlackMessage {id: $id}) RETURN m.id AS id", {"id": mid}, read_only=True
            ):
                out.append(("SlackMessage", mid))
        return out
    return []


def _symbol_targets(store: GraphStore, key: str) -> list[tuple[str, str]]:
    qual = key.replace("/", ".")
    short = re.split(r"[./]", key)[-1]
    for field_name, value in (("qualifiedName", qual), ("name", short)):
        found: list[tuple[str, str]] = []
        for label in ("CodeFunction", "CodeClass"):
            rows = store.query(
                f"MATCH (n:`{label}`) WHERE n.{field_name} = $v AND coalesce(n.deleted, false) = false "
                "RETURN n.id AS id LIMIT 5",
                {"v": value},
                read_only=True,
            )
            found.extend((label, str(r["id"])) for r in rows)
        if found:
            return found
    return []


def _upsert_reference(store: GraphStore, kind: str, key: str, raw: str, status: str) -> str:
    rid = ids.reference(kind, key)
    row: dict[str, Any] = {
        "id": rid,
        "kind": kind,
        "key": key,
        "rawText": raw[:300],
        "status": status,
    }
    if status != "pending":
        row["resolvedAt"] = now_iso()
    store.upsert_nodes("Reference", [row])
    return rid


def _final_kind(kind: str, targets: list[tuple[str, str]]) -> str:
    if kind == "github_pr" and targets and targets[0][0] == "GithubIssue":
        return "github_issue"
    return kind


def _link(store: GraphStore, rel: str, from_label: str, to_label: str, rows: list[LinkRow]) -> int:
    if not rows:
        return 0
    return store.upsert_links(rel, from_label, to_label, rows).created


def link_resolved(
    store: GraphStore,
    text: TextNode,
    rid: str,
    targets: list[tuple[str, str]],
    quote: str,
    *,
    from_attachment: bool = False,
) -> tuple[int, int]:
    """RESOLVES_TO each target; MENTIONS (and IMPLEMENTED_BY) only when unambiguous."""
    explicit = {"method": "explicit", "confidence": 1.0, "sourceRef": text.id, "deleted": False}
    for label, tid in targets:
        _link(store, "RESOLVES_TO", "Reference", label, [LinkRow(rid, tid, dict(explicit))])
    if len(targets) != 1:
        return 0, 0
    label, tid = targets[0]
    if tid == text.id:
        return 0, 0
    mentions = _link(
        store, "MENTIONS", text.label, label, [LinkRow(text.id, tid, {**explicit, "quote": quote})]
    )
    implemented = 0
    if text.label == "GithubPullRequest" and label == "LinearIssue":
        implemented = _link(
            store,
            "IMPLEMENTED_BY",
            "LinearIssue",
            "GithubPullRequest",
            [LinkRow(tid, text.id, {**explicit, "quote": quote})],
        )
    elif text.label == "LinearIssue" and label == "GithubPullRequest" and from_attachment:
        implemented = _link(
            store,
            "IMPLEMENTED_BY",
            "LinearIssue",
            "GithubPullRequest",
            [LinkRow(text.id, tid, {**explicit, "quote": quote})],
        )
    return mentions, implemented


def _current_explicit(store: GraphStore, text: TextNode) -> list[dict[str, Any]]:
    return store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[r]->(b) WHERE type(r) IN ['MENTIONS', 'CONTAINS_REFERENCE'] "
        "AND r.method = 'explicit' AND coalesce(r.deleted, false) = false "
        "RETURN type(r) AS rel, b.id AS id, labels(b)[0] AS label",
        {"id": text.id},
        read_only=True,
    )


def tombstone_outgoing(
    store: GraphStore,
    text: TextNode,
    keep: set[tuple[str, str]] | None = None,
    rels: Iterable[str] = ("MENTIONS", "CONTAINS_REFERENCE"),
    methods: Iterable[str] = ("explicit",),
) -> int:
    """Mark a text's outgoing links deleted (A12.4a) unless (rel, target id) is in `keep`."""
    rows = store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[r]->(b) WHERE type(r) IN $rels AND r.method IN $methods "
        "AND coalesce(r.deleted, false) = false RETURN type(r) AS rel, b.id AS id, labels(b)[0] AS label",
        {"id": text.id, "rels": list(rels), "methods": list(methods)},
        read_only=True,
    )
    done = 0
    for r in rows:
        if keep and (r["rel"], r["id"]) in keep:
            continue
        done += store.tombstone_links(
            str(r["rel"]), text.label, str(r["label"]), [(text.id, str(r["id"]))]
        )
    return done


def _context_repo(store: GraphStore, text: TextNode, fallback: str | None) -> str | None:
    if text.label in ("GithubPullRequest", "GithubIssue"):
        return ids.parse_id(text.id).parts.get("repo") or fallback
    queries = {
        "GithubReviewComment": "MATCH (t:GithubReviewComment {id: $id})-[:COMMENTS_ON_PR]->(x:GithubPullRequest)",
        "GithubReview": "MATCH (x:GithubPullRequest)-[:HAS_REVIEW]->(t:GithubReview {id: $id})",
        "GithubIssueComment": "MATCH (x)-[:PR_DISCUSSED_IN|ISSUE_DISCUSSED_IN]->(t:GithubIssueComment {id: $id})",
    }
    if text.label in queries:
        rows = store.query(
            queries[text.label] + " RETURN x.id AS id LIMIT 1", {"id": text.id}, read_only=True
        )
        for r in rows:
            parts = ids.parse_id(str(r["id"])).parts
            if parts.get("repo"):
                return parts["repo"]
    return fallback


def link_references(store: GraphStore, text_ids: list[str]) -> RefReport:
    """Find, store and resolve the explicit references of each text (A12.2, A12.4a)."""
    report = RefReport()
    keys = team_keys(store)
    repo = default_repo(store)
    for text in load_texts(store, text_ids):
        report.texts += 1
        if text.deleted:
            report.tombstoned += tombstone_outgoing(store, text)
            continue
        ctx = RefContext(repo=_context_repo(store, text, repo), team_keys=keys)
        matches = find_references(text.text, ctx)
        attachments = (
            [str(u) for u in text.props.get("attachmentUrls") or []]
            if text.label == "LinearIssue"
            else []
        )
        attach_matches = [m for u in attachments for m in find_references(u, ctx)]
        if text.label == "GithubPullRequest" and text.props.get("headRef"):
            matches += [
                RefMatch("branch", "linear_issue", k, str(text.props["headRef"]), 0, 0)
                for k in branch_keys(str(text.props["headRef"]), keys)
            ]
        keep: set[tuple[str, str]] = set()
        seen: set[tuple[str, str]] = set()
        for m, from_attachment in [(m, False) for m in matches] + [
            (m, True) for m in attach_matches
        ]:
            if (m.kind, m.key) in seen:
                continue
            seen.add((m.kind, m.key))
            if m.pattern == "branch" or from_attachment:
                quote = m.raw
            else:
                quote = excerpt(text.text, m.start, m.end)
            targets = _targets(store, m.kind, m.key)
            if m.kind in ("file", "symbol") and not targets:
                continue  # file and symbol references exist only when they match code (A12.2)
            if targets and targets[0][1] == text.id:
                continue
            status = (
                "pending" if not targets else ("resolved" if len(targets) == 1 else "ambiguous")
            )
            kind = _final_kind(m.kind, targets)
            rid = _upsert_reference(store, kind, m.key, m.raw, status)
            report.references += 1
            _link(
                store,
                "CONTAINS_REFERENCE",
                text.label,
                "Reference",
                [
                    LinkRow(
                        text.id,
                        rid,
                        {
                            "method": "explicit",
                            "confidence": 1.0,
                            "quote": quote,
                            "sourceRef": text.id,
                            "deleted": False,
                        },
                    )
                ],
            )
            keep.add(("CONTAINS_REFERENCE", rid))
            if status == "pending":
                report.pending += 1
                continue
            if status == "ambiguous":
                report.ambiguous += 1
            else:
                report.resolved += 1
                keep.add(("MENTIONS", targets[0][1]))
            mentions, impl = link_resolved(
                store, text, rid, targets, quote, from_attachment=from_attachment
            )
            report.mentions += mentions
            report.implemented_by += impl
        report.tombstoned += tombstone_outgoing(store, text, keep)
    return report


def link_pr_branches(
    store: GraphStore, *, pr_ids: list[str] | None = None, issue_ids: list[str] | None = None
) -> int:
    """IMPLEMENTED_BY when a PR's `headRef` equals a Linear issue's `branchName` (A12.2, A-AC-73)."""
    props = {"method": "explicit", "confidence": 1.0, "deleted": False}
    if pr_ids is not None:
        rows = store.query(
            "UNWIND $ids AS pid MATCH (p:GithubPullRequest {id: pid}) WHERE p.headRef IS NOT NULL "
            "MATCH (i:LinearIssue) WHERE i.branchName = p.headRef AND NOT i.id CONTAINS '@v' "
            "RETURN i.id AS i, p.id AS p, p.headRef AS ref",
            {"ids": pr_ids},
            read_only=True,
        )
    elif issue_ids is not None:
        rows = store.query(
            "UNWIND $ids AS iid MATCH (i:LinearIssue {id: iid}) WHERE i.branchName IS NOT NULL "
            "MATCH (p:GithubPullRequest) WHERE p.headRef = i.branchName "
            "RETURN i.id AS i, p.id AS p, p.headRef AS ref",
            {"ids": issue_ids},
            read_only=True,
        )
    else:
        rows = store.query(
            "MATCH (i:LinearIssue), (p:GithubPullRequest) WHERE i.branchName IS NOT NULL "
            "AND p.headRef = i.branchName AND NOT i.id CONTAINS '@v' RETURN i.id AS i, p.id AS p, p.headRef AS ref",
            read_only=True,
        )
    link_rows = [
        LinkRow(
            str(r["i"]), str(r["p"]), {**props, "quote": str(r["ref"]), "sourceRef": str(r["p"])}
        )
        for r in rows
    ]
    return _link(store, "IMPLEMENTED_BY", "LinearIssue", "GithubPullRequest", link_rows)


def resolve_pending(store: GraphStore, source: str | None = None) -> RefReport:
    """Resolve pending references whose kind matches `source` (all kinds when None) (A12.2, A-AC-72)."""
    report = RefReport()
    kinds = (
        list(KINDS_BY_SOURCE.get(source, ()))
        if source
        else sorted({k for v in KINDS_BY_SOURCE.values() for k in v})
    )
    if source == "github":
        kinds.append("github_issue")
    rows = store.query(
        "MATCH (r:Reference) WHERE r.status = 'pending' AND r.kind IN $kinds RETURN r.id AS id, r.kind AS kind, "
        "r.key AS key LIMIT 5000",
        {"kinds": kinds},
        read_only=True,
    )
    for row in rows:
        rid, kind, key = str(row["id"]), str(row["kind"]), str(row["key"])
        targets = _targets(store, kind, key)
        if not targets:
            continue
        status = "resolved" if len(targets) == 1 else "ambiguous"
        store.update_nodes("Reference", [{"id": rid, "status": status, "resolvedAt": now_iso()}])
        if status == "resolved":
            report.resolved += 1
            report.resolved_ids.append(rid)
        else:
            report.ambiguous += 1
        sources = store.query(
            "MATCH (t)-[c:CONTAINS_REFERENCE]->(r:Reference {id: $id}) WHERE coalesce(c.deleted, false) = false "
            "RETURN t.id AS id, c.quote AS quote",
            {"id": rid},
            read_only=True,
        )
        texts = {
            t.id: t
            for t in load_texts(store, [str(s["id"]) for s in sources], include_deleted=False)
        }
        if not sources:
            for label, tid in targets:
                _link(
                    store,
                    "RESOLVES_TO",
                    "Reference",
                    label,
                    [LinkRow(rid, tid, {"method": "explicit", "confidence": 1.0})],
                )
        for s in sources:
            text = texts.get(str(s["id"]))
            if text is None:
                continue
            mentions, impl = link_resolved(store, text, rid, targets, str(s.get("quote") or key))
            report.mentions += mentions
            report.implemented_by += impl
    if source in (None, "linear", "github"):
        report.implemented_by += link_pr_branches(store)
        report.implemented_by += _resolve_branch_keys(store)
    return report


def _resolve_branch_keys(store: GraphStore) -> int:
    """PRs whose branch contains a Linear key, once the Linear team keys are known (A-AC-73)."""
    keys = team_keys(store)
    if not keys:
        return 0
    prs = store.query(
        "MATCH (p:GithubPullRequest) WHERE p.headRef IS NOT NULL "
        "OPTIONAL MATCH (i:LinearIssue)-[:IMPLEMENTED_BY]->(p) WITH p, count(i) AS c WHERE c = 0 "
        "RETURN p.id AS id, p.headRef AS ref LIMIT 5000",
        read_only=True,
    )
    made = 0
    for p in prs:
        for key in branch_keys(str(p["ref"]), keys):
            targets = _targets(store, "linear_issue", key)
            if len(targets) == 1:
                made += _link(
                    store,
                    "IMPLEMENTED_BY",
                    "LinearIssue",
                    "GithubPullRequest",
                    [
                        LinkRow(
                            targets[0][1],
                            str(p["id"]),
                            {
                                "method": "explicit",
                                "confidence": 1.0,
                                "quote": str(p["ref"]),
                                "sourceRef": str(p["id"]),
                            },
                        )
                    ],
                )
    return made


def text_ids_for_source(changed_ids: list[str]) -> list[str]:
    """Changed ids that are texts (A12 input), skipping previous-version nodes and duplicates."""
    from actron.linking.common import TEXT_LABELS

    seen: set[str] = set()
    out = []
    for i in changed_ids:
        if i not in seen and label_of(i) in TEXT_LABELS and not is_version(i):
            seen.add(i)
            out.append(i)
    return out
