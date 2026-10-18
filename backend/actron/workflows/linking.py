"""LinkingWorkflow (task queue `link`, spec A, A12; PRD 8.5).

Deterministic order over the ids a source run changed: identity -> references (+ pending) -> classify ->
meaning -> decisions -> link checks -> knowledge and procedures. Model steps run in batches with a per-run cap;
`linking.progress` is published after each batch and `linking.finished` at the end (A.C6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from actron.activities.link import (
        ChecksInput,
        LinkBatch,
        LinkEvent,
        PendingInput,
        link_checks,
        link_classify,
        link_decisions,
        link_identity,
        link_knowledge,
        link_meaning,
        link_procedures,
        link_publish,
        link_references,
        link_resolve_pending,
    )
    from actron.linking.common import ACCOUNT_LABELS, label_of
    from actron.linking.references import text_ids_for_source
    from actron.linking.runner import finished_counts, sources_of

TASK_QUEUE = "link"
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
)
SHORT = timedelta(minutes=5)
LONG = timedelta(minutes=20)


@dataclass
class LinkingOptions:
    max_texts: int = 2000
    batch_size: int = 100


@workflow.defn(name="LinkingWorkflow")
class LinkingWorkflow:
    @workflow.run
    async def run(
        self, ws: str, changed_ids: list[str], options: LinkingOptions | None = None
    ) -> dict[str, Any]:
        opts = options or LinkingOptions()
        run_id = workflow.info().workflow_id
        texts = text_ids_for_source(changed_ids)
        capped = max(0, len(texts) - opts.max_texts)
        texts = texts[: opts.max_texts]
        groups = [texts[i : i + opts.batch_size] for i in range(0, len(texts), opts.batch_size)]
        steps: dict[str, dict[str, Any]] = {}

        async def act(fn: Any, arg: Any, timeout: timedelta = SHORT) -> Any:
            return await workflow.execute_activity(
                fn, arg, start_to_close_timeout=timeout, retry_policy=RETRY
            )

        async def progress(step: str, done: int, total: int) -> None:
            await act(
                link_publish,
                LinkEvent(
                    ws,
                    "linking.progress",
                    {"runId": run_id, "step": step, "done": done, "total": total},
                ),
            )

        if not changed_ids or any(label_of(i) in ACCOUNT_LABELS for i in changed_ids):
            steps["identity"] = await act(link_identity, ws)
        await progress("identity", 1, 1)

        steps["references"] = {}
        for n, group in enumerate(groups, 1):
            _merge(steps["references"], await act(link_references, LinkBatch(ws, group)))
            await progress("references", n, len(groups))
        steps["pending"] = await act(
            link_resolve_pending, PendingInput(ws, sources_of(changed_ids))
        )

        classes: dict[str, dict[str, Any]] = {}
        for n, group in enumerate(groups, 1):
            classes.update(await act(link_classify, LinkBatch(ws, group), LONG))
            await progress("classify", n, len(groups))

        links: list[dict[str, str]] = []
        for step, fn in (("meaning", link_meaning), ("decisions", link_decisions)):
            steps[step] = {}
            for n, group in enumerate(groups, 1):
                sub = {k: v for k, v in classes.items() if k in set(group)}
                out = await act(fn, LinkBatch(ws, group, sub), LONG)
                links.extend(out.pop("links", []))
                out.pop("decision_ids", None)
                _merge(steps[step], out)
                await progress(step, n, len(groups))

        steps["checks"] = await act(link_checks, ChecksInput(ws, links), LONG)
        await progress("checks", 1, 1)
        steps["knowledge"] = await act(link_knowledge, ws, LONG)
        steps["procedures"] = await act(link_procedures, LinkBatch(ws, texts, classes), LONG)
        await progress("procedures", 1, 1)

        counts = finished_counts(steps)
        await act(
            link_publish, LinkEvent(ws, "linking.finished", {"runId": run_id, "counts": counts})
        )
        return {
            "runId": run_id,
            "counts": counts,
            "steps": steps,
            "capped": capped,
            "texts": len(texts),
        }


def _merge(agg: dict[str, Any], out: dict[str, Any]) -> None:
    for k, v in out.items():
        if isinstance(v, bool):
            agg[k] = bool(agg.get(k)) or v
        elif isinstance(v, int | float):
            agg[k] = agg.get(k, 0) + v


WORKFLOWS = [LinkingWorkflow]
