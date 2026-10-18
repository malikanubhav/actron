"""Decisions (spec A, A12.4 and A12.4a).

Texts classified `decision` or `proposal` (J1 >= 0.5) go to LLM extraction with an exact quote. A decision is
`approved` only with explicit evidence: the text itself settles it (J1 `decision` >= 0.7 and the extraction says
"decided"), or a reply approves it (J2 >= 0.85, then `APPROVED_IN` and `DECIDED_BY`). Otherwise `proposed`.
Bot messages never yield decisions. Supersession can be partial: only the `CONSTRAINS` links inside the new
decision's scope are deactivated. Deleted or edited sources tombstone the links that no longer hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from actron import models
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow
from actron.linking.classify import Classification
from actron.linking.common import (
    CONSTRAINABLE,
    CreatedLink,
    TextNode,
    author_account,
    is_bot_message,
    load_texts,
    now_iso,
    person_of,
    time_of,
)
from actron.linking.references import tombstone_outgoing
from actron.logging import get_logger

log = get_logger(__name__)

DECISION_KINDS = frozenset({"decision", "proposal"})
MIN_KIND_PROBABILITY = 0.5
EXPLICIT_DECISION_PROBABILITY = 0.7
APPROVAL_THRESHOLD = 0.85
SUPERSEDE_THRESHOLD = 0.7
ALL_METHODS = ("explicit", "structural", "extracted", "inferred", "confirmed")


@dataclass
class DecisionReport:
    texts: int = 0
    extracted: int = 0
    dropped: int = 0
    approved: int = 0
    proposed: int = 0
    superseded: int = 0
    bot_skipped: int = 0
    tombstoned: int = 0
    implemented: int = 0
    decision_ids: list[str] = field(default_factory=list)
    links: list[CreatedLink] = field(default_factory=list)


def tombstone_text_links(store: GraphStore, text: TextNode) -> int:
    """A12.4a: a deleted text's outgoing links and the decision/feature links into it are tombstoned."""
    done = tombstone_outgoing(
        store, text, rels=("MENTIONS", "CONTAINS_REFERENCE"), methods=ALL_METHODS
    )
    rows = store.query(
        f"MATCH (a)-[r]->(t:`{text.label}` {{id: $id}}) WHERE type(r) IN ['EXTRACTED_FROM', 'APPROVED_IN', "
        "'DISCUSSED_IN'] AND coalesce(r.deleted, false) = false RETURN type(r) AS rel, a.id AS a, labels(a)[0] AS l",
        {"id": text.id},
        read_only=True,
    )
    for r in rows:
        done += store.tombstone_links(
            str(r["rel"]), str(r["l"]), text.label, [(str(r["a"]), text.id)]
        )
    return done


def _replies(store: GraphStore, text: TextNode) -> list[TextNode]:
    queries = {
        "SlackMessage": "MATCH (r:SlackMessage)-[:THREAD_OF]->(:SlackMessage {id: $id}) RETURN r.id AS id",
        "GithubReviewComment": "MATCH (r:GithubReviewComment)-[:REPLIES_TO]->(:GithubReviewComment {id: $id}) "
        "RETURN r.id AS id",
        "LinearIssue": "MATCH (:LinearIssue {id: $id})-[:HAS_COMMENT]->(r:LinearComment) RETURN r.id AS id",
        "GithubPullRequest": "MATCH (:GithubPullRequest {id: $id})-[:PR_DISCUSSED_IN]->(r:GithubIssueComment) "
        "RETURN r.id AS id",
        "GithubIssue": "MATCH (:GithubIssue {id: $id})-[:ISSUE_DISCUSSED_IN]->(r:GithubIssueComment) RETURN r.id AS id",
    }
    cypher = queries.get(text.label)
    if not cypher:
        return []
    reply_ids = [
        str(r["id"]) for r in store.query(cypher + " LIMIT 50", {"id": text.id}, read_only=True)
    ]
    return [t for t in load_texts(store, reply_ids, include_deleted=False) if t.text.strip()]


