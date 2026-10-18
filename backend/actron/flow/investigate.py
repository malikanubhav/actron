"""Investigation of a request (spec B, B5): the agent when a model is configured, else the fallback pipeline.

Pipeline: `seeds_fulltext` (top 20) -> J5 rank (or the full-text score with a name match when J5 is a
stub) -> `shared_query` -> J6 per decision -> label -> J8 -> `write_questions` (template when stubbed).
Agent: the tool-calling loop in `investigator_agent`, then `shared_query(seedIds)` and the same J6, label,
J8 and question steps. If the agent fails twice the pipeline runs and `investigation.started` records the
reason. Both modes emit `tool.called`/`tool.result` for every graph query, `judgment.made` for every
batched judgment, `evidence.found` per piece of evidence and `investigation.completed`.
The result is written to the graph: `Investigation`, `HAS_INVESTIGATION`, `FOUND` (role, rank, path) and
`ABOUT` links to the seeds.

The freshness gate (B2) runs before this, in W6's workflow.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from actron.flow.findings import (
    Conflict,
    DecisionItem,
    Evidence,
    EvidenceRole,
    EvidenceSource,
    Findings,
    InvestigationResult,
    Label,
    NodeBrief,
    Question,
    QuestionOption,
    Tokens,
    graph_label,
    tier_for,
)
from actron.flow.labels import Thresholds, compute_label, conflict_label
from actron.graph import ids
from actron.graph import queries as Q
from actron.logging import get_logger
from actron.mcp_graph.tools import EventSink, ToolContext

log = get_logger(__name__)

SEED_TYPES = ["CodeFunction", "CodeClass", "CodeFile", "CodeComponent", "Feature"]
CANDIDATES = 20
J5_SEED_MIN = 2 / 3  # "directly involved in the change" or better
STUB_SEED_MIN = 0.45
STUB_MAX_SEEDS = 5
STUB_RESTRICTS_APPROVED = 0.5  # an approved decision that no model judged cannot be ruled out
MAX_EVIDENCE_EVENTS = 40
Mode = Literal["auto", "agent", "pipeline"]


# ------------------------------------------------------------------------------------------- judgments


@dataclass
class Verdict:
    value: float
    provider: str
    stub: bool
    answer: Any = None


class Judge(Protocol):
    """The model jobs the investigation needs. `ModelJudge` uses `actron.models`; tests pass fakes."""

    async def rank(self, request: str, candidates: Sequence[tuple[str, str]], *, ws: str,
                   request_id: str) -> list[Verdict]: ...

    async def conflict(self, request: str, decision: DecisionItem, *, ws: str, request_id: str) -> Verdict: ...

    async def needs_question(self, summary: str, conflicts: list[str], max_criticality: float, *, ws: str,
                             request_id: str) -> Verdict: ...

    async def questions(self, findings: dict[str, Any], *, ws: str, request_id: str) -> list[Question]: ...

    async def summary(self, findings: dict[str, Any], *, ws: str, request_id: str) -> str: ...


class ModelJudge:
    """J5, J6, J8 and the writing jobs through W4's model layer (Jev, LiteLLM, then stubs)."""

    async def rank(self, request: str, candidates: Sequence[tuple[str, str]], *, ws: str,
                   request_id: str) -> list[Verdict]:
        from actron.models import CandidateSummary, rank_candidates

        res = await rank_candidates(request, [CandidateSummary(id=i, summary=s) for i, s in candidates],
                                    ws=ws, request_id=request_id)
        return [Verdict(float(j.probability or 0.0), j.provider, j.stub, j.answer) for j in res]

    async def conflict(self, request: str, decision: DecisionItem, *, ws: str, request_id: str) -> Verdict:
        from actron.models import DecisionView, judge_conflict

        j = await judge_conflict(request, DecisionView(statement=decision.statement, quote=decision.quote,
                                                       status=decision.status), ws=ws, request_id=request_id)
        probs = j.probabilities or {}
        restricts = probs.get("restricts")
        if restricts is None:
            restricts = (j.probability or 0.0) if j.answer == "restricts" else 0.0
        return Verdict(float(restricts), j.provider, j.stub, j.answer)

    async def needs_question(self, summary: str, conflicts: list[str], max_criticality: float, *, ws: str,
                             request_id: str) -> Verdict:
        from actron.models import needs_question

        j = await needs_question(summary, conflicts, max_criticality, ws=ws, request_id=request_id)
        return Verdict(float(j.probability if j.probability is not None else 1.0), j.provider, j.stub, j.answer)

    async def questions(self, findings: dict[str, Any], *, ws: str, request_id: str) -> list[Question]:
        from actron.models import write_questions
        from actron.models.llm import available

        if not available("writing"):
            return template_questions(findings)
        out = await write_questions(findings, ws=ws, request_id=request_id)
        return [Question.model_validate(q.model_dump(exclude_none=True)) for q in out]

    async def summary(self, findings: dict[str, Any], *, ws: str, request_id: str) -> str:
        from actron.models import summarize_findings

        return str(await summarize_findings(findings, ws=ws, request_id=request_id))


