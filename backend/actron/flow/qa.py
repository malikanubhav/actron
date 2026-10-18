"""Q&A mode (spec B, B14): a question-kind request is investigated in answer mode, then `write_answer`
composes an answer that cites the evidence. RequestWorkflow ends it in `Done` with outcome `answered`.

The same composer answers review feedback classified as a question.
"""

from __future__ import annotations

from typing import Any

from actron.logging import get_logger

log = get_logger(__name__)
NO_HISTORY = "Nothing in your team's history answers this yet."


async def compose_answer(ws: str, request_id: str, question: str,
                         evidence: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], bool]:
    """Answer text, the cited evidence items, and whether the text came from a stub."""
    try:
        from actron.models import EvidenceItem, write_answer

        items = [EvidenceItem(id=str(e.get("evidenceId")), type=str(e.get("nodeType", "")),
                              text=str(e.get("quote") or e.get("title") or ""), url=(e.get("source") or {}).get("url"))
                 for e in evidence]
        ans = await write_answer(question, items, ws=ws, request_id=request_id)
        cited_ids = set(ans.evidenceIds)
        cited = [e for e in evidence if str(e.get("evidenceId")) in cited_ids]
        return ans.text, cited, bool(ans.stub)
    except Exception as exc:
        log.warning("write_answer unavailable; using a plain summary", extra={"error": type(exc).__name__})
        return plain_answer(evidence)


def plain_answer(evidence: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], bool]:
    """Deterministic answer when the writing model is not available: quotes the top evidence."""
    if not evidence:
        return NO_HISTORY, [], True
    top = evidence[:3]
    lines = [f"{e.get('title')}: {e.get('quote') or ''}".strip().rstrip(":") for e in top]
    return "Here is what the history shows. " + " ".join(lines), top, True