def _mentions(store: GraphStore, text: TextNode, keep_at: float) -> list[dict[str, Any]]:
    rows = store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[m:MENTIONS]->(x) WHERE coalesce(m.deleted, false) = false "
        "RETURN x.id AS id, labels(x)[0] AS label, m.method AS method, m.confidence AS confidence, "
        "coalesce(x.qualifiedName, x.name, x.path, x.title, x.id) AS name",
        {"id": text.id},
        read_only=True,
    )
    return [r for r in rows if r["method"] == "explicit" or float(r["confidence"] or 0) >= keep_at]


async def link_decisions(
    store: GraphStore,
    text_ids: list[str],
    classes: dict[str, Classification],
    *,
    ws: str | None = None,
    bot_user_ids: set[str] | None = None,
    keep_at: float = 0.6,
) -> DecisionReport:
    report = DecisionReport()
    for text in load_texts(store, text_ids):
        if text.deleted:
            report.tombstoned += tombstone_text_links(store, text)
            continue
        c = classes.get(text.id)
        if c is None or c.kind not in DECISION_KINDS or c.probability < MIN_KIND_PROBABILITY:
            continue
        report.texts += 1
        if is_bot_message(text, bot_user_ids):
            report.bot_skipped += 1
            continue
        did = ids.decision(text.id)
        existing = store.get_node(did)
        extraction = await models.extract_decision(text.text, ws=ws)
        if extraction is None:
            report.dropped += 1
            if existing:  # the edited text no longer states the decision
                report.tombstoned += store.tombstone_links(
                    "EXTRACTED_FROM", "Decision", text.label, [(did, text.id)]
                )
            continue
        report.extracted += 1
        await _write_decision(store, text, c, extraction, existing, report, ws=ws, keep_at=keep_at)
    return report


async def _write_decision(
    store: GraphStore,
    text: TextNode,
    c: Classification,
    ex: models.DecisionExtraction,
    existing: dict[str, Any] | None,
    report: DecisionReport,
    *,
    ws: str | None,
    keep_at: float,
) -> None:
    did = ids.decision(text.id)
    author = author_account(store, text)
    explicit = (
        c.kind == "decision"
        and c.probability >= EXPLICIT_DECISION_PROBABILITY
        and ex.status_hint == "decided"
    )
    approver: tuple[TextNode, float, str] | None = None
    if not explicit:
        for reply in _replies(store, text):
            reply_author = author_account(store, reply)
            same = reply_author is not None and reply_author == author
            j = await models.is_approval(ex.statement, reply.text[:4000], same, ws=ws)
            if (j.probability or 0.0) >= APPROVAL_THRESHOLD and not same:
                approver = (reply, float(j.probability or 0.0), j.model)
                break
    status = "approved" if (explicit or approver) else "proposed"
    if existing and existing.get("status") in ("superseded", "rejected"):
        status = str(existing["status"])
    history = list(existing.get("statementHistory") or []) if existing else []
    if existing and existing.get("statement") and existing["statement"] != ex.statement:
        history.append(str(existing["statement"]))
    evidence = None
    if explicit:
        evidence = "The source text states the decision as settled."
    elif approver:
        evidence = f'Approved in a reply: "{approver[0].text[:200]}"'
    store.upsert_nodes(
        "Decision",
        [
            {
                "id": did,
                "statement": ex.statement,
                "status": status,
                "quote": ex.quote,
                "quoteSpan": list(ex.quote_span),
                "decidedAt": time_of(text),
                "approvalEvidence": evidence,
                "confidence": round(c.probability, 4),
                "extractedBy": ex.model,
                "scope": ex.scope or None,
                "statementHistory": history or None,
            }
        ],
    )
    report.decision_ids.append(did)
    report.approved += status == "approved"
    report.proposed += status == "proposed"
    store.upsert_links(
        "EXTRACTED_FROM",
        "Decision",
        text.label,
        [
            LinkRow(
                did,
                text.id,
                {
                    "method": "extracted",
                    "confidence": round(c.probability, 4),
                    "quote": ex.quote,
                    "quoteSpan": list(ex.quote_span),
                    "model": ex.model,
                    "sourceRef": text.id,
                    "deleted": False,
                },
            )
        ],
    )
    report.links.append(
        CreatedLink(
            "EXTRACTED_FROM",
            "Decision",
            did,
            text.label,
            text.id,
            ex.quote,
            f"This text states the decision: {ex.statement}",
            "extracted",
        )
    )
    if explicit:
        person = person_of(store, author)
        if person:
            store.upsert_links(
                "DECIDED_BY",
                "Decision",
                "Person",
                [
                    LinkRow(
                        did,
                        person,
                        {
                            "method": "extracted",
                            "confidence": round(c.probability, 4),
                            "model": ex.model,
                            "sourceRef": text.id,
                        },
                    )
                ],
            )
    if approver:
        reply, p, model = approver
        store.upsert_links(
            "APPROVED_IN",
            "Decision",
            reply.label,
            [
                LinkRow(
                    did,
                    reply.id,
                    {
                        "method": "inferred",
                        "confidence": round(p, 4),
                        "model": model,
                        "quote": reply.text[:300],
                        "sourceRef": reply.id,
                        "deleted": False,
                    },
                )
            ],
        )
        person = person_of(store, author_account(store, reply))
        if person:
            store.upsert_links(
                "DECIDED_BY",
                "Decision",
                "Person",
                [
                    LinkRow(
                        did,
                        person,
                        {
                            "method": "inferred",
                            "confidence": round(p, 4),
                            "model": model,
                            "sourceRef": reply.id,
                        },
                    )
                ],
            )
    targets = _write_constraints(store, text, did, ex, c, keep_at, report)
    _write_implemented_by(store, text, did, c, ex, report)
    if status == "approved" and not (existing and existing.get("status") == "approved"):
        await _supersede(store, did, ex, targets, time_of(text), report, ws=ws)


