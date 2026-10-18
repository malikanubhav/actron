"""Meaning links (spec A, A12.3): text -> code or feature it is about, judged by Jev (J3).

Candidates: top 10 full-text matches over CodeFunction, CodeClass, CodeFile and Feature (stop words removed),
plus code within one hop of anything the text explicitly mentions; already-linked targets are dropped.
All candidates of one text are judged in one Jev request; links at or above `LINK_KEEP_THRESHOLD` are kept
as `MENTIONS` (method `inferred`, confidence = probability, model) and, for features, `DISCUSSED_IN`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from actron import models
from actron.config import get_settings
from actron.graph.store import GraphError, GraphStore, LinkRow
from actron.linking.common import CreatedLink, TextNode, load_texts
from actron.logging import get_logger

log = get_logger(__name__)

MEANING_KINDS = frozenset({"decision", "proposal", "request", "bug_report", "question"})
SEARCH_LABELS = ("CodeFunction", "CodeClass", "CodeFile", "Feature")
KIND_OF = {
    "CodeFunction": "function",
    "CodeClass": "class",
    "CodeFile": "file",
    "Feature": "feature",
}
MAX_FULLTEXT = 10
MAX_NEIGHBOURS = 10
STOP_WORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "let",
        "lets",
        "like",
        "me",
        "more",
        "most",
        "my",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yes",
        "ok",
        "okay",
        "please",
        "thanks",
        "thank",
        "hey",
        "hi",
        "hello",
        "think",
        "maybe",
        "really",
        "still",
        "want",
        "wants",
        "need",
        "needs",
        "get",
        "got",
        "make",
        "makes",
        "made",
        "use",
        "used",
        "using",
        "one",
        "two",
        "way",
        "thing",
        "things",
        "lot",
        "bit",
        "today",
        "tomorrow",
        "yesterday",
        "going",
        "go",
        "goes",
        "done",
        "work",
        "works",
        "working",
    ]
)


@dataclass
class MeaningReport:
    texts: int = 0
    candidates: int = 0
    kept: int = 0
    dropped: int = 0
    stub: bool = False
    links: list[CreatedLink] = field(default_factory=list)


def search_terms(text: str, limit: int = 12) -> list[str]:
    """Normalised search terms: identifiers split, stop words removed, order kept, no duplicates."""
    words: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", text):
        pieces = re.findall(
            r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", token.replace("-", " ").replace("_", " ")
        )
        parts = [token, *pieces]
        for w in parts:
            w = w.lower().strip("-_")
            if len(w) >= 3 and w not in STOP_WORDS and w not in words:
                words.append(w)
    return words[:limit]


def _fulltext(store: GraphStore, text: str) -> list[dict[str, Any]]:
    terms = search_terms(text)
    if not terms:
        return []
    query = "|".join(terms)
    found: list[dict[str, Any]] = []
    for label in SEARCH_LABELS:
        try:
            rows = store.query(
                f"CALL db.idx.fulltext.queryNodes('{label}', $q) YIELD node, score "
                "WHERE coalesce(node.deleted, false) = false RETURN node, score ORDER BY score DESC LIMIT $n",
                {"q": query, "n": MAX_FULLTEXT},
                read_only=True,
            )
        except GraphError as exc:  # no full-text index for this label yet
            log.debug("full-text search skipped", extra={"label": label, "error": str(exc)[:120]})
            continue
        for r in rows:
            node = dict(r["node"])
            node["_label"] = label
            found.append({"node": node, "score": float(r["score"])})
    found.sort(key=lambda x: -x["score"])
    return found[:MAX_FULLTEXT]


def _neighbours(store: GraphStore, text: TextNode) -> list[dict[str, Any]]:
    rows = store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[m:MENTIONS]->(x) WHERE m.method = 'explicit' "
        "AND coalesce(m.deleted, false) = false MATCH (x)-[]-(n) "
        "WHERE labels(n)[0] IN ['CodeFunction', 'CodeClass', 'CodeFile'] AND coalesce(n.deleted, false) = false "
        "RETURN DISTINCT n LIMIT $n",
        {"id": text.id, "n": MAX_NEIGHBOURS},
        read_only=True,
    )
    return [{"node": dict(r["n"]), "score": 0.0} for r in rows]


def _already_linked(store: GraphStore, text: TextNode) -> set[str]:
    rows = store.query(
        f"MATCH (t:`{text.label}` {{id: $id}})-[m:MENTIONS]->(x) WHERE coalesce(m.deleted, false) = false "
        "RETURN x.id AS id",
        {"id": text.id},
        read_only=True,
    )
    return {str(r["id"]) for r in rows}


def candidate_of(node: dict[str, Any]) -> models.Candidate:
    label = str(node.get("_label"))
    kind = KIND_OF.get(label, "function")
    path = node.get("path")
    if path is None and isinstance(node.get("id"), str) and "::" in node["id"]:
        path = node["id"].split(":", 3)[-1].split("::")[0].split(":", 1)[-1]
    name = node.get("qualifiedName") or node.get("name") or node.get("path") or node.get("id")
    return models.Candidate(
        kind=kind,
        name=str(name),
        path=str(path) if path else None,
        signature=node.get("signature"),
        docstring=node.get("docstring") or node.get("description"),
        id=str(node["id"]),
    )


def best_sentence(text: str, cand: models.Candidate) -> str:
    """The sentence of `text` that shares most words with the candidate (the link's quote)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        return text[:300]
    target = set(search_terms(" ".join(filter(None, [cand.name, cand.path or ""])), limit=30))
    best = max(sentences, key=lambda s: len(target & set(search_terms(s, limit=30))))
    return best[:300]


def claim_for(cand: models.Candidate) -> str:
    where = f" in {cand.path}" if cand.path and cand.kind != "file" else ""
    noun = {
        "function": "the function",
        "class": "the class",
        "file": "the file",
        "feature": "the feature",
    }
    return f"This message is about {noun[cand.kind]} {cand.name}{where}"


async def link_meaning(
    store: GraphStore,
    text_ids: list[str],
    kinds: dict[str, str],
    *,
    ws: str | None = None,
    threshold: float | None = None,
) -> MeaningReport:
    """Judge candidates for each text whose J1 kind is in MEANING_KINDS; keep links >= threshold."""
    keep_at = get_settings().LINK_KEEP_THRESHOLD if threshold is None else threshold
    report = MeaningReport()
    eligible = [i for i in text_ids if kinds.get(i) in MEANING_KINDS]
    for text in load_texts(store, eligible, include_deleted=False):
        if not text.text.strip():
            continue
        report.texts += 1
        linked = _already_linked(store, text)
        seen: set[str] = set()
        cands: list[models.Candidate] = []
        for item in _fulltext(store, text.text) + _neighbours(store, text):
            nid = str(item["node"].get("id"))
            if nid in linked or nid in seen or nid == text.id:
                continue
            seen.add(nid)
            if "_label" not in item["node"]:
                from actron.linking.common import label_of

                item["node"]["_label"] = label_of(nid)
            cands.append(candidate_of(item["node"]))
        if not cands:
            continue
        report.candidates += len(cands)
        judgments = await models.judge_links(text.text, cands, ws=ws)
        for cand, j in zip(cands, judgments, strict=True):
            report.stub = report.stub or j.stub
            p = j.probability or 0.0
            if p < keep_at or cand.id is None:
                report.dropped += 1
                continue
            label = {
                "function": "CodeFunction",
                "class": "CodeClass",
                "file": "CodeFile",
                "feature": "Feature",
            }[cand.kind]
            quote = best_sentence(text.text, cand)
            props = {
                "method": "inferred",
                "confidence": round(p, 4),
                "model": j.model,
                "quote": quote,
                "sourceRef": text.id,
                "deleted": False,
            }
            store.upsert_links("MENTIONS", text.label, label, [LinkRow(text.id, cand.id, props)])
            claim = claim_for(cand)
            report.links.append(
                CreatedLink("MENTIONS", text.label, text.id, label, cand.id, quote, claim)
            )
            if label == "Feature":
                store.upsert_links(
                    "DISCUSSED_IN", "Feature", text.label, [LinkRow(cand.id, text.id, props)]
                )
                report.links.append(
                    CreatedLink(
                        "DISCUSSED_IN", "Feature", cand.id, text.label, text.id, quote, claim
                    )
                )
            report.kept += 1
    return report
