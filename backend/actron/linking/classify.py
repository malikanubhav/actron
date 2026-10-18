"""J1 classification of new or edited texts (PRD 10.2a): decides which texts go to meaning links,
decision extraction and procedure learning. Results are passed between linking steps, not stored on nodes
(the ontology has no property for them); the model cache makes re-runs free.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from actron import models
from actron.graph.store import GraphStore
from actron.linking.common import J1_SOURCE, TextNode, load_texts

CONCURRENCY = 8


@dataclass(frozen=True)
class Classification:
    kind: str
    probability: float
    stub: bool

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "probability": self.probability, "stub": self.stub}


def _parent_text(store: GraphStore, text: TextNode) -> str | None:
    if text.label != "SlackMessage":
        return None
    rows = store.query(
        "MATCH (m:SlackMessage {id: $id})-[:THREAD_OF]->(p:SlackMessage) RETURN p.text AS t LIMIT 1",
        {"id": text.id},
        read_only=True,
    )
    return str(rows[0]["t"]) if rows and rows[0].get("t") else None


async def classify_texts(
    store: GraphStore, text_ids: list[str], *, ws: str | None = None
) -> dict[str, Classification]:
    texts = [t for t in load_texts(store, text_ids, include_deleted=False) if t.text.strip()]
    sem = asyncio.Semaphore(CONCURRENCY)
    out: dict[str, Classification] = {}

    async def one(text: TextNode) -> None:
        async with sem:
            j = await models.classify_message(
                text.text[:8000], J1_SOURCE[text.label], _parent_text(store, text), ws=ws
            )
        out[text.id] = Classification(str(j.answer), float(j.probability or 0.0), j.stub)

    await asyncio.gather(*(one(t) for t in texts))
    return out