def _write_constraints(
    store: GraphStore,
    text: TextNode,
    did: str,
    ex: models.DecisionExtraction,
    c: Classification,
    keep_at: float,
    report: DecisionReport,
) -> set[str]:
    targets: set[str] = set()
    for m in _mentions(store, text, keep_at):
        label = str(m["label"])
        if label not in CONSTRAINABLE:
            continue
        explicit = m["method"] == "explicit"
        conf = c.probability if explicit else min(c.probability, float(m["confidence"] or 0.0))
        store.upsert_links(
            "CONSTRAINS",
            "Decision",
            label,
            [
                LinkRow(
                    did,
                    str(m["id"]),
                    {
                        "method": "extracted" if explicit else "inferred",
                        "confidence": round(conf, 4),
                        "quote": ex.quote,
                        "model": ex.model,
                        "sourceRef": text.id,
                        "active": True,
                    },
                )
            ],
        )
        targets.add(str(m["id"]))
        report.links.append(
            CreatedLink(
                "CONSTRAINS",
                "Decision",
                did,
                label,
                str(m["id"]),
                ex.quote,
                f"This decision is about {m['name']}",
                "extracted" if explicit else "inferred",
            )
        )
    return targets


def _write_implemented_by(
    store: GraphStore,
    text: TextNode,
    did: str,
    c: Classification,
    ex: models.DecisionExtraction,
    report: DecisionReport,
) -> None:
    """DECISION_IMPLEMENTED_BY (A12.4): the source is itself the change, or it names the commit or PR."""
    rows: list[tuple[str, str, dict[str, Any]]] = []
    if text.label == "GitCommit" or (
        text.label == "GithubPullRequest" and text.props.get("merged")
    ):
        rows.append(
            (text.label, text.id, {"method": "structural", "confidence": 1.0, "sourceRef": text.id})
        )
    for m in store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[m:MENTIONS]->(x) WHERE m.method = 'explicit' "
        "AND coalesce(m.deleted, false) = false AND labels(x)[0] IN ['GitCommit', 'GithubPullRequest'] "
        "RETURN x.id AS id, labels(x)[0] AS label",
        {"id": text.id},
        read_only=True,
    ):
        rows.append(
            (
                str(m["label"]),
                str(m["id"]),
                {
                    "method": "extracted",
                    "confidence": round(c.probability, 4),
                    "quote": ex.quote,
                    "model": ex.model,
                    "sourceRef": text.id,
                },
            )
        )
    for label, tid, props in rows:
        report.implemented += store.upsert_links(
            "DECISION_IMPLEMENTED_BY", "Decision", label, [LinkRow(did, tid, props)]
        ).created


