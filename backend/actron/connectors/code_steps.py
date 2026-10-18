"""The `code` source in the uniform connector interface (STEPS, fetch_page, write_batch).

These are thin wrappers around W2's `actron.connectors.code.pipeline`, imported lazily so this
module loads before that one exists. Code steps write to the graph themselves (they work from a local
clone), so `fetch_page` runs the step and `write_batch` only reports what it did.

Entry points used, in this order:
1. `pipeline.run_step(ws, step, cursor=..., page_token=..., config=...)` returning an object with
   `next_page_token`, `cursor_update`, `counts`, `changed_ids` and `partial_reason` (per-step form);
2. `pipeline.ingest_code(ws, repo, url=..., branch=..., clone_dir=..., depth=..., token=..., emit=None)`
   (whole-run form): run once at the first step; the other steps then have nothing left to do.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Mapping
from typing import Any

from actron.config import get_settings
from actron.connectors.common import Batch, ValidationError, WriteResult
from actron.connectors.steps import SOURCE_STEPS
from actron.logging import get_logger

log = get_logger(__name__)

STEPS: list[str] = SOURCE_STEPS["code"]


def _pipeline() -> Any:
    try:
        return importlib.import_module("actron.connectors.code.pipeline")
    except ModuleNotFoundError as exc:
        raise ValidationError("code ingestion is not available in this build", code="code_pipeline_missing") from exc


def _clone_url(repo: str) -> str:
    return get_settings().git_url(repo)


async def fetch_page(ws: str, step: str, cursor: Mapping[str, Any], page_token: str | None,
                     config: Mapping[str, Any]) -> Batch:
    if step not in STEPS:
        raise ValueError(f"unknown code step {step!r}")
    pipeline = _pipeline()
    batch = Batch(step=step)
    repo = config.get("repository")
    if not repo:
        raise ValidationError("no repository is configured for the code connection")
    run_step = getattr(pipeline, "run_step", None)
    if run_step is not None:
        result = await _maybe_await(run_step(ws, step, cursor=dict(cursor), page_token=page_token, config=dict(config)))
        batch.next_page_token = getattr(result, "next_page_token", None)
        batch.cursor_update = dict(getattr(result, "cursor_update", {}) or {})
        batch.partial_reason = getattr(result, "partial_reason", None)
        batch.extra = {"counts": dict(getattr(result, "counts", {}) or {}),
                       "changed_ids": list(getattr(result, "changed_ids", []) or [])}
        return batch
    if step != STEPS[0]:
        return batch
    settings = get_settings()
    report = await _maybe_await(pipeline.ingest_code(
        ws, repo, url=_clone_url(repo), branch=config.get("working_branch"),
        clone_dir=settings.ACTRON_CLONE_DIR / ws / repo.replace("/", "__"),
        depth=settings.ACTRON_GIT_HISTORY_DEPTH, token=config.get("token"), emit=None))
    batch.extra = {"counts": dict(getattr(report, "counts", {}) or {}),
                   "changed_ids": list(getattr(report, "changed_ids", []) or [])}
    head = getattr(report, "head_sha", None)
    if head:
        batch.cursor_update = {"last_sha": head}
    batch.partial_reason = getattr(report, "partial_reason", None)
    return batch


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


def write_batch(ws: str, step: str, batch: Batch) -> WriteResult:
    """Nothing to write: the pipeline already wrote this step. Report its counts and changed ids."""
    extra = batch.extra or {}
    return WriteResult(counts={k: int(v) for k, v in (extra.get("counts") or {}).items()},
                       changed_ids=[str(i) for i in extra.get("changed_ids") or []])
