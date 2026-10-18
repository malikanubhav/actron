"""A-AC-75 and A-AC-103: decision extraction, approval, bots, supersession (full and partial), tombstones."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from actron.graph import ids
from actron.linking.classify import Classification
from actron.linking.decisions import link_decisions
from actron.linking.identity import link_identities
from actron.linking.references import link_references
from tests.fakes.jev import FakeJev, choice_answer
from tests.fakes.llm import FakeLLM
from tests.unit.linking import builders as b

DECIDED = Classification("decision", 0.9, False)
PROPOSED = Classification("proposal", 0.8, False)


def extraction_reply(call: dict[str, Any]) -> str:
    """Fake extraction: the first sentence is the decision; `scope:` and `PARAPHRASE` markers steer it."""
    prompt = call["messages"][0]["content"]
    text = prompt.split('"""\n', 1)[1].rsplit('\n"""', 1)[0]
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    quote = first.replace("keep", "retain") if "PARAPHRASE" in text else first
    scope = re.search(r"scope: (\w+)", text)
    return json.dumps(
        {
            "is_decision": True,
            "statement": first.rstrip("."),
            "quote": quote,
            "scope": scope.group(1) if scope else "",
            "status_hint": "decided"
            if re.search(r"decided|going with", text, re.I)
            else "proposed",
        }
    )


def jev_answers(qid: str, q: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if qid == "approves":
        agree = re.search(r"\b(agreed|approve|ship it|let's do that)\b", state["reply"], re.I)
        return {"type": "noul", "noul": 0.95 if agree else 0.2}
    if qid == "relation" and "earlier" in state:
        return choice_answer("replaces", list(q["criteria"]), 0.9)
    return {"type": "noul", "noul": 0.5}


def _setup(g: Any) -> dict[str, str]:
    b.slack_user(g, "UANA", email="ana@calva.dev", name="Ana")
    b.slack_user(g, "UBEN", email="ben@calva.dev", name="Ben")
    b.slack_user(g, "UBOT", name="calva-bot", is_bot=True)
    fns = {
        "paste": b.code_fn(
            g, "src/calva-fmt/src/paste.ts", "formatPaste", "function formatPaste() {}"
        ),
        "indent": b.code_fn(
            g, "src/calva-fmt/src/indent.ts", "indentRules", "function indentRules() {}"
        ),
    }
    return fns


async def test_explicit_decision_is_approved(
    indexed_graph: Any,
    llm_on: Callable[..., FakeLLM],
    jev_on: Callable[..., FakeJev],
    tmp_path: Any,
) -> None:
    """A-AC-75: a text that settles the choice -> approved, EXTRACTED_FROM with exact quote, DECIDED_BY author."""
    g = indexed_graph
    fns = _setup(g)
    link_identities(g, "ws", mapping_path=tmp_path / "none.yaml")
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    text = "We decided to keep `formatPaste` off by default. Users can enable it in settings."
    msg = b.slack_msg(g, "C1", "2.1", text, user="UANA")
    link_references(g, [msg])
    report = await link_decisions(g, [msg], {msg: DECIDED})
    did = ids.decision(msg)
    d = b.node(g, did)
    assert (
        d["status"] == "approved"
        and d["quote"] == "We decided to keep `formatPaste` off by default."
    )
    assert (
        text[d["quoteSpan"][0] : d["quoteSpan"][1]] == d["quote"]
        and d["extractedBy"] == "groq/fake-decision"
    )
    [ef] = b.links(g, "EXTRACTED_FROM", did, msg)
    assert ef["method"] == "extracted" and ef["quote"] == d["quote"]
    [c] = b.links(g, "CONSTRAINS", did, fns["paste"])
    assert c["active"] is True and c["method"] == "extracted"
    [person] = g.query(
        "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity {id: $i}) RETURN p.id AS id",
        {"i": ids.identity("slack", "UANA")},
    )
    assert b.links(g, "DECIDED_BY", did, person["id"])
    assert report.approved == 1 and {lk.rel for lk in report.links} >= {
        "EXTRACTED_FROM",
        "CONSTRAINS",
    }


async def test_reply_approval(
    indexed_graph: Any,
    llm_on: Callable[..., FakeLLM],
    jev_on: Callable[..., FakeJev],
    tmp_path: Any,
) -> None:
    """A-AC-75: a proposal approved by a reply (J2 >= 0.85) -> approved, APPROVED_IN reply, DECIDED_BY replier."""
    g = indexed_graph
    _setup(g)
    link_identities(g, "ws", mapping_path=tmp_path / "none.yaml")
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    parent = b.slack_msg(g, "C1", "3.1", "Maybe paste formatting should be opt-in?", user="UANA")
    reply = b.slack_msg(g, "C1", "3.2", "Agreed, let's do that.", user="UBEN", parent_ts="3.1")
    await link_decisions(g, [parent], {parent: PROPOSED})
    did = ids.decision(parent)
    assert b.node(g, did)["status"] == "approved"
    [approved] = b.links(g, "APPROVED_IN", did, reply)
    assert approved["confidence"] == 0.95
    [ben] = g.query(
        "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity {id: $i}) RETURN p.id AS id",
        {"i": ids.identity("slack", "UBEN")},
    )
    assert b.links(g, "DECIDED_BY", did, ben["id"])
    assert "Agreed" in b.node(g, did)["approvalEvidence"]


async def test_polite_reply_leaves_proposed(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-75: acknowledgement without agreement leaves the decision proposed; no APPROVED_IN."""
    g = indexed_graph
    _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    parent = b.slack_msg(g, "C1", "4.1", "Maybe paste formatting should be opt-in?", user="UANA")
    b.slack_msg(g, "C1", "4.2", "Thanks, I will think about it.", user="UBEN", parent_ts="4.1")
    await link_decisions(g, [parent], {parent: PROPOSED})
    assert b.node(g, ids.decision(parent))["status"] == "proposed"
    assert not b.links(g, "APPROVED_IN", ids.decision(parent))


