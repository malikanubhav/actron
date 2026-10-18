"""Linking activities (task queue `link`): thin wrappers over `actron.linking.runner` steps (spec A, A12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from actron.linking import runner
from actron.logging import get_logger

log = get_logger(__name__)


@dataclass
class LinkBatch:
    ws: str
    text_ids: list[str]
    classes: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PendingInput:
    ws: str
    sources: list[str]


@dataclass
class ChecksInput:
    ws: str
    links: list[dict[str, str]]


@dataclass
class LinkEvent:
    ws: str
    type: str
    payload: dict[str, Any]


@activity.defn(name="link_identity")
async def link_identity(ws: str) -> dict[str, Any]:
    return runner.step_identity(ws)


@activity.defn(name="link_references")
async def link_references(batch: LinkBatch) -> dict[str, Any]:
    return runner.step_references(batch.ws, batch.text_ids)


@activity.defn(name="link_resolve_pending")
async def link_resolve_pending(data: PendingInput) -> dict[str, Any]:
    return runner.step_resolve_pending(data.ws, data.sources)


@activity.defn(name="link_classify")
async def link_classify(batch: LinkBatch) -> dict[str, dict[str, Any]]:
    return await runner.step_classify(batch.ws, batch.text_ids)


@activity.defn(name="link_meaning")
async def link_meaning(batch: LinkBatch) -> dict[str, Any]:
    return await runner.step_meaning(batch.ws, batch.text_ids, batch.classes)


@activity.defn(name="link_decisions")
async def link_decisions(batch: LinkBatch) -> dict[str, Any]:
    return await runner.step_decisions(batch.ws, batch.text_ids, batch.classes)


@activity.defn(name="link_checks")
async def link_checks(data: ChecksInput) -> dict[str, Any]:
    return await runner.step_checks(data.ws, data.links)


@activity.defn(name="link_knowledge")
async def link_knowledge(ws: str) -> dict[str, Any]:
    return runner.step_knowledge(ws)


@activity.defn(name="link_procedures")
async def link_procedures(batch: LinkBatch) -> dict[str, Any]:
    return await runner.step_procedures(batch.ws, batch.text_ids, batch.classes)


@activity.defn(name="link_publish")
async def link_publish(event: LinkEvent) -> None:
    """`linking.progress` / `linking.finished` (A.C6) through the workspace event stream (W6)."""
    try:
        from actron.flow.events import publish_workspace_event

        await publish_workspace_event(event.ws, event.type, event.payload)
    except Exception as exc:  # events are best effort; linking results are already in the graph
        log.warning(
            "linking event not published", extra={"type": event.type, "error": type(exc).__name__}
        )


ACTIVITIES = [
    link_identity,
    link_references,
    link_resolve_pending,
    link_classify,
    link_meaning,
    link_decisions,
    link_checks,
    link_knowledge,
    link_procedures,
    link_publish,
]
