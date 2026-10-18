"""One function per model job (spec A, A13; PRD 10.1, 10.2a).

Judgments (J1-J10): Jev -> LiteLLM (`MODEL_DECISION`, same options, JSON) -> conservative stub.
Texts: LiteLLM (`MODEL_DECISION` extraction, `MODEL_WRITING` writing) -> deterministic template.
Every call writes a `model_calls` row; Jev and LLM judgments are cached in Redis, stubs never.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from actron.logging import get_logger
from actron.models import cache, jev, llm, questions, stubs, usage
from actron.models.questions import JevAsk
from actron.models.types import (
    Answer,
    Candidate,
    CandidateSummary,
    ConstraintItem,
    DecisionExtraction,
    DecisionView,
    EvidenceItem,
    InvalidModelOutput,
    Judgment,
    ModelError,
    Provider,
    Question,
    QuestionOption,
    TestPlanItem,
    Ticket,
)

log = get_logger(__name__)
PROMPTS = Path(__file__).parent / "prompts"


@lru_cache(maxsize=32)
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    text = prompt(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, default=str)


# Judgments


def _judgment_from(
    job: str,
    ask: JevAsk,
    qid: str,
    ans: jev.JevAnswer,
    model: str,
    provider: Provider,
    cached: bool,
) -> Judgment:
    prob: float | None
    if ans.type == "noul":
        prob = max(0.0, min(1.0, float(ans.value)))
        answer: Any = prob >= 0.5
    elif ans.type == "choice":
        prob = (ans.probabilities or {}).get(str(ans.value))
        answer = ans.value
    else:
        levels = len(ask.questions[qid].get("criteria") or []) or 2
        answer = float(ans.value)
        prob = max(0.0, min(1.0, answer / (levels - 1)))
    return Judgment(
        job=job,
        answer=answer,
        probability=prob,
        probabilities=ans.probabilities,
        confidence=ans.confidence,
        model=model,
        provider=provider,
        cached=cached,
        stub=False,
    )


def _serialise(answers: Mapping[str, jev.JevAnswer]) -> dict[str, Any]:
    return {
        qid: {
            "type": a.type,
            "value": a.value,
            "probabilities": a.probabilities,
            "confidence": a.confidence,
        }
        for qid, a in answers.items()
    }


def _deserialise(data: Mapping[str, Any]) -> dict[str, jev.JevAnswer]:
    return {
        qid: jev.JevAnswer(v["type"], v["value"], v.get("probabilities"), v.get("confidence"))
        for qid, v in data.items()
    }


def _validate_llm_answers(ask: JevAsk) -> Any:
    """Validator for the LLM fallback: Jev's answer shape, values inside the allowed options."""

    def check(data: dict[str, Any]) -> dict[str, jev.JevAnswer]:
        raw = data.get("answers", data)
        if not isinstance(raw, dict):
            raise InvalidModelOutput("answers must be an object")
        out: dict[str, jev.JevAnswer] = {}
        for qid, q in ask.questions.items():
            item = raw.get(qid)
            if isinstance(item, dict) and "type" not in item:
                item = {"type": q["type"], **item}
            try:
                ans = jev.parse_answer(qid, q["type"], item)
            except jev.JevResponseError as exc:
                if (
                    q["type"] == "choice"
                    and isinstance(item, dict)
                    and isinstance(item.get("choice"), str)
                ):
                    ans = jev.JevAnswer("choice", item["choice"], {item["choice"]: 1.0}, None)
                else:
                    raise InvalidModelOutput(str(exc)) from exc
            if ans.type == "noul" and not 0.0 <= float(ans.value) <= 1.0:
                raise InvalidModelOutput(f"{qid}: probability outside 0..1")
            if ans.type == "choice" and ans.value not in q["criteria"]:
                raise InvalidModelOutput(
                    f"{qid}: {ans.value!r} is not one of {sorted(q['criteria'])}"
                )
            if ans.type == "score" and not 0.0 <= float(ans.value) <= len(q["criteria"]) - 1:
                raise InvalidModelOutput(f"{qid}: score outside the levels")
            out[qid] = ans
        return out

    return check