async def test_bot_messages_never_yield_decisions(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM]
) -> None:
    """A-AC-75 (A-AC-56): bot messages produce no Decision."""
    g = indexed_graph
    _setup(g)
    fake = llm_on(extraction_reply)
    m1 = b.slack_msg(g, "C1", "5.1", "We decided to ship 2.0 on Friday.", bot_id="B123")
    m2 = b.slack_msg(g, "C1", "5.2", "We decided to ship 2.0 on Friday.", subtype="bot_message")
    m3 = b.slack_msg(g, "C1", "5.3", "We decided to ship 2.0 on Friday.", user="UBOT")
    report = await link_decisions(
        g, [m1, m2, m3], {m: DECIDED for m in (m1, m2, m3)}, bot_user_ids={"UBOT"}
    )
    assert report.bot_skipped == 3 and g.count("Decision") == 0 and fake.calls == []


async def test_non_substring_quote_is_dropped(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM]
) -> None:
    """A-AC-75: extraction rejects quotes that are not exact substrings (after one retry)."""
    g = indexed_graph
    llm_on(extraction_reply)
    msg = b.slack_msg(g, "C1", "6.1", "We decided to keep strict mode. PARAPHRASE")
    report = await link_decisions(g, [msg], {msg: DECIDED})
    assert report.dropped == 1 and g.count("Decision") == 0


async def test_stub_extraction_creates_nothing(indexed_graph: Any) -> None:
    """A-AC-75 with no keys: no decision is invented."""
    g = indexed_graph
    msg = b.slack_msg(g, "C1", "6.2", "We decided to keep strict mode.")
    report = await link_decisions(g, [msg], {msg: DECIDED})
    assert report.dropped == 1 and g.count("Decision") == 0


