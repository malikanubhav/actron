"""A-AC-74: meaning links keep candidates at or above the threshold with the probability as confidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from actron.linking.meaning import link_meaning, search_terms
from actron.linking.references import link_references
from tests.fakes.jev import FakeJev
from tests.unit.linking import builders as b

PROBS = {"formatPaste": 0.85, "pasteHandler": 0.6, "activate": 0.59}


def probability_by_name(qid: str, q: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if "candidates" in state:
        cand = next(c for c in state["candidates"] if c["id"] == qid)
    else:
        cand = state["candidate"]
    return {"type": "noul", "noul": PROBS.get(cand["name"].split(".")[-1], 0.1)}


def _code(g: Any) -> dict[str, str]:
    return {
        "formatPaste": b.code_fn(
            g,
            "src/calva-fmt/src/paste.ts",
            "formatPaste",
            "export function formatPaste(editor) { // format pasted clojure forms\n}",
            doc="Formats text pasted into a Clojure file",
        ),
        "pasteHandler": b.code_fn(
            g,
            "src/paste/handler.ts",
            "pasteHandler",
            "function pasteHandler(e) { return pasted text into editor }",
        ),
        "activate": b.code_fn(
            g,
            "src/extension.ts",
            "activate",
            "export function activate(context) { registerCommands(context); paste }",
        ),
        "unrelated": b.code_fn(
            g, "src/nrepl/session.ts", "evalCode", "function evalCode() { nrepl }"
        ),
    }


async def test_threshold_and_confidence(indexed_graph: Any, jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-74: >= 0.6 kept as MENTIONS (inferred, confidence = probability, model); < 0.6 not created."""
    g = indexed_graph
    fns = _code(g)
    fake = jev_on(answer_fn=probability_by_name)
    msg = b.slack_msg(
        g,
        "C1",
        "1.1",
        "Pasting Clojure forms into the editor breaks the formatting of pasted text.",
    )
    report = await link_meaning(g, [msg], {msg: "bug_report"})
    assert fake.calls == 1  # all candidates of one text in one request
    mentions = {lk["to"]: lk for lk in b.links(g, "MENTIONS", msg)}
    assert set(mentions) == {fns["formatPaste"], fns["pasteHandler"]}
    kept = mentions[fns["formatPaste"]]
    assert (
        kept["method"] == "inferred"
        and kept["confidence"] == 0.85
        and kept["model"] == "jev-1.13.0"
    )
    assert mentions[fns["pasteHandler"]]["confidence"] == 0.6
    assert kept["quote"] and kept["sourceRef"] == msg
    assert report.kept == 2 and report.dropped >= 1 and not report.stub
    assert {lk.to_id for lk in report.links} == set(mentions)


async def test_only_meaningful_kinds_are_linked(
    indexed_graph: Any, jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-74: chatter and status updates are not judged."""
    g = indexed_graph
    _code(g)
    fake = jev_on(answer_fn=probability_by_name)
    msg = b.slack_msg(g, "C1", "1.2", "Thanks for the paste formatting fix")
    report = await link_meaning(g, [msg], {msg: "chatter"})
    assert fake.calls == 0 and report.texts == 0 and not b.links(g, "MENTIONS", msg)


async def test_stub_creates_nothing(indexed_graph: Any) -> None:
    """A-AC-74 with no keys: the stub answers 0.0, so no inferred link is created and the run says stub."""
    g = indexed_graph
    _code(g)
    msg = b.slack_msg(g, "C1", "1.3", "Pasting Clojure forms breaks formatting")
    report = await link_meaning(g, [msg], {msg: "bug_report"})
    assert report.stub and report.kept == 0 and report.candidates > 0
    assert not b.links(g, "MENTIONS", msg)


async def test_explicit_mentions_dropped_and_neighbours_added(
    indexed_graph: Any, jev_on: Callable[..., FakeJev]
) -> None:
    """A-AC-74: explicit targets are not re-judged; code one hop from them becomes a candidate."""
    g = indexed_graph
    fns = _code(g)
    seen: list[str] = []

    def record(qid: str, q: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        cands = state.get("candidates") or [dict(state["candidate"], id=qid)]
        seen.extend(c["name"] for c in cands if c["id"] == qid)
        return {"type": "noul", "noul": 0.1}

    jev_on(answer_fn=record)
    msg = b.slack_msg(g, "C1", "1.4", "Something odd in `src/extension.ts` on startup")
    link_references(g, [msg])
    await link_meaning(g, [msg], {msg: "question"})
    assert "src/extension.ts" not in seen  # explicit file target dropped
    assert "activate" in seen  # function defined in the mentioned file
    assert fns["activate"]


def test_search_terms() -> None:
    """A-AC-74: stop words removed, identifiers split."""
    terms = search_terms("Why does formatPaste break the paredit-forward command?")
    assert "formatpaste" in terms and "paste" in terms and "paredit" in terms and "the" not in terms
