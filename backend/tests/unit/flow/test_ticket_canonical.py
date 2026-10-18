"""Ticket canonical JSON, hash, Linear markdown and parse-back (spec B, B.C5, B7)."""

from __future__ import annotations

import json

from actron.flow.ticket import (
    MARKER_PREFIX,
    canonical_json,
    detect_external_edit,
    diff_contents,
    parse_description,
    render_markdown,
    template_ticket,
    ticket_hash,
)

TICKET = {
    "objective": "Let project admins export invoices.",
    "context": "Invoice exports are Finance-only today. A decision in #finance set that rule.",
    "acceptanceCriteria": ["Given a project admin, when they export, then the CSV downloads."],
    "constraintsToPreserve": [{"text": "Invoice exports stay Finance-only.", "evidenceIds": ["actron:decision:x"]}],
    "affectedFunctions": ["code:fn:o/r:src/export.py::export_csv"],
    "testPlan": [{"kind": "existing", "target": "code:fn:o/r:tests/t.py::test_x", "command": "pytest -q"}],
    "outOfScope": ["PDF exports"],
    "targetBranch": "main",
    "requestId": "req_01",
}


def test_canonical_excludes_revision() -> None:
    """B-AC-32: hash is over the object without `revision`."""
    a = ticket_hash(TICKET)
    b = ticket_hash({**TICKET, "revision": 7})
    assert a == b
    assert len(a) == 64
    assert '"revision"' not in canonical_json({**TICKET, "revision": 3})


def test_canonical_format_is_compact_and_sorted() -> None:
    """B.C5: sort_keys, compact separators, ensure_ascii False."""
    text = canonical_json({"b": 1, "a": "é"})
    assert text == '{"a":"é","b":1}'


def test_hash_changes_with_content() -> None:
    """B-AC-32: any content field change changes the hash."""
    base = ticket_hash(TICKET)
    for key in ("objective", "context", "targetBranch"):
        assert ticket_hash({**TICKET, key: TICKET[key] + "x"}) != base  # type: ignore[operator]


def test_markdown_contains_marker_and_json_block() -> None:
    """B-AC-33: the Linear description has the marker line and a fenced canonical JSON block."""
    h = ticket_hash(TICKET)
    md = render_markdown(TICKET, n=2, content_hash=h)
    assert f"{MARKER_PREFIX} sha256={h} rev=2 -->" in md
    assert "```json\n" + canonical_json(TICKET) + "\n```" in md
    assert "## Acceptance criteria" in md


def test_parse_back_yields_same_hash() -> None:
    """B-AC-33: parsing the description back gives the same hash and revision."""
    h = ticket_hash(TICKET)
    parsed = parse_description(render_markdown(TICKET, n=3, content_hash=h))
    assert parsed is not None
    assert parsed.marker_hash == h
    assert parsed.revision == 3
    assert parsed.computed_hash == h
    assert parsed.content == json.loads(canonical_json(TICKET))
    assert not detect_external_edit(render_markdown(TICKET, n=3, content_hash=h), h)


def test_external_edit_detected() -> None:
    """B-AC-34: an edit to the JSON block, the marker, or a removed block is an external edit."""
    h = ticket_hash(TICKET)
    md = render_markdown(TICKET, n=1, content_hash=h)
    assert detect_external_edit(md.replace("Let project admins", "Let anyone"), h)
    assert detect_external_edit(md.replace(f"sha256={h}", "sha256=" + "0" * 64), h)
    assert detect_external_edit("Someone rewrote the whole issue.", h)
    assert detect_external_edit(md, "f" * 64)


def test_template_ticket_from_findings() -> None:
    """B7: deterministic template when the LLM is stubbed."""
    findings = {
        "seeds": [{"id": "code:fn:o/r:a.py::f", "type": "CodeFunction", "score": 0.9}],
        "decisions": [
            {"id": "actron:decision:1", "statement": "Exports stay Finance-only.", "status": "approved"},
            {"id": "actron:decision:2", "statement": "Old rule.", "status": "superseded"},
        ],
        "impact": {"tests": [{"id": "code:fn:o/r:tests/t.py::test_f"}], "callers": [], "criticality": []},
        "procedures": [{"id": "actron:procedure:x", "testCommand": "pytest -q"}],
    }
    t = template_ticket(request_id="req_1", title="Add export", text="Add export for admins",
                        findings=findings, answers=[], target_branch="dev")
    assert t["objective"] == "Add export"
    assert t["constraintsToPreserve"] == [{"text": "Exports stay Finance-only.", "evidenceIds": ["actron:decision:1"]}]
    assert t["affectedFunctions"] == ["code:fn:o/r:a.py::f"]
    assert t["testPlan"][0]["target"] == "code:fn:o/r:tests/t.py::test_f"
    assert t["testPlan"][0]["command"] == "pytest -q"
    assert t["targetBranch"] == "dev"
    assert t["requestId"] == "req_1"


def test_diff_contents_lists_changed_fields() -> None:
    changes = diff_contents(TICKET, {**TICKET, "objective": "New"})
    assert changes == [{"field": "objective", "before": TICKET["objective"], "after": "New"}]