async def test_partial_supersession_deactivates_only_scope(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-75 + A-AC-103: SUPERSEDES {scope}; only CONSTRAINS links inside the new decision's scope go inactive."""
    g = indexed_graph
    fns = _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    old = b.slack_msg(
        g,
        "C1",
        "7.1",
        "We decided `formatPaste` and `indentRules` stay off. scope: formatter",
        at="2026-09-01T10:00:00Z",
    )
    new = b.slack_msg(
        g,
        "C1",
        "7.2",
        "We decided `formatPaste` is on by default now. scope: paste",
        at="2026-09-10T10:00:00Z",
    )
    link_references(g, [old, new])
    await link_decisions(g, [old], {old: DECIDED})
    report = await link_decisions(g, [new], {new: DECIDED})
    d_old, d_new = ids.decision(old), ids.decision(new)
    [sup] = b.links(g, "SUPERSEDES", d_new, d_old)
    assert sup["scope"] == "paste" and sup["confidence"] == 0.9 and report.superseded == 1
    [paste] = b.links(g, "CONSTRAINS", d_old, fns["paste"])
    [indent] = b.links(g, "CONSTRAINS", d_old, fns["indent"])
    assert paste["active"] is False and paste["supersededBy"] == d_new
    assert indent["active"] is True
    assert b.node(g, d_old)["status"] == "approved"


async def test_full_supersession(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-75: when the new decision covers every target, the old one becomes superseded."""
    g = indexed_graph
    fns = _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    old = b.slack_msg(
        g, "C1", "8.1", "We decided `formatPaste` stays off.", at="2026-09-01T10:00:00Z"
    )
    new = b.slack_msg(
        g, "C1", "8.2", "We decided `formatPaste` is on by default.", at="2026-09-10T10:00:00Z"
    )
    link_references(g, [old, new])
    await link_decisions(g, [old], {old: DECIDED})
    await link_decisions(g, [new], {new: DECIDED})
    assert b.node(g, ids.decision(old))["status"] == "superseded"
    assert b.links(g, "CONSTRAINS", ids.decision(old), fns["paste"])[0]["active"] is False
    assert b.links(g, "CONSTRAINS", ids.decision(new), fns["paste"])[0]["active"] is True


async def test_deleted_source_tombstones_links_keeps_decision(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-103: a deleted source tombstones EXTRACTED_FROM and its mentions; the decision node stays."""
    g = indexed_graph
    fns = _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    msg = b.slack_msg(g, "C1", "9.1", "We decided `formatPaste` stays off.")
    link_references(g, [msg])
    await link_decisions(g, [msg], {msg: DECIDED})
    g.tombstone("SlackMessage", [msg])
    report = await link_decisions(g, [msg], {})
    did = ids.decision(msg)
    assert report.tombstoned >= 2
    assert b.node(g, did)["status"] == "approved"
    assert not b.links(g, "EXTRACTED_FROM", did, msg)
    assert b.links(g, "EXTRACTED_FROM", did, msg, include_deleted=True)[0]["deleted"] is True
    assert not b.links(g, "MENTIONS", msg, fns["paste"])


async def test_edited_source_keeps_statement_history(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A12.4: an edit that changes the statement appends the old one to statementHistory."""
    g = indexed_graph
    _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    msg = b.slack_msg(g, "C1", "10.1", "We decided paste formatting stays off.")
    await link_decisions(g, [msg], {msg: DECIDED})
    b.slack_msg(g, "C1", "10.1", "We decided paste formatting is opt-in.")
    await link_decisions(g, [msg], {msg: DECIDED})
    d = b.node(g, ids.decision(msg))
    assert d["statement"] == "We decided paste formatting is opt-in"
    assert d["statementHistory"] == ["We decided paste formatting stays off"]


async def test_decision_implemented_by_commit(
    indexed_graph: Any, llm_on: Callable[..., FakeLLM], jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-106 (decision part): a decision restated after its commit links DECISION_IMPLEMENTED_BY."""
    g = indexed_graph
    _setup(g)
    llm_on(extraction_reply)
    jev_on(answer_fn=jev_answers)
    c = b.commit(g, "abcdef1234567890abcdef1234567890abcdef12", "Turn paste formatting off")
    msg = b.slack_msg(
        g, "C1", "11.1", "We decided paste formatting stays off, done in commit abcdef12."
    )
    link_references(g, [msg])
    report = await link_decisions(g, [msg], {msg: DECIDED})
    assert b.links(g, "DECISION_IMPLEMENTED_BY", ids.decision(msg), c) and report.implemented == 1
