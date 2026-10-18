"""Link checks (spec A, A12.5): every model-made link from this run is re-judged with J4.

Probability < 0.5: delete the link (an `EXTRACTED_FROM` that fails also removes its decision);
0.5 to < 0.7: keep and set `flag = "possible"`; >= 0.7: keep.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from actron import models
from actron.graph.store import GraphStore
from actron.linking.common import CreatedLink

DROP_BELOW = 0.5
FLAG_BELOW = 0.7
CONCURRENCY = 8


@dataclass
class CheckReport:
    checked: int = 0
    kept: int = 0
    flagged: int = 0
    deleted: int = 0
    decisions_dropped: int = 0
    stub: bool = False


def outcome(probability: float) -> str:
    if probability < DROP_BELOW:
        return "delete"
    if probability < FLAG_BELOW:
        return "flag"
    return "keep"


async def check_links(
    store: GraphStore, links: list[CreatedLink], *, ws: str | None = None
) -> CheckReport:
    report = CheckReport()
    todo = [lk for lk in links if lk.method in ("inferred", "extracted")]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def judge(link: CreatedLink) -> tuple[CreatedLink, models.Judgment]:
        async with sem:
            return link, await models.check_link(link.quote, link.claim, ws=ws)

    results = await asyncio.gather(*(judge(lk) for lk in todo))
    for link, j in results:
        report.checked += 1
        report.stub = report.stub or j.stub
        action = outcome(float(j.probability or 0.0))
        if action == "delete":
            store.delete_links(
                link.rel, link.from_label, link.to_label, [(link.from_id, link.to_id)]
            )
            report.deleted += 1
            if link.rel == "EXTRACTED_FROM":
                store.query("MATCH (d:Decision {id: $id}) DETACH DELETE d", {"id": link.from_id})
                report.decisions_dropped += 1
        elif (
            action == "flag"
            and (link.rel, link.from_label, link.to_label) in store.ontology.relationships
        ):
            store.query(
                f"MATCH (a:`{link.from_label}` {{id: $a}})-[r:`{link.rel}`]->(b:`{link.to_label}` {{id: $b}}) "
                "SET r.flag = 'possible'",
                {"a": link.from_id, "b": link.to_id},
            )
            report.flagged += 1
        else:
            report.kept += 1
    return report
