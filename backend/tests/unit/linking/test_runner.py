"""In-process linking run: all steps in order with progress events and A.C6 counts (stubs only)."""

from __future__ import annotations

from typing import Any

from actron.graph import ids
from actron.linking.runner import RunCaps, run_linking, sources_of
from tests.unit.linking import builders as b


def test_sources_of() -> None:
    """A12.2: sources come from the changed ids' prefixes."""
    assert sources_of([ids.slack_msg("C", "1.0"), ids.linear_issue("u"), ids.slack_user("U")]) == [
        "slack",
        "linear",
    ]


async def test_run_linking_with_stubs(indexed_graph: Any) -> None:
    """A-AC-72 + A.C6: a full run with no keys links references, reports pending and stub, emits events."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    issue = b.linear_issue(g, "u-1", "CAL-1", "Paste formatting")
    b.slack_user(g, "U1", email="a@x.org")
    m1 = b.slack_msg(g, "C1", "1.1", "CAL-1 is about paste formatting", user="U1")
    m2 = b.slack_msg(g, "C1", "1.2", "And CAL-99 is not there yet", user="U1")
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(type: str, payload: dict[str, Any], **_: Any) -> None:
        events.append((type, payload))

    report = await run_linking(
        "acme",
        [m1, m2, ids.slack_user("U1")],
        run_id="r1",
        emit=emit,
        store=g,
        caps=RunCaps(max_texts=10, batch_size=1),
    )
    assert report.counts["references_resolved"] == 1 and report.counts["pending"] == 1
    assert report.counts["identities"] == 1 and report.counts["decisions"] == 0
    assert report.stub
    assert b.links(g, "MENTIONS", m1, issue)
    assert events[-1] == ("linking.finished", {"runId": "r1", "counts": report.counts})
    steps = [p["step"] for t, p in events if t == "linking.progress"]
    assert (
        steps.index("identity")
        < steps.index("references")
        < steps.index("classify")
        < steps.index("checks")
    )
