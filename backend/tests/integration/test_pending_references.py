"""A-AC-72 integration: pending references against the real FalkorDB with ontology indexes.

A Slack message mentioning ENG-40 is ingested before Linear; the Linear run then resolves it. Also checks
the PR <-> Linear branch link once the Linear issue arrives (A-AC-73).
"""

from __future__ import annotations

from typing import Any

import pytest

from actron.graph import ids
from actron.linking.references import link_references, resolve_pending
from tests.unit.linking import builders as b

pytestmark = pytest.mark.integration


def test_slack_before_linear(indexed_graph: Any) -> None:
    """A-AC-72."""
    g = indexed_graph
    msg = b.slack_msg(
        g, "C0456", "1712345678.000100", "Can we ship ENG-40 this week? It changes the REPL menu."
    )
    pr = b.pr(g, 501, "REPL menu", head="eng-40-repl-menu")
    first = link_references(g, [msg, pr])
    assert first.pending == 1
    ref = ids.reference("linear_issue", "ENG-40")
    assert b.node(g, ref)["status"] == "pending"
    assert g.query(
        "MATCH (:SlackMessage {id: $m})-[:CONTAINS_REFERENCE]->(r:Reference {id: $r}) RETURN r.id AS id",
        {"m": msg, "r": ref},
    )

    b.linear_team(g, "ENG")
    issue = b.linear_issue(
        g, "uuid-40", "ENG-40", "Reorder the REPL menu", branch="eng-40-repl-menu"
    )
    report = resolve_pending(g, "linear")

    assert report.resolved == 1
    node = b.node(g, ref)
    assert node["status"] == "resolved" and node["resolvedAt"]
    assert b.links(g, "RESOLVES_TO", ref, issue)
    [mention] = b.links(g, "MENTIONS", msg, issue)
    assert (
        mention["method"] == "explicit"
        and mention["confidence"] == 1.0
        and "ENG-40" in mention["quote"]
    )
    assert b.links(g, "IMPLEMENTED_BY", issue, pr)
    again = resolve_pending(g, "linear")
    assert again.resolved == 0 and len(b.links(g, "MENTIONS", msg, issue)) == 1
