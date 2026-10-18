"""Knowledge and ownership (spec A, A12.6, bonus).

KNOWS_ABOUT.score per (Person, function or file) = 1 - exp(-(0.4*commits + 0.3*blameShare*10 + 0.2*reviews
+ 0.1*messages) / 5), signals over the last 365 days; the top 10 people per node with score >= 0.2 are kept.
OWNS comes from CODEOWNERS (basis `codeowners`) and from a blame share >= 0.5 (basis `blame`).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from actron.graph.store import GraphStore, LinkRow

WINDOW_DAYS = 365
MIN_SCORE = 0.2
TOP_PEOPLE = 10
OWN_SHARE = 0.5
SIGNALS = ("commits", "blame", "reviews", "messages")

# (person, target label, target id) -> signal counts
Signals = dict[tuple[str, str, str], dict[str, float]]


@dataclass
class KnowledgeReport:
    knows_about: int = 0
    removed: int = 0
    owns: int = 0
    codeowner_links: int = 0


def score(commits: float, blame_share: float, reviews: float, messages: float) -> float:
    raw = 0.4 * commits + 0.3 * blame_share * 10 + 0.2 * reviews + 0.1 * messages
    return 1.0 - math.exp(-raw / 5.0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _add(
    signals: Signals, rows: list[dict[str, Any]], name: str, value_key: str | None = None
) -> None:
    for r in rows:
        key = (str(r["person"]), str(r["label"]), str(r["target"]))
        bucket = signals.setdefault(key, dict.fromkeys(SIGNALS, 0.0))
        bucket[name] += float(r[value_key]) if value_key else float(r.get("n") or 1)


def collect_signals(store: GraphStore, now: datetime | None = None) -> Signals:
    since = _iso((now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS))
    signals: Signals = {}
    git_person = "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_GIT_AUTHOR]->(a:GitAuthor)"
    gh_person = "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_GITHUB_USER]->(u:GithubUser)"
    _add(
        signals,
        store.query(
            git_person + "<-[:AUTHORED_BY]-(c:GitCommit)-[:TOUCHED]->(f:CodeFunction) "
            "WHERE coalesce(c.authoredAt, $since) >= $since AND coalesce(f.deleted, false) = false "
            "RETURN p.id AS person, 'CodeFunction' AS label, f.id AS target, count(DISTINCT c) AS n",
            {"since": since},
            read_only=True,
        ),
        "commits",
    )
    _add(
        signals,
        store.query(
            git_person
            + "<-[:AUTHORED_BY]-(c:GitCommit)-[:HAS_FILE_CHANGE]->(:GitFileChange)-[:CHANGE_OF_FILE]->"
            "(f:CodeFile) WHERE coalesce(c.authoredAt, $since) >= $since AND coalesce(f.deleted, false) = false "
            "RETURN p.id AS person, 'CodeFile' AS label, f.id AS target, count(DISTINCT c) AS n",
            {"since": since},
            read_only=True,
        ),
        "commits",
    )
    _add(
        signals,
        store.query(
            git_person
            + "-[b:BLAME_OWNS]->(f:CodeFunction) WHERE coalesce(f.deleted, false) = false "
            "RETURN p.id AS person, 'CodeFunction' AS label, f.id AS target, sum(b.lineShare) AS s",
            read_only=True,
        ),
        "blame",
        "s",
    )
    _add(
        signals,
        store.query(
            git_person
            + "-[b:BLAME_OWNS_FILE]->(f:CodeFile) WHERE coalesce(f.deleted, false) = false "
            "RETURN p.id AS person, 'CodeFile' AS label, f.id AS target, sum(b.lineShare) AS s",
            read_only=True,
        ),
        "blame",
        "s",
    )
    _add(
        signals,
        store.query(
            gh_person
            + "<-[:REVIEWED_BY]-(r:GithubReview)<-[:HAS_REVIEW]-(:GithubPullRequest)-[:PR_TOUCHED]->"
            "(f:CodeFunction) WHERE coalesce(r.submittedAt, $since) >= $since "
            "RETURN p.id AS person, 'CodeFunction' AS label, f.id AS target, count(DISTINCT r) AS n",
            {"since": since},
            read_only=True,
        ),
        "reviews",
    )
    _add(
        signals,
        store.query(
            gh_person
            + "<-[:REVIEWED_BY]-(r:GithubReview)<-[:HAS_REVIEW]-(:GithubPullRequest)-[:CHANGES_FILE]->"
            "(:GithubPullRequestFile)-[:PR_FILE_IS]->(f:CodeFile) WHERE coalesce(r.submittedAt, $since) >= $since "
            "RETURN p.id AS person, 'CodeFile' AS label, f.id AS target, count(DISTINCT r) AS n",
            {"since": since},
            read_only=True,
        ),
        "reviews",
    )
    for label in ("CodeFunction", "CodeFile"):
        _add(
            signals,
            store.query(
                "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_SLACK_USER]->(:SlackUser)<-[:POSTED_BY]-"
                f"(m:SlackMessage)-[k:MENTIONS]->(f:{label}) WHERE coalesce(k.deleted, false) = false "
                "AND coalesce(m.postedAt, $since) >= $since "
                f"RETURN p.id AS person, '{label}' AS label, f.id AS target, count(DISTINCT m) AS n",
                {"since": since},
                read_only=True,
            ),
            "messages",
        )
        _add(
            signals,
            store.query(
                "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_LINEAR_USER]->(:LinearUser)<-[:CREATED_BY]-"
                f"(m:LinearComment)-[k:MENTIONS]->(f:{label}) WHERE coalesce(k.deleted, false) = false "
                "AND coalesce(m.createdAt, $since) >= $since "
                f"RETURN p.id AS person, '{label}' AS label, f.id AS target, count(DISTINCT m) AS n",
                {"since": since},
                read_only=True,
            ),
            "messages",
        )
        _add(
            signals,
            store.query(
                gh_person + "<-[:REVIEW_COMMENT_BY]-(m:GithubReviewComment)-[k:MENTIONS]->"
                f"(f:{label}) WHERE coalesce(k.deleted, false) = false AND coalesce(m.createdAt, $since) >= $since "
                f"RETURN p.id AS person, '{label}' AS label, f.id AS target, count(DISTINCT m) AS n",
                {"since": since},
                read_only=True,
            ),
            "messages",
        )
    return signals


def compute_knows_about(store: GraphStore, now: datetime | None = None) -> KnowledgeReport:
    report = KnowledgeReport()
    signals = collect_signals(store, now)
    per_target: dict[tuple[str, str], list[tuple[float, str, dict[str, float]]]] = defaultdict(list)
    for (person, label, target), s in signals.items():
        value = score(s["commits"], s["blame"], s["reviews"], s["messages"])
        if value >= MIN_SCORE:
            per_target[(label, target)].append((value, person, s))
    for (label, target), people in per_target.items():
        people.sort(key=lambda x: (-x[0], x[1]))
        keep = people[:TOP_PEOPLE]
        rows = [
            LinkRow(
                person,
                target,
                {
                    "method": "inferred",
                    "confidence": round(value, 4),
                    "score": round(value, 4),
                    "signals": json.dumps({k: round(v, 4) for k, v in s.items()}, sort_keys=True),
                },
            )
            for value, person, s in keep
        ]
        report.knows_about += store.upsert_links("KNOWS_ABOUT", "Person", label, rows).created
        stale = store.query(
            f"MATCH (p:Person)-[r:KNOWS_ABOUT]->(t:`{label}` {{id: $t}}) WHERE NOT p.id IN $keep RETURN p.id AS p",
            {"t": target, "keep": [p for _, p, _ in keep]},
            read_only=True,
        )
        if stale:
            report.removed += store.delete_links(
                "KNOWS_ABOUT", "Person", label, [(str(r["p"]), target) for r in stale]
            )
    return report


def _resolve_owner(store: GraphStore, owner: str) -> str | None:
    owner = owner.strip()
    if owner.startswith("@") and "/" not in owner:
        rows = store.query(
            "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_GITHUB_USER]->(u:GithubUser) "
            "WHERE toLower(u.login) = toLower($login) RETURN p.id AS id LIMIT 1",
            {"login": owner[1:]},
            read_only=True,
        )
    elif "@" in owner and not owner.startswith("@"):
        rows = store.query(
            "MATCH (p:Person)-[:HAS_IDENTITY]->(i:Identity) WHERE i.email = $e RETURN p.id AS id LIMIT 1",
            {"e": owner.lower()},
            read_only=True,
        )
    else:
        return None  # teams (@org/team) are not people
    return str(rows[0]["id"]) if rows else None


def compute_owns(store: GraphStore) -> KnowledgeReport:
    report = KnowledgeReport()
    owns: dict[tuple[str, str, str], tuple[set[str], float]] = {}
    rules = store.query(
        "MATCH (f:CodeFile)-[:MATCHES_OWNER_RULE]->(r:CodeOwnerRule) WHERE coalesce(f.deleted, false) = false "
        "RETURN f.id AS file, r.id AS rule, r.owners AS owners",
        read_only=True,
    )
    rule_people: dict[str, set[str]] = defaultdict(set)
    for r in rules:
        for owner in r["owners"] or []:
            person = _resolve_owner(store, str(owner))
            if person:
                rule_people[str(r["rule"])].add(person)
                key = (person, "CodeFile", str(r["file"]))
                bases, conf = owns.get(key, (set(), 1.0))
                owns[key] = (bases | {"codeowners"}, max(conf, 1.0))
    for rule, people in rule_people.items():
        report.codeowner_links += store.upsert_links(
            "CODEOWNER_IS",
            "CodeOwnerRule",
            "Person",
            [LinkRow(rule, p, {"method": "structural", "confidence": 1.0}) for p in sorted(people)],
        ).created
    for rel, label in (("BLAME_OWNS", "CodeFunction"), ("BLAME_OWNS_FILE", "CodeFile")):
        rows = store.query(
            "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:IS_GIT_AUTHOR]->(:GitAuthor)-"
            f"[b:{rel}]->(t:{label}) WHERE coalesce(t.deleted, false) = false "
            "RETURN p.id AS person, t.id AS target, sum(b.lineShare) AS share",
            read_only=True,
        )
        for r in rows:
            share = float(r["share"] or 0.0)
            if share >= OWN_SHARE:
                key = (str(r["person"]), label, str(r["target"]))
                bases, conf = owns.get(key, (set(), 0.0))
                owns[key] = (bases | {"blame"}, max(conf, min(share, 1.0)))
    by_label: dict[str, list[LinkRow]] = defaultdict(list)
    for (person, label, target), (bases, conf) in sorted(owns.items()):
        method = "structural" if "codeowners" in bases else "inferred"
        by_label[label].append(
            LinkRow(
                person,
                target,
                {"method": method, "confidence": round(conf, 4), "basis": ",".join(sorted(bases))},
            )
        )
    for label, link_rows in by_label.items():
        report.owns += store.upsert_links("OWNS", "Person", label, link_rows).created
    return report


def compute_knowledge(store: GraphStore, now: datetime | None = None) -> KnowledgeReport:
    k = compute_knows_about(store, now)
    o = compute_owns(store)
    return KnowledgeReport(
        knows_about=k.knows_about, removed=k.removed, owns=o.owns, codeowner_links=o.codeowner_links
    )