def default_judge() -> Judge:
    try:
        import actron.models  # noqa: F401
    except ImportError:
        return TemplateJudge()
    return ModelJudge()


class TemplateJudge:
    """Used only when the model layer cannot be imported: every judgment is a marked stub."""

    async def rank(self, request: str, candidates: Sequence[tuple[str, str]], *, ws: str,
                   request_id: str) -> list[Verdict]:
        return [Verdict(0.0, "stub", True) for _ in candidates]

    async def conflict(self, request: str, decision: DecisionItem, *, ws: str, request_id: str) -> Verdict:
        return Verdict(0.0, "stub", True, "unrelated")

    async def needs_question(self, summary: str, conflicts: list[str], max_criticality: float, *, ws: str,
                             request_id: str) -> Verdict:
        return Verdict(1.0, "stub", True)

    async def questions(self, findings: dict[str, Any], *, ws: str, request_id: str) -> list[Question]:
        return template_questions(findings)

    async def summary(self, findings: dict[str, Any], *, ws: str, request_id: str) -> str:
        return template_summary(findings)


def _sentence(text: str) -> str:
    text = " ".join(text.split()).rstrip(".!? ")
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def template_questions(findings: Mapping[str, Any]) -> list[Question]:
    """One question per conflicting decision (max 3): the decision quoted, then "Should that still hold?"."""
    out: list[Question] = []
    for d in findings.get("decisions") or []:
        if (d.get("conflict") or {}).get("label") not in ("conflict", "possible_conflict"):
            continue
        statement = " ".join(str(d.get("statement") or "").split()).rstrip(".")
        out.append(Question(
            questionId=f"q{len(out) + 1}",
            text=f"The team decided: “{statement}.” Should that still hold after this change?",
            options=[QuestionOption(value="keep", label="Yes, keep it"),
                     QuestionOption(value="change", label="No, this request changes it")],
            evidenceIds=[str(d["id"])],
        ))
        if len(out) == 3:
            break
    return out


def template_summary(findings: Mapping[str, Any]) -> str:
    seeds = findings.get("seeds") or []
    decisions = findings.get("decisions") or []
    if not seeds and not decisions:
        return "Nothing in your history touches this."
    conflicts = [d for d in decisions if (d.get("conflict") or {}).get("label") != "none"]
    parts = []
    if conflicts:
        parts.append(f"{len(conflicts)} earlier decision{'s' if len(conflicts) != 1 else ''} may affect this "
                     f"request. The strongest is: {_sentence(str(conflicts[0].get('statement')))}.")
    else:
        parts.append("No earlier decision blocks this request.")
    callers = len((findings.get("impact") or {}).get("callers") or [])
    parts.append(f"{len(seeds)} place{'s' if len(seeds) != 1 else ''} in the code found; {callers} "
                 f"caller{'s' if callers != 1 else ''} may be affected.")
    return " ".join(parts)


# ------------------------------------------------------------------------------------------- helpers


async def _emit(emit: EventSink | None, type_: str, payload: dict[str, Any]) -> None:
    if emit is None:
        return
    try:
        await emit(type_, payload, actor="actron", surface="system")
    except Exception as exc:
        log.warning("investigation event emit failed", extra={"type": type_, "error": type(exc).__name__})


