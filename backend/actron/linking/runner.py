"""Linking runner (spec A, A12; PRD 8.5): identity -> references and pending -> classify -> meaning ->
decisions -> checks -> knowledge and procedures, over the ids changed by a source run.

Each step is a plain function returning JSON-safe data, so the Temporal activities (`actron.activities.link`)
call them one by one and `run_linking` can run them in-process. Model steps run in batches with a per-run cap
and publish `linking.progress {runId, step, done, total}` and `linking.finished {runId, counts}` (A.C6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from actron.config import get_settings
from actron.graph.store import GraphStore, store_for
from actron.linking import checks, decisions, identity, knowledge, meaning, procedures, references
from actron.linking.classify import Classification, classify_texts
from actron.linking.common import ACCOUNT_LABELS, CreatedLink, label_of
from actron.logging import get_logger

log = get_logger(__name__)

STEPS = (
    "identity",
    "references",
    "classify",
    "meaning",
    "decisions",
    "checks",
    "knowledge",
    "procedures",
)
SOURCE_OF_PREFIX = {
    "slack": "slack",
    "linear": "linear",
    "github": "github",
    "git": "git",
    "code": "code",
}


class EventSink(Protocol):
    async def __call__(
        self, type: str, payload: dict[str, Any], *, actor: str = "actron", surface: str = "system"
    ) -> None: ...


@dataclass(frozen=True)
class RunCaps:
    max_texts: int = 2000  # model-backed steps per run; the rest waits for the next run
    batch_size: int = 100


@dataclass
class LinkingReport:
    run_id: str
    counts: dict[str, int] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    capped: int = 0
    stub: bool = False


_stores: dict[str, GraphStore] = {}


def use_store(ws: str, store: GraphStore | None) -> None:
    """Tests only: route a workspace to a given store (activities resolve stores by workspace)."""
    if store is None:
        _stores.pop(ws, None)
    else:
        _stores[ws] = store


def get_store(ws: str) -> GraphStore:
    return _stores.get(ws) or store_for(ws)


def sources_of(changed_ids: list[str]) -> list[str]:
    out: list[str] = []
    for nid in changed_ids:
        src = SOURCE_OF_PREFIX.get(nid.split(":", 1)[0])
        if src and src not in out:
            out.append(src)
    return out


def batches(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def link_to_dict(link: CreatedLink) -> dict[str, str]:
    return asdict(link)


def link_from_dict(data: dict[str, str]) -> CreatedLink:
    return CreatedLink(**data)


def _bot_users(store: GraphStore) -> set[str]:
    rows = store.query("MATCH (u:SlackUser) WHERE u.isBot = true RETURN u.id AS id", read_only=True)
    return {str(r["id"]).removeprefix("slack:user:") for r in rows}


# Steps (each JSON in, JSON out)


def step_identity(ws: str) -> dict[str, Any]:
    r = identity.link_identities(get_store(ws), ws)
    return {
        "accounts": r.accounts,
        "people": r.people,
        "resolved_people": r.resolved_people,
        "unresolved": len(r.unresolved),
        "unresolved_accounts": r.unresolved[:200],
        "merged": r.merged,
        "unmatched_mapping_entries": r.unmatched_mapping_entries,
    }


def step_references(ws: str, text_ids: list[str]) -> dict[str, Any]:
    r = references.link_references(get_store(ws), text_ids)
    return {
        "references": r.references,
        "resolved": r.resolved,
        "pending": r.pending,
        "ambiguous": r.ambiguous,
        "mentions": r.mentions,
        "implemented_by": r.implemented_by,
        "tombstoned": r.tombstoned,
    }


def step_resolve_pending(ws: str, sources: list[str]) -> dict[str, Any]:
    total = references.RefReport()
    store = get_store(ws)
    for source in sources or [None]:  # type: ignore[list-item]
        total.add(references.resolve_pending(store, source))
    return {
        "resolved": total.resolved,
        "ambiguous": total.ambiguous,
        "mentions": total.mentions,
        "implemented_by": total.implemented_by,
    }


async def step_classify(ws: str, text_ids: list[str]) -> dict[str, dict[str, Any]]:
    found = await classify_texts(get_store(ws), text_ids, ws=ws)
    return {k: v.as_dict() for k, v in found.items()}


def _classes(data: dict[str, dict[str, Any]]) -> dict[str, Classification]:
    return {
        k: Classification(str(v["kind"]), float(v["probability"]), bool(v["stub"]))
        for k, v in data.items()
    }


async def step_meaning(
    ws: str, text_ids: list[str], classes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    kinds = {k: str(v["kind"]) for k, v in classes.items()}
    r = await meaning.link_meaning(get_store(ws), text_ids, kinds, ws=ws)
    return {
        "texts": r.texts,
        "candidates": r.candidates,
        "kept": r.kept,
        "dropped": r.dropped,
        "stub": r.stub,
        "links": [link_to_dict(lk) for lk in r.links],
    }


async def step_decisions(
    ws: str, text_ids: list[str], classes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    store = get_store(ws)
    r = await decisions.link_decisions(
        store,
        text_ids,
        _classes(classes),
        ws=ws,
        bot_user_ids=_bot_users(store),
        keep_at=get_settings().LINK_KEEP_THRESHOLD,
    )
    return {
        "texts": r.texts,
        "extracted": r.extracted,
        "dropped": r.dropped,
        "approved": r.approved,
        "proposed": r.proposed,
        "superseded": r.superseded,
        "bot_skipped": r.bot_skipped,
        "tombstoned": r.tombstoned,
        "implemented": r.implemented,
        "decision_ids": r.decision_ids,
        "links": [link_to_dict(lk) for lk in r.links],
    }


async def step_checks(ws: str, links: list[dict[str, str]]) -> dict[str, Any]:
    r = await checks.check_links(get_store(ws), [link_from_dict(d) for d in links], ws=ws)
    return {
        "checked": r.checked,
        "kept": r.kept,
        "flagged": r.flagged,
        "deleted": r.deleted,
        "decisions_dropped": r.decisions_dropped,
        "stub": r.stub,
    }


def step_knowledge(ws: str) -> dict[str, Any]:
    r = knowledge.compute_knowledge(get_store(ws))
    return {
        "knows_about": r.knows_about,
        "removed": r.removed,
        "owns": r.owns,
        "codeowner_links": r.codeowner_links,
    }


async def step_procedures(
    ws: str, text_ids: list[str], classes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    store = get_store(ws)
    a = procedures.learn_from_prs(store)
    b = await procedures.learn_from_texts(store, text_ids, _classes(classes), ws=ws)
    return {
        "procedures": a.procedures + b.procedures,
        "learned_from_pr": a.learned_from_pr,
        "learned_from_text": b.learned_from_text,
    }


def finished_counts(steps: dict[str, dict[str, Any]]) -> dict[str, int]:
    """`linking.finished.counts` (A.C6)."""
    ref = steps.get("references", {})
    pend = steps.get("pending", {})
    mean = steps.get("meaning", {})
    chk = steps.get("checks", {})
    dec = steps.get("decisions", {})
    return {
        "references_resolved": int(ref.get("resolved", 0)) + int(pend.get("resolved", 0)),
        "pending": int(ref.get("pending", 0)),
        "decisions": int(dec.get("extracted", 0)),
        "identities": int(steps.get("identity", {}).get("accounts", 0)),
        "links_kept": int(mean.get("kept", 0)) - int(chk.get("deleted", 0)),
        "links_dropped": int(mean.get("dropped", 0)) + int(chk.get("deleted", 0)),
    }


Emit = Callable[..., Awaitable[None]]


async def run_linking(
    ws: str,
    changed_ids: list[str],
    *,
    run_id: str = "local",
    emit: Emit | None = None,
    caps: RunCaps | None = None,
    store: GraphStore | None = None,
) -> LinkingReport:
    """Run every step in order, in-process (tests, CLI). The Temporal workflow runs the same steps."""
    caps = caps or RunCaps()
    if store is not None:
        use_store(ws, store)
    report = LinkingReport(run_id=run_id)
    texts = references.text_ids_for_source(changed_ids)
    if len(texts) > caps.max_texts:
        report.capped = len(texts) - caps.max_texts
        texts = texts[: caps.max_texts]

    async def progress(step: str, done: int, total: int) -> None:
        if emit is not None:
            await emit(
                "linking.progress", {"runId": run_id, "step": step, "done": done, "total": total}
            )

    if any(label_of(i) in ACCOUNT_LABELS for i in changed_ids) or not changed_ids:
        report.steps["identity"] = step_identity(ws)
    await progress("identity", 1, 1)
    agg: dict[str, Any] = {}
    for n, batch in enumerate(batches(texts, caps.batch_size), 1):
        _merge(agg, step_references(ws, batch))
        await progress("references", n, len(batches(texts, caps.batch_size)))
    report.steps["references"] = agg
    report.steps["pending"] = step_resolve_pending(ws, sources_of(changed_ids))
    classes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, str]] = []
    total = len(batches(texts, caps.batch_size))
    for step in ("classify", "meaning", "decisions"):
        agg = {}
        for n, batch in enumerate(batches(texts, caps.batch_size), 1):
            if step == "classify":
                classes.update(await step_classify(ws, batch))
            elif step == "meaning":
                out = await step_meaning(ws, batch, classes)
                links += out.pop("links")
                _merge(agg, out)
            else:
                out = await step_decisions(ws, batch, classes)
                links += out.pop("links")
                out.pop("decision_ids", None)
                _merge(agg, out)
            await progress(step, n, total)
        report.steps[step] = agg if step != "classify" else {"texts": len(classes)}
    report.steps["checks"] = await step_checks(ws, links)
    await progress("checks", 1, 1)
    report.steps["knowledge"] = step_knowledge(ws)
    report.steps["procedures"] = await step_procedures(ws, texts, classes)
    await progress("procedures", 1, 1)
    report.stub = any(bool(s.get("stub")) for s in report.steps.values()) or any(
        bool(v.get("stub")) for v in classes.values()
    )
    report.counts = finished_counts(report.steps)
    if emit is not None:
        await emit("linking.finished", {"runId": run_id, "counts": report.counts})
    return report


def _merge(agg: dict[str, Any], out: dict[str, Any]) -> None:
    for k, v in out.items():
        if isinstance(v, bool):
            agg[k] = bool(agg.get(k)) or v
        elif isinstance(v, int | float):
            agg[k] = agg.get(k, 0) + v
