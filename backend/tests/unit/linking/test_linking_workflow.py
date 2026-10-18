"""LinkingWorkflow (time-skipping): step order, batching, progress events, and a real run on a test graph.

A-AC-72 (pending resolved through the workflow), A.C6 linking events.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from actron.activities.link import ACTIVITIES, ChecksInput, LinkBatch, LinkEvent, PendingInput
from actron.graph import ids
from actron.linking import runner
from actron.workflows.linking import TASK_QUEUE, LinkingOptions, LinkingWorkflow
from tests.unit.linking import builders as b


def _fake_activities(calls: list[tuple[str, Any]]) -> list[Any]:
    @activity.defn(name="link_identity")
    async def identity(ws: str) -> dict[str, Any]:
        calls.append(("identity", ws))
        return {"accounts": 2}

    @activity.defn(name="link_references")
    async def references(batch: LinkBatch) -> dict[str, Any]:
        calls.append(("references", list(batch.text_ids)))
        return {"resolved": len(batch.text_ids), "pending": 1}

    @activity.defn(name="link_resolve_pending")
    async def pending(data: PendingInput) -> dict[str, Any]:
        calls.append(("pending", list(data.sources)))
        return {"resolved": 1}

    @activity.defn(name="link_classify")
    async def classify(batch: LinkBatch) -> dict[str, dict[str, Any]]:
        calls.append(("classify", list(batch.text_ids)))
        return {t: {"kind": "decision", "probability": 0.9, "stub": False} for t in batch.text_ids}

    @activity.defn(name="link_meaning")
    async def meaning(batch: LinkBatch) -> dict[str, Any]:
        calls.append(("meaning", sorted(batch.classes)))
        return {
            "kept": 1,
            "dropped": 2,
            "links": [
                {
                    "rel": "MENTIONS",
                    "from_label": "SlackMessage",
                    "from_id": batch.text_ids[0],
                    "to_label": "CodeFunction",
                    "to_id": "code:fn:a/b:x.ts::f",
                    "quote": "q",
                    "claim": "c",
                    "method": "inferred",
                }
            ],
        }

    @activity.defn(name="link_decisions")
    async def decisions(batch: LinkBatch) -> dict[str, Any]:
        calls.append(("decisions", list(batch.text_ids)))
        return {"extracted": 1, "links": [], "decision_ids": ["actron:decision:x"]}

    @activity.defn(name="link_checks")
    async def checks(data: ChecksInput) -> dict[str, Any]:
        calls.append(("checks", len(data.links)))
        return {"checked": len(data.links), "deleted": 1}

    @activity.defn(name="link_knowledge")
    async def knowledge(ws: str) -> dict[str, Any]:
        calls.append(("knowledge", ws))
        return {}

    @activity.defn(name="link_procedures")
    async def procedures(batch: LinkBatch) -> dict[str, Any]:
        calls.append(("procedures", len(batch.text_ids)))
        return {}

    @activity.defn(name="link_publish")
    async def publish(event: LinkEvent) -> None:
        calls.append(("event", (event.type, event.payload)))

    return [
        identity,
        references,
        pending,
        classify,
        meaning,
        decisions,
        checks,
        knowledge,
        procedures,
        publish,
    ]


async def test_order_batches_and_events() -> None:
    """A12 order is fixed; text batches respect the batch size and the cap; events follow A.C6."""
    calls: list[tuple[str, Any]] = []
    texts = [ids.slack_msg("C1", f"{i}.0") for i in range(5)]
    changed = [*texts, ids.slack_user("U1"), ids.linear_issue("u-1")]
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LinkingWorkflow],
            activities=_fake_activities(calls),
        ),
    ):
        result = await env.client.execute_workflow(
            LinkingWorkflow.run,
            args=["acme", changed, LinkingOptions(max_texts=5, batch_size=2)],
            id=f"link-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
    steps = [c[0] for c in calls if c[0] != "event"]
    assert steps == [
        "identity",
        "references",
        "references",
        "references",
        "pending",
        "classify",
        "classify",
        "classify",
        "meaning",
        "meaning",
        "meaning",
        "decisions",
        "decisions",
        "decisions",
        "checks",
        "knowledge",
        "procedures",
    ]
    assert [c[1] for c in calls if c[0] == "references"] == [texts[:2], texts[2:4], texts[4:]]
    assert ("pending", ["slack", "linear"]) in calls
    assert ("checks", 3) in calls
    events = [c[1] for c in calls if c[0] == "event"]
    assert events[-1][0] == "linking.finished"
    progress = [e[1] for e in events if e[0] == "linking.progress"]
    assert {"step", "done", "total", "runId"} <= set(progress[0])
    assert result["counts"] == {
        "references_resolved": 5 + 1,
        "pending": 3,
        "decisions": 3,
        "identities": 2,
        "links_kept": 3 - 1,
        "links_dropped": 6 + 1,
    }
    assert result["texts"] == 5


async def test_cap_limits_texts() -> None:
    """Per-run cap: texts beyond `max_texts` wait for the next run."""
    calls: list[tuple[str, Any]] = []
    texts = [ids.slack_msg("C1", f"{i}.0") for i in range(7)]
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LinkingWorkflow],
            activities=_fake_activities(calls),
        ),
    ):
        result = await env.client.execute_workflow(
            LinkingWorkflow.run,
            args=["acme", texts, LinkingOptions(max_texts=4, batch_size=10)],
            id=f"link-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
    assert result["capped"] == 3 and result["texts"] == 4
    assert not any(c[0] == "identity" for c in calls)  # no account changed


async def test_real_activities_resolve_pending(indexed_graph: Any) -> None:
    """A-AC-72 through the workflow: Slack first (pending), then Linear (resolved), with real activities."""
    g = indexed_graph
    ws = f"wf{uuid.uuid4().hex[:8]}"
    runner.use_store(ws, g)
    try:
        msg = b.slack_msg(g, "C1", "1712345678.000400", "ENG-40 is the plan for the jack-in menu.")
        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[LinkingWorkflow],
                activities=ACTIVITIES,
            ),
        ):
            first = await env.client.execute_workflow(
                LinkingWorkflow.run, args=[ws, [msg]], id=f"l1-{ws}", task_queue=TASK_QUEUE
            )
            assert first["counts"]["pending"] == 1
            team = b.linear_team(g, "ENG")
            issue = b.linear_issue(g, "u-40", "ENG-40", "Jack-in menu order")
            second = await env.client.execute_workflow(
                LinkingWorkflow.run, args=[ws, [team, issue]], id=f"l2-{ws}", task_queue=TASK_QUEUE
            )
        assert second["counts"]["references_resolved"] >= 1
        assert b.node(g, ids.reference("linear_issue", "ENG-40"))["status"] == "resolved"
        assert b.links(g, "MENTIONS", msg, issue)
    finally:
        runner.use_store(ws, None)


@pytest.mark.parametrize(
    "name",
    [
        "link_identity",
        "link_references",
        "link_resolve_pending",
        "link_classify",
        "link_meaning",
        "link_decisions",
        "link_checks",
        "link_knowledge",
        "link_procedures",
        "link_publish",
    ],
)
def test_activity_names_registered(name: str) -> None:
    """Temporal registration: ACTIVITIES exports every activity the workflow calls."""
    assert name in {a.__temporal_activity_definition.name for a in ACTIVITIES}  # type: ignore[attr-defined]
