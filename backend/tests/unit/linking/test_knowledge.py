"""A-AC-78 (bonus): KNOWS_ABOUT scores and OWNS on a synthetic dataset with hand-computed values."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from actron.graph import ids
from actron.graph.store import LinkRow
from actron.linking.identity import link_identities
from actron.linking.knowledge import compute_knowledge, score
from tests.unit.linking import builders as b

NOW = datetime(2026, 10, 17, tzinfo=UTC)
S = {"method": "structural", "confidence": 1.0}


def _person(g: Any, account_identity: str) -> str:
    [row] = g.query(
        "MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity {id: $i}) RETURN p.id AS id",
        {"i": account_identity},
    )
    return str(row["id"])


def test_score_formula() -> None:
    """A-AC-78: 1 - exp(-(0.4c + 0.3*blame*10 + 0.2r + 0.1m)/5)."""
    assert score(0, 0, 0, 0) == 0.0
    assert score(3, 0.7, 0, 1) == pytest.approx(1 - math.exp(-3.4 / 5))


def test_knows_about_and_owns(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-78: commits (365-day window), blame, reviews and messages give the expected scores; OWNS by
    CODEOWNERS and blame share."""
    g = indexed_graph
    ana_git = b.git_author(g, "ana@calva.dev", "Ana")
    ben_git = b.git_author(g, "ben@calva.dev", "Ben")
    b.github_user(g, 1, "ana-gh", email="ana@calva.dev")
    ben_gh = b.github_user(g, 2, "ben-gh", email="ben@calva.dev")
    b.slack_user(g, "UANA", email="ana@calva.dev")
    fn = b.code_fn(g, "src/a.ts", "doThing", "function doThing() {}")
    file_id = ids.code_file(b.REPO, "src/a.ts")
    for i in range(3):
        b.commit(
            g, f"{i:040x}", f"change {i}", author=ana_git, at="2026-08-01T00:00:00Z", touched=[fn]
        )
    b.commit(g, "f" * 40, "old change", author=ben_git, at="2024-01-01T00:00:00Z", touched=[fn])
    g.upsert_links(
        "BLAME_OWNS",
        "GitAuthor",
        "CodeFunction",
        [
            LinkRow(ana_git, fn, {**S, "lines": 7, "lineShare": 0.7}),
            LinkRow(ben_git, fn, {**S, "lines": 3, "lineShare": 0.3}),
        ],
    )
    for n in (5, 6):
        pr = b.pr(g, n, f"PR {n}")
        g.upsert_links(
            "PR_TOUCHED",
            "GithubPullRequest",
            "CodeFunction",
            [LinkRow(pr, fn, {**S, "linesChanged": 2})],
        )
        rid = ids.github_review(900 + n)
        g.upsert_nodes(
            "GithubReview",
            [{"id": rid, "state": "APPROVED", "submittedAt": "2026-09-01T00:00:00Z"}],
        )
        g.upsert_links("HAS_REVIEW", "GithubPullRequest", "GithubReview", [LinkRow(pr, rid, S)])
        g.upsert_links("REVIEWED_BY", "GithubReview", "GithubUser", [LinkRow(rid, ben_gh, S)])
    msg = b.slack_msg(g, "C1", "1.1", "doThing is slow", user="UANA", at="2026-09-02T00:00:00Z")
    g.upsert_links(
        "MENTIONS",
        "SlackMessage",
        "CodeFunction",
        [LinkRow(msg, fn, {"method": "explicit", "confidence": 1.0})],
    )
    rule = ids.code_owners(b.REPO, 3)
    g.upsert_nodes(
        "CodeOwnerRule",
        [{"id": rule, "pattern": "src/*.ts", "owners": ["@ben-gh", "@calva/core"], "line": 3}],
    )
    g.upsert_links("MATCHES_OWNER_RULE", "CodeFile", "CodeOwnerRule", [LinkRow(file_id, rule, S)])
    link_identities(g, "ws", mapping_path=tmp_path / "none.yaml")
    ana, ben = (
        _person(g, ids.identity("git", "ana@calva.dev")),
        _person(g, ids.identity("git", "ben@calva.dev")),
    )

    report = compute_knowledge(g, now=NOW)

    [ka] = b.links(g, "KNOWS_ABOUT", ana, fn)
    assert ka["score"] == pytest.approx(round(score(3, 0.7, 0, 1), 4))
    assert json.loads(ka["signals"]) == {
        "commits": 3.0,
        "blame": 0.7,
        "reviews": 0.0,
        "messages": 1.0,
    }
    [kb] = b.links(g, "KNOWS_ABOUT", ben, fn)
    assert kb["score"] == pytest.approx(
        round(score(0, 0.3, 2, 0), 4)
    )  # the 2024 commit is outside the window
    assert json.loads(kb["signals"])["commits"] == 0.0
    [own_fn] = b.links(g, "OWNS", ana, fn)
    assert own_fn["basis"] == "blame" and own_fn["confidence"] == 0.7
    assert not b.links(g, "OWNS", ben, fn)
    [own_file] = b.links(g, "OWNS", ben, file_id)
    assert own_file["basis"] == "codeowners" and own_file["method"] == "structural"
    assert b.links(g, "CODEOWNER_IS", rule, ben)
    assert report.knows_about >= 2 and report.owns == 2 and report.codeowner_links == 1


def test_low_scores_are_not_kept(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-78: a score below 0.2 creates no KNOWS_ABOUT."""
    g = indexed_graph
    author = b.git_author(g, "x@calva.dev")
    fn = b.code_fn(g, "src/b.ts", "f", "function f() {}")
    b.commit(g, "a" * 40, "one", author=author, at="2026-10-01T00:00:00Z", touched=[fn])
    link_identities(g, "ws", mapping_path=tmp_path / "none.yaml")
    compute_knowledge(g, now=NOW)
    assert score(1, 0, 0, 0) < 0.2 and not b.links(g, "KNOWS_ABOUT", None, fn)