async def _traced(ctx: ToolContext, tool: str, args: dict[str, Any], fn: Callable[[], Any],
                  node_ids_of: Callable[[Any], list[str]]) -> Any:
    """Run a graph query in a thread and show it on the timeline as a tool call."""
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    await _emit(ctx.emit, "tool.called", {"callId": call_id, "tool": tool, "args": args, "by": ctx.by})
    started = time.monotonic()
    ctx.calls += 1
    try:
        out = await asyncio.to_thread(fn)
    except Exception as exc:
        await _emit(ctx.emit, "tool.result", {"callId": call_id, "ok": False, "summary": f"{tool} failed",
                                              "nodeIds": [], "durationMs": int((time.monotonic() - started) * 1000),
                                              "error": {"code": type(exc).__name__, "message": str(exc)[:300]}})
        raise
    found = node_ids_of(out)
    ctx.returned_ids.update(found)
    await _emit(ctx.emit, "tool.result", {"callId": call_id, "ok": True, "summary": f"{len(found)} results",
                                          "nodeIds": found[:200],
                                          "durationMs": int((time.monotonic() - started) * 1000)})
    return out


async def _shared_query(ctx: ToolContext, request_id: str, seeds: list[str], scores: Mapping[str, float],
                        *, trace: bool) -> Q.SharedQueryResult:
    steps: list[tuple[str, dict[str, Any], list[str], float, str | None]] = []

    def run() -> Q.SharedQueryResult:
        return Q.shared_query(ctx.store, request_id, seeds, scores,
                              record=(lambda *a: steps.append(a)) if trace else None)

    res = await asyncio.to_thread(run)
    for tool, args, node_ids, ms, err in steps:
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        ctx.calls += 1
        ctx.returned_ids.update(node_ids)
        await _emit(ctx.emit, "tool.called", {"callId": call_id, "tool": tool, "args": args, "by": ctx.by})
        payload: dict[str, Any] = {"callId": call_id, "ok": err is None,
                                   "summary": f"{len(node_ids)} results" if err is None else f"{tool} failed",
                                   "nodeIds": node_ids[:200], "durationMs": int(ms)}
        if err:
            payload["error"] = {"code": "query_failed", "message": err[:300]}
        await _emit(ctx.emit, "tool.result", payload)
    return res


def _providers(verdicts: Sequence[Verdict]) -> str:
    names = sorted({v.provider for v in verdicts})
    return names[0] if len(names) == 1 else ",".join(names) if names else "stub"


def _root_message(exc: BaseException) -> str:
    """The innermost error message (the MCP client wraps failures in exception groups)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return str(exc) or type(exc).__name__


def agent_available() -> bool:
    from actron.config import get_settings

    settings = get_settings()
    try:
        from actron.models.llm import available

        return bool(available("agent"))
    except ImportError:
        return bool(settings.MODEL_AGENT and settings.has_llm_key())


# ------------------------------------------------------------------------------------------- steps


async def find_seeds(ctx: ToolContext, text: str, judge: Judge, *, ws: str, request_id: str
                     ) -> tuple[list[str], dict[str, float], bool]:
    """Full-text candidates (top 20, non-test), ranked by J5; with a stubbed J5, by full-text score plus the
    share of the candidate's name the request mentions. Returns (seed ids, scores, stub)."""
    rows: list[Q.SeedRow] = await _traced(
        ctx, "search", {"query": text[:300], "types": SEED_TYPES, "limit": CANDIDATES},
        lambda: Q.seeds_fulltext(ctx.store, text, search_fields=ctx.fields(), types=SEED_TYPES,
                                 limit=CANDIDATES * 2),
        lambda rs: [r.id for r in rs],
    )
    # A name written in the request is the strongest signal; it stays even when it lives in test helpers.
    named = await _traced(
        ctx, "find_symbol", {"names": Q.explicit_identifiers(text)},
        lambda: Q.seeds_by_name(ctx.store, text),
        lambda rs: [r.id for r in rs],
    ) if Q.explicit_identifiers(text) else []
    named_ids = {r.id for r in named}
    rows = named + [r for r in rows if not r.isTest and r.id not in named_ids]
    rows = rows[:CANDIDATES]
    if not rows:
        return [], {}, True
    verdicts = await judge.rank(text, [(r.id, f"{r.type} {r.label}: {r.snippet}") for r in rows], ws=ws,
                                request_id=request_id)
    await _emit(ctx.emit, "judgment.made", {"job": "rank_candidates", "provider": _providers(verdicts),
                                            "count": len(verdicts), "what": "candidates"})
    stub = not verdicts or all(v.stub for v in verdicts)
    if not stub:
        scored = [
            (r.id, 1.0 if r.explicit else v.value)
            for r, v in zip(rows, verdicts, strict=False)
            if r.explicit or v.value >= J5_SEED_MIN - 1e-9
        ]
        scored.sort(key=lambda x: -x[1])
        return [i for i, _ in scored], dict(scored), False
    combined = sorted(
        ((r.id, 1.0 if r.explicit else round(0.6 * r.score + 0.4 * r.nameMatch, 4)) for r in rows),
        key=lambda x: -x[1],
    )
    picked = [(i, s) for i, s in combined if s >= STUB_SEED_MIN][:STUB_MAX_SEEDS]
    return [i for i, _ in picked], dict(picked), True


