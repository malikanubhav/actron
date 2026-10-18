"""Explicit references against a real graph: resolution, pending, ambiguity, IMPLEMENTED_BY, tombstones.

A-AC-71 (resolution side), A-AC-72, A-AC-73, A-AC-103 (reference links), A-AC-104 (attachments), A-AC-106.
"""

from __future__ import annotations

from typing import Any

from actron.graph import ids
from actron.linking.references import link_references, resolve_pending
from tests.unit.linking import builders as b


def test_resolved_reference_creates_mentions(indexed_graph: Any) -> None:
    """A-AC-71: a resolvable key creates Reference(resolved), CONTAINS_REFERENCE, RESOLVES_TO and MENTIONS."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    issue = b.linear_issue(g, "u-12", "CAL-12", "Paste formatting breaks forms")
    msg = b.slack_msg(
        g, "C1", "1712345678.000100", "Looking at CAL-12 now, the paste handler is odd."
    )
    report = link_references(g, [msg])
    assert (report.resolved, report.pending, report.mentions) == (1, 0, 1)
    ref = b.node(g, ids.reference("linear_issue", "CAL-12"))
    assert ref["status"] == "resolved" and ref["kind"] == "linear_issue" and ref["resolvedAt"]
    [m] = b.links(g, "MENTIONS", msg, issue)
    assert m["method"] == "explicit" and m["confidence"] == 1.0 and "CAL-12" in m["quote"]
    assert b.links(g, "RESOLVES_TO", ref["id"], issue)
    assert b.links(g, "CONTAINS_REFERENCE", msg, ref["id"])


def test_pending_then_resolved_after_linear_run(indexed_graph: Any) -> None:
    """A-AC-72: Slack mentions ENG-40 before Linear exists -> pending; after the Linear run -> resolved."""
    g = indexed_graph
    msg = b.slack_msg(g, "C1", "1712345678.000200", "ENG-40 decides the jack-in menu order.")
    first = link_references(g, [msg])
    assert first.pending == 1
    rid = ids.reference("linear_issue", "ENG-40")
    assert b.node(g, rid)["status"] == "pending" and not b.links(g, "MENTIONS", msg)
    b.linear_team(g, "ENG")
    issue = b.linear_issue(g, "u-40", "ENG-40", "Jack-in menu order")
    report = resolve_pending(g, "linear")
    assert report.resolved == 1 and report.mentions == 1
    assert b.node(g, rid)["status"] == "resolved"
    assert b.links(g, "RESOLVES_TO", rid, issue) and b.links(g, "MENTIONS", msg, issue)
    assert resolve_pending(g, "linear").resolved == 0  # idempotent


def test_pending_ignored_for_other_sources(indexed_graph: Any) -> None:
    """A-AC-72: resolve_pending only checks the kinds of the source just ingested."""
    g = indexed_graph
    msg = b.slack_msg(g, "C1", "1712345678.000300", "See ENG-41")
    link_references(g, [msg])
    b.linear_team(g, "ENG")
    b.linear_issue(g, "u-41", "ENG-41", "x")
    assert resolve_pending(g, "slack").resolved == 0
    assert resolve_pending(g, "linear").resolved == 1


def test_ambiguous_symbol(indexed_graph: Any) -> None:
    """A-AC-71: several targets -> status ambiguous, RESOLVES_TO each, no MENTIONS."""
    g = indexed_graph
    f1 = b.code_fn(g, "src/a.ts", "format", "function format() {}")
    f2 = b.code_fn(g, "src/b.ts", "format", "function format() {}")
    msg = b.slack_msg(g, "C1", "1.000001", "Why are there two `format` functions?")
    report = link_references(g, [msg])
    assert report.ambiguous == 1
    rid = ids.reference("symbol", "format")
    assert b.node(g, rid)["status"] == "ambiguous"
    assert {lk["to"] for lk in b.links(g, "RESOLVES_TO", rid)} == {f1, f2}
    assert not b.links(g, "MENTIONS", msg)


def test_file_symbol_github_commit_and_unmatched(indexed_graph: Any) -> None:
    """A-AC-71: file suffix, symbol, owner/name#n, bare #n, commit prefix resolve; unmatched files are dropped."""
    g = indexed_graph
    b.code_repo(g)
    f = b.code_file(g, "src/cursor-doc/paredit.ts")
    fn = b.code_fn(g, "src/extension.ts", "activate", "export function activate(context) {}")
    p = b.pr(g, 2401, "Paredit fix")
    c = b.commit(g, "1a2b3c4d5e6f7a8b9c0d1a2b3c4d5e6f7a8b9c0d", "Fix paredit")
    msg = b.slack_msg(
        g,
        "C1",
        "1.000002",
        "Touches `cursor-doc/paredit.ts` and activate() — see #2401, "
        "commit 1a2b3c4d, also src/missing/file.ts",
    )
    report = link_references(g, [msg])
    targets = {lk["to"] for lk in b.links(g, "MENTIONS", msg)}
    assert targets == {f, fn, p, c}
    assert report.pending == 0
    assert g.get_node(ids.reference("file", "src/missing/file.ts")) is None


