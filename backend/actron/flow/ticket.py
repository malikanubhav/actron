"""Tickets: canonical JSON, SHA-256, revisions, Linear markdown and parse-back (spec B, B.C5, B7)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

MARKER_PREFIX = "<!-- actron:ticket"
_MARKER_RE = re.compile(r"<!-- actron:ticket sha256=(?P<hash>[0-9a-f]{64}) rev=(?P<rev>\d+) -->")
_BLOCK_RE = re.compile(r"```json\n(?P<body>.*?)\n```", re.DOTALL)

CONTENT_FIELDS = (
    "objective", "context", "acceptanceCriteria", "constraintsToPreserve", "affectedFunctions",
    "testPlan", "outOfScope", "targetBranch",
)


def canonical_json(ticket: dict[str, Any]) -> str:
    """B.C5 canonical form: the object without `revision`, sorted keys, compact, UTF-8."""
    body = {k: v for k, v in ticket.items() if k != "revision"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ticket_hash(ticket: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(ticket).encode("utf-8")).hexdigest()


def short_hash(h: str) -> str:
    return f"{h[:4]}…{h[-4:]}" if len(h) > 8 else h


def content_only(ticket: dict[str, Any]) -> dict[str, Any]:
    """TicketContent for the API (B.C7): without requestId and revision."""
    return {k: v for k, v in ticket.items() if k not in ("requestId", "revision")}


def normalise_content(content: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Fill missing fields with empty values so every revision has the full B.C5 shape."""
    out: dict[str, Any] = {
        "objective": str(content.get("objective") or ""),
        "context": str(content.get("context") or ""),
        "acceptanceCriteria": [str(x) for x in content.get("acceptanceCriteria") or []],
        "constraintsToPreserve": [
            {"text": str(c.get("text", "")), "evidenceIds": [str(e) for e in c.get("evidenceIds") or []]}
            for c in content.get("constraintsToPreserve") or []
            if isinstance(c, dict)
        ],
        "affectedFunctions": [str(x) for x in content.get("affectedFunctions") or []],
        "testPlan": [
            {"kind": str(t.get("kind", "existing")), "target": str(t.get("target", "")),
             "command": str(t.get("command", ""))}
            for t in content.get("testPlan") or []
            if isinstance(t, dict)
        ],
        "outOfScope": [str(x) for x in content.get("outOfScope") or []],
        "targetBranch": str(content.get("targetBranch") or ""),
        "requestId": request_id,
    }
    return out


def render_markdown(ticket: dict[str, Any], *, n: int, content_hash: str) -> str:
    """Linear description: readable markdown, then the marker line and the canonical JSON block."""
    lines = [f"**Objective.** {ticket.get('objective', '')}", "", str(ticket.get("context", "")), ""]
    lines.append("## Acceptance criteria")
    lines += [f"- {c}" for c in ticket.get("acceptanceCriteria") or []] or ["- None listed"]
    lines += ["", "## Constraints to preserve"]
    lines += [f"- {c.get('text', '')}" for c in ticket.get("constraintsToPreserve") or []] or ["- None found"]
    lines += ["", "## Affected functions"]
    lines += [f"- `{f}`" for f in ticket.get("affectedFunctions") or []] or ["- None identified"]
    lines += ["", "## Test plan"]
    lines += [
        f"- {t.get('kind', '')}: `{t.get('target', '')}` (`{t.get('command', '')}`)" for t in ticket.get("testPlan") or []
    ] or ["- Run the repository's test command"]
    if ticket.get("outOfScope"):
        lines += ["", "## Out of scope"] + [f"- {x}" for x in ticket["outOfScope"]]
    lines += ["", f"Target branch: `{ticket.get('targetBranch', '')}`", ""]
    lines.append(f"{MARKER_PREFIX} sha256={content_hash} rev={n} -->")
    lines.append("```json\n" + canonical_json(ticket) + "\n```")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ParsedTicket:
    content: dict[str, Any] | None
    marker_hash: str | None
    revision: int | None
    computed_hash: str | None

    @property
    def consistent(self) -> bool:
        return self.marker_hash is not None and self.marker_hash == self.computed_hash


def parse_description(md: str) -> ParsedTicket | None:
    """Read the marker and JSON block back from a Linear description. None when neither exists."""
    marker = _MARKER_RE.search(md or "")
    block = _BLOCK_RE.search(md or "")
    if not marker and not block:
        return None
    content: dict[str, Any] | None = None
    computed: str | None = None
    if block:
        try:
            parsed = json.loads(block.group("body"))
            if isinstance(parsed, dict):
                content = parsed
                computed = ticket_hash(parsed)
        except json.JSONDecodeError:
            content = None
    return ParsedTicket(
        content=content,
        marker_hash=marker.group("hash") if marker else None,
        revision=int(marker.group("rev")) if marker else None,
        computed_hash=computed,
    )


def detect_external_edit(md: str, expected_hash: str) -> bool:
    """B7: any mismatch between the block, the marker and the stored revision is an external edit."""
    parsed = parse_description(md)
    if parsed is None:
        return True
    return not (parsed.consistent and parsed.computed_hash == expected_hash)


def template_ticket(
    *,
    request_id: str,
    title: str,
    text: str,
    findings: dict[str, Any] | None,
    answers: list[dict[str, Any]],
    target_branch: str,
) -> dict[str, Any]:
    """Deterministic ticket used when the writing model is stubbed (B7)."""
    f = findings or {}
    decisions = [d for d in f.get("decisions") or [] if d.get("status") == "approved"]
    seeds = [s["id"] for s in f.get("seeds") or [] if str(s.get("id", "")).startswith("code:fn:")]
    tests = [t["id"] for t in (f.get("impact") or {}).get("tests") or [] if t.get("id")]
    procedures = f.get("procedures") or []
    command = next((p.get("testCommand") for p in procedures if p.get("testCommand")), "") or ""
    answered = [a for a in answers if a.get("questionId") != "target_branch" and a.get("value")]
    context = text.strip()
    if decisions:
        n = len(decisions)
        context += " 1 earlier decision constrains this code." if n == 1 else f" {n} earlier decisions constrain this code."
    for a in answered:
        context += f" Answer to {a.get('text') or a['questionId']}: {a['value']}."
    return normalise_content(
        {
            "objective": title,
            "context": context,
            "acceptanceCriteria": [f"Given the change is made, when it is used, then: {title}."],
            "constraintsToPreserve": [{"text": d.get("statement", ""), "evidenceIds": [d["id"]]} for d in decisions],
            "affectedFunctions": seeds,
            "testPlan": [{"kind": "existing", "target": t, "command": command} for t in tests]
            or [{"kind": "new", "target": seeds[0] if seeds else "", "command": command}],
            "outOfScope": [],
            "targetBranch": target_branch,
        },
        request_id,
    )


def diff_contents(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Field-level changes between two revisions, for GET /ticket/revisions."""
    return [
        {"field": k, "before": before.get(k), "after": after.get(k)}
        for k in CONTENT_FIELDS
        if before.get(k) != after.get(k)
    ]