async def judge_decisions(findings: Findings, text: str, judge: Judge, th: Thresholds, emit: EventSink | None,
                          *, ws: str, request_id: str) -> bool:
    """J6 for every decision; sets `conflict` and re-sorts by probability then date. Returns True if stubbed."""
    if not findings.decisions:
        return False
    verdicts = await asyncio.gather(*(judge.conflict(text, d, ws=ws, request_id=request_id)
                                      for d in findings.decisions))
    await _emit(emit, "judgment.made", {"job": "judge_conflict", "provider": _providers(verdicts),
                                        "count": len(verdicts), "what": "decisions"})
    for d, v in zip(findings.decisions, verdicts, strict=True):
        p = v.value
        if v.stub and d.status == "approved":
            p = max(p, STUB_RESTRICTS_APPROVED)
        d.conflict = Conflict(label=conflict_label(p, th), probability=round(p, 4))
    findings.decisions.sort(key=lambda d: (-d.conflict.probability, _neg_time(d.decidedAt)))
    return all(v.stub for v in verdicts)


def _neg_time(at: str | None) -> float:
    if not at:
        return 0.0
    try:
        return -datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def label_for(findings: Findings, th: Thresholds) -> Label:
    return compute_label(
        restricts=[d.conflict.probability for d in findings.decisions],
        seed_count=len(findings.seeds),
        decision_count=len(findings.decisions),
        max_seed_criticality=max((c.percentile for c in findings.impact.criticality), default=None),
        thresholds=th,
    )