async def judge(
    ask: JevAsk, *, ws: str | None = None, request_id: str | None = None
) -> dict[str, Judgment]:
    """Answer every question of one request: Jev, then the LLM fallback, then the stub."""
    job = ask.job
    if jev.available():
        model = jev.model_name()
        key = cache.key_for(job, f"jev:{model}", ask.state, ask.questions)
        hit = await cache.get(key)
        if hit is not None:
            await usage.record(
                usage.UsageRow(
                    job=job,
                    provider="jev",
                    model=hit["model"],
                    workspace_id=ws,
                    request_id=request_id,
                    cached=True,
                )
            )
            answers = _deserialise(hit["answers"])
            return {
                q: _judgment_from(job, ask, q, a, hit["model"], "jev", True)
                for q, a in answers.items()
            }
        started = time.monotonic()
        try:
            resp = await jev.ask(ask, model=model)
        except (jev.JevError, ModelError) as exc:
            await usage.record(
                usage.UsageRow(
                    job=job,
                    provider="jev",
                    model=model,
                    workspace_id=ws,
                    request_id=request_id,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
            )
            log.warning("jev failed; falling back", extra={"job": job, "error": type(exc).__name__})
        else:
            await usage.record(
                usage.UsageRow(
                    job=job,
                    provider="jev",
                    model=resp.model,
                    workspace_id=ws,
                    request_id=request_id,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    latency_ms=resp.latency_ms,
                )
            )
            await cache.put(key, {"model": resp.model, "answers": _serialise(resp.answers)})
            return {
                q: _judgment_from(job, ask, q, a, resp.model, "jev", False)
                for q, a in resp.answers.items()
            }

    models = llm.chain("decision")
    if models:
        key = cache.key_for(job, f"llm:{models[0]}", ask.state, ask.questions)
        hit = await cache.get(key)
        if hit is not None:
            await usage.record(
                usage.UsageRow(
                    job=job,
                    provider="llm",
                    model=hit["model"],
                    workspace_id=ws,
                    request_id=request_id,
                    cached=True,
                )
            )
            answers = _deserialise(hit["answers"])
            return {
                q: _judgment_from(job, ask, q, a, hit["model"], "llm", True)
                for q, a in answers.items()
            }
        messages = [
            {
                "role": "user",
                "content": render(
                    "judgment", input=_dump({"state": ask.state, "questions": ask.questions})
                ),
            }
        ]
        try:
            answers, used = await llm.complete_json(
                "decision",
                messages,
                _validate_llm_answers(ask),
                job=job,
                ws=ws,
                request_id=request_id,
            )
        except ModelError as exc:
            log.warning(
                "llm judgment failed; using stub", extra={"job": job, "error": type(exc).__name__}
            )
        else:
            await cache.put(key, {"model": used, "answers": _serialise(answers)})
            return {
                q: _judgment_from(job, ask, q, a, used, "llm", False) for q, a in answers.items()
            }

    await usage.record(
        usage.UsageRow(
            job=job,
            provider="stub",
            model=stubs.STUB_MODEL,
            workspace_id=ws,
            request_id=request_id,
            stub=True,
        )
    )
    return stubs.stub_judgments(ask)


async def _one(ask: JevAsk, qid: str, ws: str | None, request_id: str | None) -> Judgment:
    return (await judge(ask, ws=ws, request_id=request_id))[qid]


async def classify_message(
    text: str,
    source: str,
    thread_parent_text: str | None,
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Judgment:
    """J1."""
    return await _one(
        questions.j1_classify_message(text, source, thread_parent_text), "kind", ws, request_id
    )


async def is_approval(
    decision: str,
    reply: str,
    same_author: bool,
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Judgment:
    """J2."""
    return await _one(
        questions.j2_is_approval(decision, reply, same_author), "approves", ws, request_id
    )


async def judge_link(
    text: str, candidate: Candidate, *, ws: str | None = None, request_id: str | None = None
) -> Judgment:
    """J3 (one candidate)."""
    return await _one(questions.j3_judge_link(text, candidate), "refers", ws, request_id)


async def judge_links(
    text: str, candidates: list[Candidate], *, ws: str | None = None, request_id: str | None = None
) -> list[Judgment]:
    """J3 batched: one Jev request per text, one judgment per candidate, in order."""
    if not candidates:
        return []
    ask = questions.j3_judge_links(text, candidates)
    result = await judge(ask, ws=ws, request_id=request_id)
    if len(candidates) == 1:
        return [result["refers"]]
    return [result[f"c{i}"] for i in range(len(candidates))]


async def check_link(
    quote: str, claim: str, *, ws: str | None = None, request_id: str | None = None
) -> Judgment:
    """J4."""
    return await _one(questions.j4_check_link(quote, claim), "supported", ws, request_id)


async def rank_candidates(
    request: str,
    candidates: list[CandidateSummary],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> list[Judgment]:
    """J5: one request, one score per candidate (first 20), in order."""
    items = candidates[: questions.MAX_RANK_CANDIDATES]
    if not items:
        return []
    result = await judge(questions.j5_rank_candidates(request, items), ws=ws, request_id=request_id)
    return [result[f"c{i}"] for i in range(len(items))]


async def judge_conflict(
    request: str, decision: DecisionView, *, ws: str | None = None, request_id: str | None = None
) -> Judgment:
    """J6."""
    return await _one(questions.j6_judge_conflict(request, decision), "relation", ws, request_id)


async def judge_supersession(
    earlier: Mapping[str, Any],
    later: Mapping[str, Any],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Judgment:
    """J6-style choice used by decision linking (A12.4 SUPERSEDES)."""
    ask = questions.j6b_judge_supersession(dict(earlier), dict(later))
    return await _one(ask, "relation", ws, request_id)


async def classify_request(
    text: str, *, ws: str | None = None, request_id: str | None = None
) -> Judgment:
    """J7."""
    return await _one(questions.j7_classify_request(text), "kind", ws, request_id)


async def needs_question(
    summary: str,
    conflicts: list[str],
    max_criticality: float,
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Judgment:
    """J8."""
    return await _one(
        questions.j8_needs_question(summary, conflicts, max_criticality),
        "needs_input",
        ws,
        request_id,
    )


async def is_scope_change(
    ticket: dict[str, Any],
    diff_summary: str,
    outside_files: list[str],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Judgment:
    """J9."""
    ask = questions.j9_is_scope_change(ticket, diff_summary, outside_files)
    return await _one(ask, "scope_change", ws, request_id)


async def feedback_kind(
    feedback: str, ticket: dict[str, Any], *, ws: str | None = None, request_id: str | None = None
) -> Judgment:
    """J10."""
    return await _one(questions.j10_feedback_kind(feedback, ticket), "kind", ws, request_id)


# Text jobs


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Exact-substring check (A-AC-84). Only surrounding whitespace of the quote is forgiven."""
    q = quote.strip()
    if not q:
        return None
    start = text.find(q)
    if start < 0:
        return None
    return start, start + len(q)


async def extract_decision(
    text: str, *, ws: str | None = None, request_id: str | None = None
) -> DecisionExtraction | None:
    """LLM extraction with a strict shape. Returns None when there is no decision, no model, or the
    quote is
    not an exact substring of `text` after one retry (A12.4)."""

    def validate(data: dict[str, Any]) -> DecisionExtraction:
        if not isinstance(data.get("is_decision"), bool):
            raise InvalidModelOutput("is_decision must be true or false")
        if not data["is_decision"]:
            return DecisionExtraction(is_decision=False, statement="", quote="")
        statement = str(data.get("statement") or "").strip()
        quote = str(data.get("quote") or "")
        span = find_quote(text, quote)
        if not statement:
            raise InvalidModelOutput("statement is empty")
        if span is None:
            raise InvalidModelOutput(
                "quote is not an exact substring of the message; copy the words exactly"
            )
        hint = data.get("status_hint")
        return DecisionExtraction(
            is_decision=True,
            statement=statement,
            quote=text[span[0] : span[1]],
            scope=str(data.get("scope") or ""),
            status_hint="decided" if hint == "decided" else "proposed",
            quote_span=span,
        )

    schema = {
        "type": "object",
        "properties": {
            "is_decision": {"type": "boolean"},
            "statement": {"type": "string"},
            "quote": {"type": "string"},
            "scope": {"type": "string"},
            "status_hint": {"type": "string", "enum": ["decided", "proposed"]},
        },
        "required": ["is_decision", "statement", "quote", "scope", "status_hint"],
        "additionalProperties": False,
    }
    if not llm.available("decision"):
        await usage.record(
            usage.UsageRow(
                job="extract_decision",
                provider="stub",
                model=stubs.STUB_MODEL,
                workspace_id=ws,
                request_id=request_id,
                stub=True,
            )
        )
        return None
    messages = [{"role": "user", "content": render("decision_extraction", text=text)}]
    try:
        result, model = await llm.complete_json(
            "decision",
            messages,
            validate,
            job="extract_decision",
            ws=ws,
            request_id=request_id,
            json_schema=schema,
        )
    except ModelError as exc:
        log.info("decision extraction dropped", extra={"error": str(exc)[:200]})
        return None
    if not result.is_decision:
        return None
    return result.model_copy(update={"model": model, "provider": "llm"})


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped: dict[str, Any] = value.model_dump(mode="json", by_alias=True)
        return dumped
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _ids_in(findings: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, Mapping):
            for k, x in v.items():
                if k in ("id", "personId", "decisionId") and isinstance(x, str):
                    out.add(x)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(findings)
    return out


def _sentence(text: str, limit: int = 140) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0] if text.strip() else ""
    first = first.rstrip(".!? ")
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def template_questions(findings: Mapping[str, Any]) -> list[Question]:
    """Template questions when the LLM is stubbed (spec B, B5): one per conflict, at most 3."""
    request = str(findings.get("requestText") or findings.get("request") or "")
    target = _lower_first(_sentence(request, 80)) if request else "this request"
    out: list[Question] = []
    decisions = sorted(
        findings.get("decisions") or [],
        key=lambda d: -float(((d.get("conflict") or {}).get("probability")) or 0.0),
    )
    for d in decisions:
        label = (d.get("conflict") or {}).get("label")
        if label not in ("conflict", "possible_conflict") or not d.get("id"):
            continue
        statement = _lower_first(_sentence(str(d.get("statement") or "the earlier decision")))
        out.append(
            Question(
                questionId=f"q{len(out) + 1}",
                text=f"Should {statement} still hold for {target}?",
                kind="choice",
                options=[
                    QuestionOption(value="keep", label="Yes, keep it"),
                    QuestionOption(value="change", label="No, this request changes it"),
                ],
                evidenceIds=[str(d["id"])],
            )
        )
        if len(out) == 3:
            break
    return out


async def write_questions(
    findings: Any, *, ws: str | None = None, request_id: str | None = None
) -> list[Question]:
    data = _as_dict(findings)
    known = _ids_in(data)

    def validate(raw: dict[str, Any]) -> list[Question]:
        items = raw.get("questions")
        if not isinstance(items, list):
            raise InvalidModelOutput("questions must be a list")
        qs = [Question.model_validate(i) for i in items[:3]]
        for i, q in enumerate(qs):
            q.questionId = q.questionId or f"q{i + 1}"
            q.evidenceIds = [e for e in q.evidenceIds if e in known]
        return qs

    if llm.available("writing"):
        try:
            result, _ = await llm.complete_json(
                "writing",
                [{"role": "user", "content": render("questions", findings=_dump(data))}],
                validate,
                job="write_questions",
                ws=ws,
                request_id=request_id,
            )
            return result
        except ModelError as exc:
            log.warning(
                "write_questions fell back to the template", extra={"error": type(exc).__name__}
            )
    await usage.record(
        usage.UsageRow(
            job="write_questions",
            provider="stub",
            model=stubs.STUB_MODEL,
            workspace_id=ws,
            request_id=request_id,
            stub=True,
        )
    )
    return template_questions(data)


def template_ticket(request: str, findings: Mapping[str, Any], answers: Sequence[Any]) -> Ticket:
    """Deterministic ticket when the LLM is stubbed (spec B, B7)."""
    answer_map = {str(a.get("questionId")): a for a in (_as_dict(x) for x in answers)}
    branch = str(
        (answer_map.get("target_branch") or {}).get("value")
        or findings.get("workingBranch")
        or "main"
    )
    lifted = {
        e
        for a in answer_map.values()
        if str(a.get("value")) == "change"
        for e in (a.get("evidenceIds") or [])
    }
    decisions = [
        d for d in findings.get("decisions") or [] if d.get("status") == "approved" and d.get("id")
    ]
    constraints = [
        ConstraintItem(text=str(d.get("statement") or ""), evidenceIds=[str(d["id"])])
        for d in decisions
        if str(d["id"]) not in lifted
    ]
    seeds = [
        str(s["id"])
        for s in findings.get("seeds") or []
        if str(s.get("id", "")).startswith("code:fn:")
    ]
    impact = findings.get("impact") or {}
    tests = [
        TestPlanItem(kind="existing", target=str(t["id"]), command=str(t.get("command") or ""))
        for t in impact.get("tests") or []
        if t.get("id")
    ]
    procs = findings.get("procedures") or []
    command = next((str(p["testCommand"]) for p in procs if p.get("testCommand")), "")
    if command:
        tests = [t.model_copy(update={"command": t.command or command}) for t in tests]
    objective = _sentence(request) or "Make the requested change"
    n_dec = len(findings.get("decisions") or [])
    context = (
        f"The request touches {len(seeds)} function{'s' if len(seeds) != 1 else ''} "
        "found in the code graph. "
        + ("No earlier decision relates to it." if n_dec == 0
           else "1 earlier decision relates to it." if n_dec == 1
           else f"{n_dec} earlier decisions relate to it.")
    )
    return Ticket(
        objective=objective + ".",
        context=context,
        acceptanceCriteria=[
            f"Given the current code, when the change is made, then {_lower_first(objective)}."
        ],
        constraintsToPreserve=constraints,
        affectedFunctions=seeds,
        testPlan=tests,
        outOfScope=["Changes not needed for the objective."],
        targetBranch=branch,
        stub=True,
    )


async def write_ticket(
    request: str,
    findings: Any,
    answers: Sequence[Any],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Ticket:
    data = _as_dict(findings)
    known = _ids_in(data)
    answer_dicts = [_as_dict(a) for a in answers]

    def validate(raw: dict[str, Any]) -> Ticket:
        ticket = Ticket.model_validate(raw)
        ticket.affectedFunctions = [f for f in ticket.affectedFunctions if f in known]
        for c in ticket.constraintsToPreserve:
            c.evidenceIds = [e for e in c.evidenceIds if e in known]
        return ticket

    if llm.available("writing"):
        payload = {
            "request": request,
            "findings": data,
            "answers": answer_dicts,
            "workingBranch": data.get("workingBranch") or "main",
        }
        try:
            result, _ = await llm.complete_json(
                "writing",
                [{"role": "user", "content": render("ticket", input=_dump(payload))}],
                validate,
                job="write_ticket",
                ws=ws,
                request_id=request_id,
            )
            return result
        except ModelError as exc:
            log.warning(
                "write_ticket fell back to the template", extra={"error": type(exc).__name__}
            )
    await usage.record(
        usage.UsageRow(
            job="write_ticket",
            provider="stub",
            model=stubs.STUB_MODEL,
            workspace_id=ws,
            request_id=request_id,
            stub=True,
        )
    )
    return template_ticket(request, data, answer_dicts)


def template_answer(question: str, evidence: Sequence[EvidenceItem]) -> Answer:
    if not evidence:
        return Answer(text="Nothing in your history answers this yet.", evidenceIds=[], stub=True)
    lines = ["This is what your history holds about it."]
    for item in evidence[:5]:
        snippet = _sentence(item.text, 160) if item.text else item.type or "record"
        lines.append(f"{snippet}. [{item.id}]")
    return Answer(text=" ".join(lines), evidenceIds=[e.id for e in evidence[:5]], stub=True)


async def write_answer(
    question: str,
    evidence: list[EvidenceItem],
    *,
    ws: str | None = None,
    request_id: str | None = None,
) -> Answer:
    known = {e.id for e in evidence}

    def validate(raw: dict[str, Any]) -> Answer:
        ans = Answer.model_validate(
            {"text": raw.get("text"), "evidenceIds": raw.get("evidenceIds") or []}
        )
        if not ans.text.strip():
            raise InvalidModelOutput("text is empty")
        ans.evidenceIds = [e for e in ans.evidenceIds if e in known]
        return ans

    if llm.available("writing"):
        ev = _dump([e.model_dump() for e in evidence])
        try:
            result, _ = await llm.complete_json(
                "writing",
                [{"role": "user", "content": render("answer", question=question, evidence=ev)}],
                validate,
                job="write_answer",
                ws=ws,
                request_id=request_id,
            )
            return result
        except ModelError as exc:
            log.warning(
                "write_answer fell back to the template", extra={"error": type(exc).__name__}
            )
    await usage.record(
        usage.UsageRow(
            job="write_answer",
            provider="stub",
            model=stubs.STUB_MODEL,
            workspace_id=ws,
            request_id=request_id,
            stub=True,
        )
    )
    return template_answer(question, evidence)


_NUMBER_WORDS = [
    "No",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
]


def _count(n: int, noun: str) -> str:
    word = _NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else str(n)
    return f"{word} {noun}{'' if n == 1 else 's'}"


def template_summary(findings: Mapping[str, Any]) -> str:
    decisions = findings.get("decisions") or []
    seeds = findings.get("seeds") or []
    label = findings.get("label")
    conflicts = [
        d
        for d in decisions
        if (d.get("conflict") or {}).get("label") in ("conflict", "possible_conflict")
    ]
    if not seeds and not decisions:
        return "Nothing in your history touches this. Safe to continue."
    parts: list[str] = []
    if conflicts:
        parts.append(
            f"{_count(len(conflicts), 'earlier decision')} "
            f"affect{'s' if len(conflicts) == 1 else ''} "
            "this request."
        )
        top = conflicts[0].get("statement")
        if top:
            parts.append(f"The strongest is: {_sentence(str(top))}.")
    elif label == "clear" or decisions:
        parts.append("No earlier decision blocks this request.")
    impact = findings.get("impact") or {}
    callers = len(impact.get("callers") or [])
    tests = len(impact.get("tests") or [])
    parts.append(
        f"{_count(len(seeds), 'function')} found; "
        f"{callers} caller{'s' if callers != 1 else ''} and "
        f"{tests} test{'s' if tests != 1 else ''} may be affected."
    )
    return " ".join(parts)


async def summarize_findings(
    findings: Any, *, ws: str | None = None, request_id: str | None = None
) -> str:
    data = _as_dict(findings)
    if llm.available("writing"):
        try:
            text, _ = await llm.complete_text(
                "writing",
                [{"role": "user", "content": render("situation", input=_dump(data))}],
                job="summarize_findings",
                ws=ws,
                request_id=request_id,
            )
            return text
        except ModelError as exc:
            log.warning(
                "summarize_findings fell back to the template", extra={"error": type(exc).__name__}
            )
    await usage.record(
        usage.UsageRow(
            job="summarize_findings",
            provider="stub",
            model=stubs.STUB_MODEL,
            workspace_id=ws,
            request_id=request_id,
            stub=True,
        )
    )
    return template_summary(data)


async def extract_procedure(
    text: str, *, ws: str | None = None, request_id: str | None = None
) -> dict[str, Any] | None:
    """A12.6: `{area, steps[], testCommand?}` from text stating how changes are made, else None."""

    def validate(raw: dict[str, Any]) -> dict[str, Any]:
        steps = raw.get("steps")
        if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
            raise InvalidModelOutput("steps must be a list of strings")
        cmd = raw.get("testCommand")
        if cmd is not None and (not isinstance(cmd, str) or cmd not in text):
            cmd = None  # never invent a command
        return {
            "area": str(raw.get("area") or ""),
            "steps": [s.strip() for s in steps if s.strip()],
            "testCommand": cmd,
        }

    if not llm.available("decision"):
        return None
    try:
        result, _ = await llm.complete_json(
            "decision",
            [{"role": "user", "content": render("procedure_extraction", text=text)}],
            validate,
            job="extract_procedure",
            ws=ws,
            request_id=request_id,
        )
    except ModelError:
        return None
    if not result["steps"] and not result["testCommand"]:
        return None
    return result
