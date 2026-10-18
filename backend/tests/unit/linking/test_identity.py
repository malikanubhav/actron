"""A-AC-70: identity resolution across Slack, GitHub, Linear and git."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from actron.graph import ids
from actron.graph.store import LinkRow
from actron.linking.identity import link_identities
from tests.unit.linking import builders as b

WS = "acme"


def _people(g: Any) -> list[dict[str, Any]]:
    return g.query(
        "MATCH (p:Person) OPTIONAL MATCH (p)-[:HAS_IDENTITY]->(i:Identity) "
        "RETURN p.id AS id, p.displayName AS name, collect(i.id) AS identities ORDER BY id"
    )


def test_email_match_across_four_sources(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: one email in four sources -> one Person with four Identity nodes."""
    g = indexed_graph
    b.slack_user(g, "U1", email="Ana@Example.org", name="Ana L")
    b.github_user(g, 101, "ana-l", email="ana@example.org", name="Ana Lopez")
    b.linear_user(g, "lin-ana", email="ana@example.org", name="Ana Lopez")
    b.git_author(g, "ana@example.org", "Ana")
    report = link_identities(g, WS, mapping_path=tmp_path / "none.yaml")
    [person] = _people(g)
    assert len(person["identities"]) == 4 and person["name"] == "Ana Lopez"
    assert report.people == 1 and report.resolved_people == 1 and report.unresolved == []
    ident = b.node(g, ids.identity("slack", "U1"))
    assert ident["matchMethod"] == "email" and ident["matchConfidence"] == 1.0
    assert b.links(g, "IS_SLACK_USER", ident["id"], ids.slack_user("U1"))
    assert b.links(
        g,
        "IS_GIT_AUTHOR",
        ids.identity("git", "ana@example.org"),
        ids.git_author("ana@example.org"),
    )
    assert b.node(g, person["id"])["primaryEmail"] == "ana@example.org"


def test_same_name_different_email_stays_two_people(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: display names never join accounts; both stay unresolved and are listed."""
    g = indexed_graph
    b.slack_user(g, "U2", email="sam@one.org", name="Sam Park")
    b.github_user(g, 202, "sampark", email="sam@two.org", name="Sam Park")
    report = link_identities(g, WS, mapping_path=tmp_path / "none.yaml")
    assert len(_people(g)) == 2
    assert sorted(report.unresolved) == sorted([ids.slack_user("U2"), ids.github_user(202)])
    assert b.node(g, ids.identity("github", "202"))["matchMethod"] == "unresolved"
    assert b.node(g, ids.identity("github", "202"))["matchConfidence"] == 0.0


def test_noreply_email_maps_to_github_user(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: `<id>+<login>@users.noreply.github.com` and `<login>@users.noreply...` map to the GitHub user."""
    g = indexed_graph
    b.github_user(g, 303, "pez", email=None, name="Peter")
    b.github_user(g, 404, "kim", email=None, name="Kim")
    b.git_author(g, "303+pez@users.noreply.github.com", "Peter")
    b.git_author(g, "kim@users.noreply.github.com", "Kim")
    link_identities(g, WS, mapping_path=tmp_path / "none.yaml")
    people = _people(g)
    assert len(people) == 2
    assert all(len(p["identities"]) == 2 for p in people)


def test_mapping_merges_two_people_and_moves_links(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: a later mapping entry merges two people; links of the extra person move to the kept one."""
    g = indexed_graph
    b.slack_user(g, "U9", email="jo@home.net", name="Jo")
    b.github_user(g, 909, "jo-dev", email="jo@work.com", name="Jo Dev")
    mapping = tmp_path / "identity_map.yaml"
    mapping.write_text("[]\n")
    link_identities(g, WS, mapping_path=mapping)
    people = {p["id"]: p for p in _people(g)}
    assert len(people) == 2
    gh_person = next(p for p in people.values() if ids.identity("github", "909") in p["identities"])
    g.upsert_nodes(
        "Decision",
        [
            {
                "id": "actron:decision:d1",
                "statement": "s",
                "status": "approved",
                "quote": "q",
                "confidence": 0.9,
                "extractedBy": "test",
            }
        ],
    )
    g.upsert_links(
        "DECIDED_BY",
        "Decision",
        "Person",
        [LinkRow("actron:decision:d1", gh_person["id"], {"method": "inferred", "confidence": 0.9})],
    )
    mapping.write_text("- person: Jo Rivera\n  accounts: [slack:U9, github:jo-dev]\n")
    report = link_identities(g, WS, mapping_path=mapping)
    [person] = _people(g)
    assert report.merged == 1 and len(person["identities"]) == 2 and person["name"] == "Jo Rivera"
    assert b.links(g, "DECIDED_BY", "actron:decision:d1", person["id"])
    assert b.node(g, ids.identity("slack", "U9"))["matchMethod"] == "mapping_file"


def test_idempotent_and_bots_skipped(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: running twice changes nothing; Slack bots get no Person."""
    g = indexed_graph
    b.slack_user(g, "U1", email="a@x.org")
    b.slack_user(g, "UBOT", is_bot=True)
    b.git_author(g, "a@x.org")
    link_identities(g, WS, mapping_path=tmp_path / "none.yaml")
    link_identities(g, WS, mapping_path=tmp_path / "none.yaml")
    assert g.count("Person") == 1 and g.count("Identity") == 2


def test_unmatched_mapping_entries_are_reported(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-70: mapping entries that match no account are listed, not guessed."""
    g = indexed_graph
    b.slack_user(g, "U1", email="a@x.org")
    mapping = tmp_path / "m.yaml"
    mapping.write_text("- person: A\n  accounts: [slack:U1, github:ghost]\n")
    report = link_identities(g, WS, mapping_path=mapping)
    assert report.unmatched_mapping_entries == ["github:ghost"]