def build_evidence(findings: Findings, details: Mapping[str, NodeBrief]) -> list[Evidence]:
    """Evidence in priority order (conflicts, constraints, seeds, tests, similar work, owners, callers);
    one entry per node, `evidenceId` = node id, rank = position."""
    out: list[Evidence] = []
    seen: set[str] = set()

    def add(role: EvidenceRole, node_id: str, node_type: str, title: str, conf: float, path: list[str],
            quote: str | None = None, source: EvidenceSource | None = None) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        brief = details.get(node_id)
        src = source or EvidenceSource(type=node_type, id=node_id, url=brief.url if brief else None,
                                       author=brief.author if brief else None, at=brief.at if brief else None)
        conf = max(0.0, min(1.0, float(conf)))
        out.append(Evidence(evidenceId=node_id, role=role, nodeId=node_id, nodeType=node_type, title=title,
                            quote=quote, source=src, confidence=round(conf, 4), tier=tier_for(conf), path=path))

    for d in findings.decisions:
        brief = details.get(d.id)
        # The decision's brief carries its source's author and time (set by shared_query).
        source = (EvidenceSource(type=d.source.type, id=d.source.id, url=d.source.url,
                                 author=brief.author if brief else None,
                                 at=brief.at if brief else None) if d.source else None)
        if d.conflict.label != "none":
            add("conflict", d.id, "Decision", d.statement, d.conflict.probability, d.path, d.quote, source)
        else:
            conf = brief.confidence if brief and brief.confidence is not None else 0.5
            add("constraint", d.id, "Decision", d.statement, conf, d.path, d.quote, source)
    for s in findings.seeds:
        brief = details.get(s.id)
        add("impact", s.id, s.type, brief.title if brief else s.id, s.score, s.path)
    for t in findings.impact.tests:
        brief = details.get(t.id)
        add("test", t.id, "CodeFunction", brief.title if brief else t.id,
            brief.confidence if brief and brief.confidence is not None else 0.8, t.path)
    for r in findings.relatedWork:
        add("similar_work", r.id, r.type, r.title, 1.0 if len(r.path) <= 3 else 0.8, r.path)
    for o in findings.owners:
        if o.personId:
            add("owner", o.personId, "Person", o.name, o.score, o.path)
    for c in findings.impact.callers:
        brief = details.get(c.id)
        add("impact", c.id, "CodeFunction", brief.title if brief else c.id, max(0.5, 1.0 - 0.15 * (c.depth - 1)),
            c.path)
    return out


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _callers_phrase(store: Any, fn_id: str, fallback: int) -> str:
    """'is called from 5 functions and 964 tests', read from the graph; the impact count when unavailable."""
    if store is not None:
        try:
            rows = store.query(
                "MATCH (f:CodeFunction {id: $id})<-[:CALLS]-(c:CodeFunction) "
                "WHERE coalesce(c.deleted, false) = false "
                "RETURN coalesce(c.isTest, false) AS test, count(DISTINCT c) AS n",
                {"id": fn_id}, read_only=True, timeout_ms=2000,
            )
            counts = {bool(r["test"]): int(r["n"]) for r in rows}
            code, tests = counts.get(False, 0), counts.get(True, 0)
            if code or tests:
                parts = [_plural(code, "function")] if code else []
                parts += [_plural(tests, "test")] if tests else []
                return "is called from " + " and ".join(parts)
        except Exception as exc:
            log.debug("caller counts unavailable", extra={"error": str(exc)})
    return f"is used by {_plural(fallback, 'other function')}"


async def make_questions(findings: Findings, text: str, kind: str, label: Label, judge: Judge,
                         emit: EventSink | None, *, ws: str, request_id: str,
                         store: Any = None) -> tuple[list[Question], bool]:
    """J8, then evidence-tied questions (at most 3) when product input is needed. Returns (questions, stub)."""
    if kind == "question" or label not in ("conflict", "possible_conflict"):
        return [], False
    conflicts = [d.statement for d in findings.decisions if d.conflict.label != "none"]
    max_crit = max((c.percentile for c in findings.impact.criticality), default=0.0)
    summary = template_summary(findings.to_json())
    need = await judge.needs_question(summary, conflicts, max_crit, ws=ws, request_id=request_id)
    await _emit(emit, "judgment.made", {"job": "needs_question", "provider": need.provider, "count": 1,
                                        "what": "findings"})
    if need.value < 0.5 and label != "conflict":
        return [], need.stub
    data = {**findings.to_json(), "requestText": text}
    questions = await judge.questions(data, ws=ws, request_id=request_id)
    known = findings.node_ids()
    kept: list[Question] = []
    for q in questions:
        q.evidenceIds = [e for e in q.evidenceIds if e in known]
        if q.evidenceIds:
            kept.append(q)
    if not kept and not conflicts and findings.impact.criticality:
        top = max(findings.impact.criticality, key=lambda c: c.percentile)
        name = top.id.rsplit("::", 1)[-1]
        kept.append(Question(
            questionId="q1",
            text=f"{name} {_callers_phrase(store, top.id, len(findings.impact.callers))}. Should its current "
                 "behaviour stay the same for them?",
            options=[QuestionOption(value="keep", label="Yes, keep current behaviour"),
                     QuestionOption(value="change", label="No, callers may change too")],
            evidenceIds=[top.id],
        ))
    for i, q in enumerate(kept[:3]):
        q.questionId = q.questionId or f"q{i + 1}"
    return kept[:3], need.stub