def test_pr_title_key_and_branch_create_implemented_by(indexed_graph: Any) -> None:
    """A-AC-73: PR title containing a Linear key, or headRef equal to branchName, yields IMPLEMENTED_BY."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    i1 = b.linear_issue(g, "u-1", "CAL-1", "Paste", branch="vikram/cal-1-paste")
    i2 = b.linear_issue(g, "u-2", "CAL-2", "Indent", branch="vikram/indent-rules")
    p1 = b.pr(g, 10, "CAL-1: format on paste", head="other-branch")
    p2 = b.pr(g, 11, "Indent rules", head="vikram/indent-rules")
    link_references(g, [p1, p2])
    resolve_pending(g, "github")
    assert b.links(g, "IMPLEMENTED_BY", i1, p1)
    assert b.links(g, "IMPLEMENTED_BY", i2, p2)
    assert not b.links(g, "IMPLEMENTED_BY", i1, p2)


def test_branch_key_before_linear_arrives(indexed_graph: Any) -> None:
    """A-AC-73: a PR on branch `cal-9-x` ingested before Linear links once the team and issue arrive."""
    g = indexed_graph
    p = b.pr(g, 12, "Fix the thing", head="cal-9-fix-thing")
    link_references(g, [p])
    b.linear_team(g, "CAL")
    i = b.linear_issue(g, "u-9", "CAL-9", "Thing")
    resolve_pending(g, "linear")
    assert b.links(g, "IMPLEMENTED_BY", i, p)


def test_linear_attachment_pr_url(indexed_graph: Any) -> None:
    """A-AC-104 (linking part): a Linear attachment that is a PR URL yields IMPLEMENTED_BY."""
    g = indexed_graph
    p = b.pr(g, 77, "Something")
    i = b.linear_issue(
        g,
        "u-77",
        "CAL-77",
        "Thing",
        attachments=["https://github.com/BetterThanTomorrow/calva/pull/77"],
    )
    link_references(g, [i])
    assert b.links(g, "IMPLEMENTED_BY", i, p)


def test_slack_permalink_through_alias(indexed_graph: Any) -> None:
    """A-AC-106 (reference part): a permalink with a channel's original id resolves through aliases."""
    g = indexed_graph
    b.slack_channel(g, "CNEW", aliases=["COLD123"])
    target = b.slack_msg(g, "CNEW", "1700000000.123456", "We decided to keep strict mode.")
    msg = b.slack_msg(
        g,
        "CNEW",
        "1700000100.000001",
        "As said in https://clojurians.slack.com/archives/COLD123/p1700000000123456",
    )
    link_references(g, [msg])
    ref = b.node(g, ids.reference("slack_message", "COLD123:1700000000.123456"))
    assert ref["kind"] == "slack_message" and ref["status"] == "resolved"
    assert b.links(g, "MENTIONS", msg, target)


def test_deleted_message_tombstones_reference_links(indexed_graph: Any) -> None:
    """A-AC-103: deleting a Slack message tombstones its outgoing reference and mention links."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    issue = b.linear_issue(g, "u-5", "CAL-5", "x")
    msg = b.slack_msg(g, "C1", "1.000005", "CAL-5 is next")
    link_references(g, [msg])
    g.tombstone("SlackMessage", [msg])
    report = link_references(g, [msg])
    assert report.tombstoned == 2
    assert not b.links(g, "MENTIONS", msg, issue)
    [m] = b.links(g, "MENTIONS", msg, issue, include_deleted=True)
    assert m["deleted"] is True and m["deletedAt"]


def test_edited_out_reference_is_tombstoned(indexed_graph: Any) -> None:
    """A-AC-103 / A12.4a: an edit that removes a reference tombstones only that link."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    i5 = b.linear_issue(g, "u-5", "CAL-5", "x")
    i6 = b.linear_issue(g, "u-6", "CAL-6", "y")
    msg = b.slack_msg(g, "C1", "1.000006", "CAL-5 and CAL-6")
    link_references(g, [msg])
    b.slack_msg(g, "C1", "1.000006", "only CAL-6 now")
    link_references(g, [msg])
    assert not b.links(g, "MENTIONS", msg, i5) and b.links(g, "MENTIONS", msg, i6)
    assert b.links(g, "MENTIONS", msg, i5, include_deleted=True)[0]["deleted"] is True


def test_relinking_is_idempotent(indexed_graph: Any) -> None:
    """A-AC-71: running linking twice creates no duplicate nodes or links."""
    g = indexed_graph
    b.linear_team(g, "CAL")
    b.linear_issue(g, "u-1", "CAL-1", "x")
    msg = b.slack_msg(g, "C1", "1.000007", "CAL-1 again")
    link_references(g, [msg])
    link_references(g, [msg])
    assert g.count("Reference") == 1 and len(b.links(g, "MENTIONS", msg)) == 1
