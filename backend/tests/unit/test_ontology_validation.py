"""A-AC-12: validate_node rejects wrong types for every type kind, missing required and unknown properties."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from actron.graph.ontology import Ontology, OntologyViolation, PropertyDef, UnknownNodeType

NOW = "2026-10-17T10:00:00Z"
COMMON = {
    "source": "slack",
    "workspaceId": "ws1",
    "ingestedAt": NOW,
    "refreshedAt": NOW,
    "ontologyVersion": "v",
}


def slack_msg(**extra: Any) -> dict[str, Any]:
    return {
        "id": "slack:msg:C1:1.2",
        "text": "hi",
        "ts": "1.2",
        "channelId": "C1",
        "postedAt": NOW,
        **COMMON,
        **extra,
    }


def test_valid_node_passes_a_ac_12(ontology: Ontology) -> None:
    """A-AC-12"""
    ontology.validate_node("SlackMessage", slack_msg())


def test_common_properties_accepted_on_any_node_a_ac_12(ontology: Ontology) -> None:
    """A-AC-12"""
    for label in ("SlackMessage", "CodeFunction", "GithubIssue", "LinearTeam"):
        ontology.validate_node(
            label,
            {**COMMON, "sourceUrl": "https://x", "deleted": True, "deletedAt": NOW},
            partial=True,
        )


# One wrong value per type kind present in the ontology files.
WRONG_TYPE_CASES: list[tuple[str, str, Any, str]] = [
    ("SlackMessage", "text", 12, "string"),
    ("SlackMessage", "replyCount", "3", "integer"),
    ("SlackMessage", "replyCount", True, "integer (bool is not int)"),
    ("SlackMessage", "replyCount", 1.5, "integer (float)"),
    ("LinearIssue", "estimate", "2", "float"),
    ("LinearIssue", "estimate", False, "float (bool)"),
    ("SlackMessage", "edited", "yes", "boolean"),
    ("SlackMessage", "edited", 1, "boolean (int)"),
    ("SlackMessage", "postedAt", 12345, "datetime (int)"),
    ("SlackMessage", "postedAt", "not a date", "datetime (bad string)"),
    ("LinearIssue", "dueDate", 20261017, "date (int)"),
    ("LinearIssue", "dueDate", "tomorrow", "date (bad string)"),
    ("LinearIssue", "labelIds", "a,b", "array (string)"),
    ("LinearIssue", "labelIds", [["nested"]], "array (nested list)"),
    ("LinearIssue", "labelIds", [{"a": 1}], "array (dict item)"),
    ("LinearCustomView", "filters", 5, "object"),
]


@pytest.mark.parametrize(("label", "prop", "value", "kind"), WRONG_TYPE_CASES)
def test_wrong_type_rejected_a_ac_12(
    ontology: Ontology, label: str, prop: str, value: Any, kind: str
) -> None:
    """A-AC-12: wrong type for each type kind"""
    with pytest.raises(OntologyViolation) as err:
        ontology.validate_node(label, {prop: value}, partial=True)
    assert prop in str(err.value)


def test_number_type_is_checked_a_ac_12() -> None:
    """A-AC-12: `number` (used by the Slack fabric properties) accepts int and float only."""
    prop = PropertyDef("n", "number", False, False, False, False)
    o = Ontology.__new__(Ontology)
    o._check_value("X", prop, 1)
    o._check_value("X", prop, 1.5)
    for bad in ("1", True, [1]):
        with pytest.raises(OntologyViolation):
            o._check_value("X", prop, bad)


@pytest.mark.parametrize(
    ("label", "prop", "value"),
    [
        ("SlackMessage", "text", "hello"),
        ("SlackMessage", "replyCount", 3),
        ("LinearIssue", "estimate", 2),
        ("LinearIssue", "estimate", 2.5),
        ("SlackMessage", "edited", False),
        ("SlackMessage", "postedAt", datetime(2026, 10, 17, tzinfo=UTC)),
        ("SlackMessage", "postedAt", "2026-10-17T10:00:00+00:00"),
        ("LinearIssue", "dueDate", date(2026, 10, 17)),
        ("LinearIssue", "dueDate", "2026-10-17"),
        ("LinearIssue", "labelIds", ["a", "b"]),
        ("LinearIssue", "labelIds", []),
        ("LinearCustomView", "filters", {"a": 1}),
        ("LinearCustomView", "filters", '{"a": 1}'),
    ],
)
def test_right_type_accepted_a_ac_12(ontology: Ontology, label: str, prop: str, value: Any) -> None:
    """A-AC-12"""
    ontology.validate_node(label, {prop: value}, partial=True)


def test_none_is_allowed_for_optional_values(ontology: Ontology) -> None:
    ontology.validate_node("SlackMessage", {"replyCount": None}, partial=True)


@pytest.mark.parametrize(
    "missing",
    [
        "id",
        "text",
        "ts",
        "channelId",
        "postedAt",
        "source",
        "workspaceId",
        "ingestedAt",
        "refreshedAt",
        "ontologyVersion",
    ],
)
def test_missing_required_property_rejected_a_ac_12(ontology: Ontology, missing: str) -> None:
    """A-AC-12"""
    props = slack_msg()
    del props[missing]
    with pytest.raises(OntologyViolation, match=missing):
        ontology.validate_node("SlackMessage", props)


def test_partial_skips_required_check(ontology: Ontology) -> None:
    ontology.validate_node("SlackMessage", {"text": "only text"}, partial=True)


def test_unknown_property_rejected_a_ac_12(ontology: Ontology) -> None:
    """A-AC-12"""
    with pytest.raises(OntologyViolation, match="mystery"):
        ontology.validate_node("SlackMessage", slack_msg(mystery="x"))


def test_unknown_node_type_rejected_a_ac_12(ontology: Ontology) -> None:
    """A-AC-12"""
    with pytest.raises(UnknownNodeType):
        ontology.validate_node("Nope", {})


def test_enumerated_values_are_enforced(ontology: Ontology) -> None:
    ontology.validate_node("GithubIssue", {"state": "open"}, partial=True)
    with pytest.raises(OntologyViolation, match="state"):
        ontology.validate_node("GithubIssue", {"state": "merged"}, partial=True)
    with pytest.raises(OntologyViolation):
        ontology.validate_node("CodeFunction", {"kind": "lambda"}, partial=True)


def test_enum_extraction_ignores_free_text(ontology: Ontology) -> None:
    for node in ontology.nodes.values():
        for prop in node.properties.values():
            if prop.allowed:
                assert all(" " not in value for value in prop.allowed)


COMMON_REL = {"method": "structural", "confidence": 1.0, "createdAt": NOW}


def test_relationship_properties_a_ac_12(ontology: Ontology) -> None:
    """A-AC-12 (relationship side): common props plus the ones listed in the description."""
    ontology.validate_rel(
        "CALLS", "CodeFunction", "CodeFunction", {**COMMON_REL, "count": 2, "resolution": "local"}
    )
    ontology.validate_rel("TOUCHED", "GitCommit", "CodeFunction", {**COMMON_REL, "linesChanged": 4})
    with pytest.raises(OntologyViolation, match="bogus"):
        ontology.validate_rel("CALLS", "CodeFunction", "CodeFunction", {**COMMON_REL, "bogus": 1})
    with pytest.raises(OntologyViolation, match="confidence"):
        ontology.validate_rel(
            "CALLS", "CodeFunction", "CodeFunction", {**COMMON_REL, "confidence": "high"}
        )


def test_known_relationship_property_lists(ontology: Ontology) -> None:
    def allowed(name: str, f: str, t: str) -> frozenset[str]:
        return ontology.rel(name, f, t).allowed_properties

    assert {"role", "rank", "path"} <= allowed("FOUND", "Investigation", "CodeFunction")
    assert {"score", "signals"} <= next(
        r.allowed_properties for k, r in ontology.relationships.items() if k[0] == "KNOWS_ABOUT"
    )
    assert "basis" in next(
        r.allowed_properties for k, r in ontology.relationships.items() if k[0] == "OWNS"
    )
    assert "scope" in next(
        r.allowed_properties for k, r in ontology.relationships.items() if k[0] == "SUPERSEDES"
    )