# ------------------------------------------------------------------------------------------- graph writes


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_investigation(store: Any, request_id: str, text: str, kind: str, investigation_id: str,
                        result: InvestigationResult, started_at: str, finished_at: str) -> None:
    """Investigation node, HAS_INVESTIGATION, ABOUT (request -> seeds) and FOUND (role, rank, path)."""
    from actron.graph.store import LinkRow

    rid = Q.request_graph_id(request_id)
    if store.get_node(rid) is None:
        # W6 mirrors the request into the graph; if it has not yet, create the minimal node (MERGE on id).
        store.upsert_nodes("Request", [{"id": rid, "kind": kind if kind in ("feature", "bug", "question") else "feature",
                                        "title": " ".join(text.split())[:80] or "Request", "text": text,
                                        "state": "Investigating", "createdAt": started_at}])
    store.upsert_nodes("Investigation", [{
        "id": investigation_id, "summary": result.summary, "conflictLabel": graph_label(result.label),
        "toolCallCount": result.tool_calls, "startedAt": started_at, "finishedAt": finished_at,
    }])
    store.upsert_links("HAS_INVESTIGATION", "Request", "Investigation",
                       [LinkRow(rid, investigation_id, {"method": "structural", "confidence": 1.0})])
    about: dict[str, list[Any]] = {}
    for s in result.findings.seeds:
        if s.type in Q.CONSTRAINABLE:
            about.setdefault(s.type, []).append(LinkRow(rid, s.id, {"method": "inferred",
                                                                    "confidence": round(min(1.0, s.score), 4)}))
    for label, rows in about.items():
        store.upsert_links("ABOUT", "Request", label, rows)
    evidence_group = set(store.ontology.groups.get("Evidence", []))
    found: dict[str, list[Any]] = {}
    for rank, ev in enumerate(result.evidence, start=1):
        if ev.nodeType not in evidence_group:
            continue  # people and owners are not Evidence nodes in the ontology; they stay in the findings
        found.setdefault(ev.nodeType, []).append(LinkRow(investigation_id, ev.nodeId, {
            "method": "inferred", "confidence": ev.confidence, "role": ev.role, "rank": rank, "path": ev.path,
        }))
    for label, rows in found.items():
        store.upsert_links("FOUND", "Investigation", label, rows)


# ------------------------------------------------------------------------------------------- entry point