def _norm(scope: str | None) -> str:
    return " ".join((scope or "").lower().split())


async def _supersede(
    store: GraphStore,
    did: str,
    ex: models.DecisionExtraction,
    targets: set[str],
    decided_at: str | None,
    report: DecisionReport,
    *,
    ws: str | None,
) -> None:
    rows = store.query(
        "MATCH (e:Decision) WHERE e.id <> $id AND e.status = 'approved' AND coalesce(e.deleted, false) = false "
        "OPTIONAL MATCH (e)-[c:CONSTRAINS]->(x) WHERE coalesce(c.active, true) = true "
        "AND coalesce(c.deleted, false) = false "
        "RETURN e.id AS id, e.statement AS statement, e.quote AS quote, e.scope AS scope, e.decidedAt AS at, "
        "collect(x.id) AS targets, collect(labels(x)[0]) AS labels",
        {"id": did},
        read_only=True,
    )
    for e in rows:
        earlier_targets = {str(t) for t in e["targets"] if t}
        shares = bool(earlier_targets & targets) or (
            _norm(ex.scope) and _norm(ex.scope) == _norm(e.get("scope"))
        )
        if not shares or (decided_at and e.get("at") and str(e["at"]) > decided_at):
            continue
        j = await models.judge_supersession(
            {"statement": e["statement"], "quote": e["quote"], "scope": e.get("scope") or ""},
            {"statement": ex.statement, "quote": ex.quote, "scope": ex.scope},
            ws=ws,
        )
        if j.answer != "replaces" or (j.probability or 0.0) < SUPERSEDE_THRESHOLD:
            continue
        apply_supersession(
            store,
            did,
            str(e["id"]),
            ex.scope or "",
            targets,
            dict(
                zip(
                    [str(t) for t in e["targets"] if t],
                    [str(lbl) for lbl in e["labels"] if lbl],
                    strict=False,
                )
            ),
            confidence=float(j.probability or 0.0),
            model=j.model,
        )
        report.superseded += 1


def apply_supersession(
    store: GraphStore,
    new_id: str,
    old_id: str,
    scope: str,
    new_targets: set[str],
    old_targets: dict[str, str],
    *,
    confidence: float,
    model: str,
) -> bool:
    """SUPERSEDES {scope}; full when the new decision covers every old target, else partial (A12.4a).

    Returns True when the supersession was full (the old decision becomes `superseded`).
    """
    overlap = {t for t in old_targets if t in new_targets}
    full = not old_targets or overlap == set(old_targets)
    store.upsert_links(
        "SUPERSEDES",
        "Decision",
        "Decision",
        [
            LinkRow(
                new_id,
                old_id,
                {
                    "method": "inferred",
                    "confidence": round(confidence, 4),
                    "model": model,
                    "scope": scope or ("full" if full else "partial"),
                },
            )
        ],
    )
    deactivate = set(old_targets) if full else overlap
    for tid in sorted(deactivate):
        if old_targets[tid] not in store.ontology.nodes:
            continue
        store.query(
            f"MATCH (d:Decision {{id: $d}})-[c:CONSTRAINS]->(x:`{old_targets[tid]}` {{id: $t}}) "
            "SET c.active = false, c.supersededBy = $new",
            {"d": old_id, "t": tid, "new": new_id},
        )
    if full:
        store.update_nodes("Decision", [{"id": old_id, "status": "superseded"}])
    log.info(
        "decision superseded", extra={"new": new_id, "old": old_id, "full": full, "at": now_iso()}
    )
    return full
