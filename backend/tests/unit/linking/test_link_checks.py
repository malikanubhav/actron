"""A-AC-76: link checks delete (< 0.5), flag (0.5-0.7) or keep (>= 0.7) model-made links."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from actron.graph.store import LinkRow
from actron.linking.checks import check_links, outcome
from actron.linking.common import CreatedLink
from tests.fakes.jev import FakeJev
from tests.unit.linking import builders as b

SCORES = {"weak": 0.3, "borderline": 0.5, "almost": 0.69, "strong": 0.7}


@pytest.mark.parametrize(
    ("p", "action"),
    [
        (0.0, "delete"),
        (0.49, "delete"),
        (0.5, "flag"),
        (0.69, "flag"),
        (0.7, "keep"),
        (1.0, "keep"),
    ],
)
def test_thresholds(p: float, action: str) -> None:
    """A-AC-76: boundaries are inclusive at 0.5 and 0.7."""
    assert outcome(p) == action


def _setup(g: Any) -> tuple[str, list[CreatedLink]]:
    msg = b.slack_msg(g, "C1", "1.1", "the paste thing")
    made: list[CreatedLink] = []
    for name in SCORES:
        fn = b.code_fn(g, f"src/{name}.ts", name, f"function {name}() {{}}")
        g.upsert_links(
            "MENTIONS",
            "SlackMessage",
            "CodeFunction",
            [
                LinkRow(
                    msg, fn, {"method": "inferred", "confidence": 0.8, "quote": "the paste thing"}
                )
            ],
        )
        made.append(
            CreatedLink(
                "MENTIONS",
                "SlackMessage",
                msg,
                "CodeFunction",
                fn,
                "the paste thing",
                f"This message is about the function {name}",
            )
        )
    return msg, made


async def test_delete_flag_keep(indexed_graph: Any, jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-76."""
    g = indexed_graph
    msg, made = _setup(g)

    def by_claim(qid: str, q: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        return {"type": "noul", "noul": SCORES[state["claim"].rsplit(" ", 1)[-1]]}

    fake = jev_on(answer_fn=by_claim)
    report = await check_links(g, made)
    assert (report.checked, report.deleted, report.flagged, report.kept) == (4, 1, 2, 1)
    remaining = {lk["to"].rsplit("::", 1)[-1]: lk for lk in b.links(g, "MENTIONS", msg)}
    assert set(remaining) == {"borderline", "almost", "strong"}
    assert (
        remaining["borderline"]["flag"] == "possible" and remaining["almost"]["flag"] == "possible"
    )
    assert "flag" not in remaining["strong"]
    assert fake.requests[0]["state"] == {"quote": "the paste thing", "claim": made[0].claim}


async def test_explicit_links_not_checked(
    indexed_graph: Any, jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-76: only inferred and extracted links are re-judged."""
    g = indexed_graph
    fake = jev_on(noul=0.0)
    link = CreatedLink(
        "MENTIONS",
        "SlackMessage",
        "slack:msg:C:1",
        "CodeFile",
        "code:file:a/b:x",
        "q",
        "c",
        method="explicit",
    )
    report = await check_links(g, [link])
    assert report.checked == 0 and fake.calls == 0


async def test_failed_extraction_check_removes_decision(
    indexed_graph: Any, jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-76: an EXTRACTED_FROM below 0.5 is deleted together with its decision."""
    g = indexed_graph
    msg = b.slack_msg(g, "C1", "2.1", "We might do X")
    g.upsert_nodes(
        "Decision",
        [
            {
                "id": "actron:decision:x",
                "statement": "X",
                "status": "proposed",
                "quote": "X",
                "confidence": 0.6,
                "extractedBy": "m",
            }
        ],
    )
    g.upsert_links(
        "EXTRACTED_FROM",
        "Decision",
        "SlackMessage",
        [LinkRow("actron:decision:x", msg, {"method": "extracted", "confidence": 0.6})],
    )
    jev_on(noul=0.2)
    report = await check_links(
        g,
        [
            CreatedLink(
                "EXTRACTED_FROM",
                "Decision",
                "actron:decision:x",
                "SlackMessage",
                msg,
                "We might do X",
                "This text states the decision: X",
                "extracted",
            )
        ],
    )
    assert report.decisions_dropped == 1 and g.get_node("actron:decision:x") is None


async def test_stub_flags_never_deletes(indexed_graph: Any) -> None:
    """A-AC-76 with no keys: the 0.5 stub keeps every link and flags it."""
    g = indexed_graph
    msg, made = _setup(g)
    report = await check_links(g, made)
    assert report.stub and report.deleted == 0 and report.flagged == 4
    assert len(b.links(g, "MENTIONS", msg)) == 4
