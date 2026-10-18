"""A-AC-78 (bonus) and A-AC-106 (procedure part): test command, co-changed paths, LEARNED_FROM_PR/TEXT."""

from __future__ import annotations

from typing import Any

from actron.linking.classify import Classification
from actron.linking.procedures import (
    co_changed,
    commands_in,
    learn_from_prs,
    learn_from_texts,
    procedure_id,
)
from tests.unit.linking import builders as b


def test_commands_in_text() -> None:
    """A-AC-78: test commands from backticks, `$ ` lines and CI `run:` lines."""
    text = (
        "Tested with `npm run unit-test`.\n$ npx mocha --grep paredit\n    - run: npm run integration-test\n"
        "`npm install` is not a test"
    )
    assert commands_in(text) == ["npm run unit-test", "npm run integration-test"]


def test_co_changed_threshold() -> None:
    """A-AC-78: pairs changed together in >= 30% of the area's PRs (and at least twice)."""
    prs = [{"a", "b"}, {"a", "b", "c"}, {"a"}, {"c"}, {"d"}, {"e"}, {"f"}]
    assert co_changed(prs) == []  # a<->b in 2 of 7 (29%)
    assert co_changed(prs[:5]) == ["a <-> b"]
    assert co_changed([{"a", "b"}]) == []


def test_learn_from_merged_prs(indexed_graph: Any) -> None:
    """A-AC-78: expected test command and co-changed paths, linked to their PRs."""
    g = indexed_graph
    files = ["src/cursor-doc/model.ts", "src/cursor-doc/paredit.ts"]
    p1 = b.pr(g, 1, "Paredit", body="Tested with `npm run unit-test`", merged=True, files=files)
    p2 = b.pr(
        g,
        2,
        "Paredit 2",
        body="`npm run unit-test` passes",
        merged=True,
        files=[*files, "docs/x.md"],
    )
    p3 = b.pr(g, 3, "Model", body="ran `npm run integration-test`", merged=True, files=files[:1])
    b.pr(g, 4, "Open", body="`npm run e2e-test`", merged=False, files=files)
    report = learn_from_prs(g)
    proc = b.node(g, procedure_id("src"))
    assert proc["testCommand"] == "npm run unit-test"
    assert proc["coChangedPaths"] == ["src/cursor-doc/model.ts <-> src/cursor-doc/paredit.ts"]
    assert any("npm run unit-test" in s for s in proc["steps"])
    assert {lk["to"] for lk in b.links(g, "LEARNED_FROM_PR", proc["id"])} == {p1, p2, p3}
    assert sorted(report.areas) == ["docs", "src"]


async def test_learned_from_slack_text_without_models(indexed_graph: Any) -> None:
    """A-AC-106: a procedure stated in a Slack message is linked with LEARNED_FROM_TEXT (heuristic when stubbed)."""
    g = indexed_graph
    msg = b.slack_msg(
        g,
        "C1",
        "9.1",
        "How we release:\n1. Bump the version in package.json\n"
        "2. Update CHANGELOG.md\n3. Run `npm run unit-test` and push the tag",
    )
    report = await learn_from_texts(g, [msg], {msg: Classification("chatter", 0.0, True)})
    proc = b.node(g, procedure_id("."))
    assert proc["testCommand"] == "npm run unit-test" and len(proc["steps"]) == 3
    assert b.links(g, "LEARNED_FROM_TEXT", proc["id"], msg) and report.learned_from_text == 1


async def test_chatter_is_not_a_procedure(indexed_graph: Any) -> None:
    """A-AC-78: texts classified as something else by a real model are skipped."""
    g = indexed_graph
    msg = b.slack_msg(g, "C1", "9.2", "1. lol\n2. nice `npm test` joke")
    report = await learn_from_texts(g, [msg], {msg: Classification("chatter", 0.9, False)})
    assert report.learned_from_text == 0