async def investigate(
    ws: str,
    request_id: str,
    text: str,
    kind: str,
    *,
    emit: EventSink,
    mode: Mode = "auto",
    store: Any | None = None,
    judge: Judge | None = None,
    complete: Any | None = None,
    thresholds: Thresholds | None = None,
    write: bool = True,
) -> InvestigationResult:
    """Investigate one request and return the findings, label, summary, evidence and questions."""
    from actron.flow import investigator_agent as agent

    if store is None:
        from actron.graph.store import store_for

        store = store_for(ws)
    judge = judge or default_judge()
    th = thresholds or Thresholds.from_settings()
    started_at = _now()
    investigation_id = ids.investigation(f"inv_{uuid.uuid4().hex[:20]}")
    ctx = ToolContext(ws=ws, store=store, emit=emit, by="investigator")
    reason: str | None = None
    if mode == "auto":
        mode = "agent" if (complete is not None or agent_available()) else "pipeline"
        if mode == "pipeline":
            reason = "No agent model is configured, so the deterministic pipeline ran."
    stubs: list[bool] = []
    tokens = Tokens()
    model = ""
    outcome: agent.AgentOutcome | None = None

    if mode == "agent":
        await _emit(emit, "investigation.started", {"mode": "agent"})
        from actron.mcp_graph.server import graph_client

        completion = complete
        if completion is None:
            from actron.models import agent_completion

            completion = agent_completion
        failures: list[str] = []
        for _attempt in range(2):
            try:
                async with graph_client(ctx) as client:
                    outcome = await agent.run_agent(text, kind, client=client, returned_ids=ctx.returned_ids,
                                                    complete=completion, ws=ws, request_id=request_id)
                break
            except Exception as exc:  # AgentFailed, model errors, MCP errors
                failures.append(_root_message(exc)[:300])
                log.warning("investigator agent failed", extra={"request_id": request_id, "error": str(exc)[:200]})
        if outcome is None:
            reason = f"The agent failed twice ({failures[-1] if failures else 'unknown error'}), so the pipeline ran."
            mode = "pipeline"
            await _emit(emit, "investigation.started", {"mode": "pipeline", "reason": reason})
        else:
            tokens = Tokens(input=outcome.tokens.get("input", 0), output=outcome.tokens.get("output", 0))
            model = outcome.model
            stubs.append(outcome.stub)
    else:
        payload: dict[str, Any] = {"mode": "pipeline"}
        if reason:
            payload["reason"] = reason
        await _emit(emit, "investigation.started", payload)

    if outcome is not None:
        seeds = outcome.seed_ids
        scores: dict[str, float] = {s: round(1.0 - i * 0.05, 4) for i, s in enumerate(seeds)}
        if len(seeds) > 1:  # J5 (PRD 10.2a): Jev scores every set of seeds worth ordering, however small
            nodes = await asyncio.to_thread(Q.fetch_nodes, store, seeds, Q.SHARED_TIMEOUT_MS)
            verdicts = await judge.rank(text, [(s, Q.display_label(nodes.get(s, {"id": s}))) for s in seeds],
                                        ws=ws, request_id=request_id)
            await _emit(emit, "judgment.made", {"job": "rank_candidates", "provider": _providers(verdicts),
                                                "count": len(verdicts), "what": "candidates"})
            if not all(v.stub for v in verdicts):
                scores = {s: round(v.value, 4) for s, v in zip(seeds, verdicts, strict=False)}
            stubs.append(all(v.stub for v in verdicts))
        sq = await _shared_query(ctx, request_id, seeds, scores, trace=False)
    else:
        seeds, scores, rank_stub = await find_seeds(ctx, text, judge, ws=ws, request_id=request_id)
        stubs.append(rank_stub)
        sq = await _shared_query(ctx, request_id, seeds, scores, trace=True)

    findings = sq.findings
    stubs.append(await judge_decisions(findings, text, judge, th, emit, ws=ws, request_id=request_id))
    findings.label = label_for(findings, th)
    questions, q_stub = await make_questions(findings, text, kind, findings.label, judge, emit, ws=ws,
                                             request_id=request_id, store=ctx.store)
    stubs.append(q_stub)
    summary = await judge.summary({**findings.to_json(), "requestText": text}, ws=ws, request_id=request_id)
    evidence = build_evidence(findings, sq.details)
    for ev in evidence[:MAX_EVIDENCE_EVENTS]:
        await _emit(emit, "evidence.found", {
            "evidenceId": ev.evidenceId, "role": ev.role, "nodeId": ev.nodeId, "nodeType": ev.nodeType,
            "quote": ev.quote, "source": ev.source.model_dump(include={"type", "url", "author", "at"}),
            "confidence": ev.confidence, "path": ev.path,
        })
    cost = 0.0
    if model and (tokens.input or tokens.output):
        try:
            from actron.models.usage import cost_for

            cost = cost_for(model, tokens.input, tokens.output)
        except ImportError:
            cost = 0.0
    result = InvestigationResult(
        findings=findings, label=findings.label, summary=summary, mode=mode, tool_calls=ctx.calls, tokens=tokens,
        cost_usd=cost, stub=any(stubs), evidence=evidence, questions=questions,
        investigation_id=investigation_id, fallback_reason=reason,
    )
    finished_at = _now()
    if write:
        await asyncio.to_thread(write_investigation, store, request_id, text, kind, investigation_id, result,
                                started_at, finished_at)
    await _emit(emit, "investigation.completed", {
        "label": findings.label, "summary": summary,
        "counts": {"decisions": len(findings.decisions), "relatedWork": len(findings.relatedWork),
                   "callers": len(findings.impact.callers), "tests": len(findings.impact.tests)},
        "findingsRef": investigation_id,
    })
    return result
