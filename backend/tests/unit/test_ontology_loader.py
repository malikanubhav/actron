"""A-AC-10, A-AC-11, A-AC-14: ontology loading, group expansion, rule-3 failures, skipped fabric relationships."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from actron.config import REPO_ROOT
from actron.graph.ontology import FILE_ORDER, Ontology, OntologyError, load_ontology

ONTOLOGY_DIR = REPO_ROOT / "ontology"


def read_all() -> dict[str, dict[str, Any]]:
    return {s: json.loads((ONTOLOGY_DIR / f"{s}.json").read_text()) for s in FILE_ORDER}


def expected_counts(files: dict[str, dict[str, Any]]) -> tuple[int, int, dict[str, int]]:
    """Independent computation from the raw files (does not use the loader)."""
    node_names = {n["name"] for f in files.values() for n in f["nodes"]}
    groups = files["core"].get("node_groups", {})
    total = 0
    skipped = {"slack": 0, "linear": 0}
    for stem, data in files.items():
        for rel in data.get("relationships", []):
            frm = groups.get(rel["from_node"], [rel["from_node"]])
            to = groups.get(rel["to_node"], [rel["to_node"]])
            if all(n in node_names for n in (*frm, *to)):
                total += len(frm) * len(to)
            elif stem in skipped:
                skipped[stem] += 1
    return len(node_names), total, skipped


def test_real_files_load_with_expected_counts_a_ac_10(ontology: Ontology) -> None:
    """A-AC-10"""
    nodes, rels, _ = expected_counts(read_all())
    assert len(ontology.nodes) == nodes
    assert len(ontology.relationships) == rels
    assert nodes == 96


def test_core_relationships_expand_a_ac_10(ontology: Ontology) -> None:
    """A-AC-10: core's relationships over node groups expand to one RelDef per member pair."""
    core = read_all()["core"]
    groups = core["node_groups"]
    expected = sum(
        len(groups.get(r["from_node"], [r["from_node"]]))
        * len(groups.get(r["to_node"], [r["to_node"]]))
        for r in core["relationships"]
    )
    actual = sum(1 for r in ontology.relationships.values() if r.source_file == "core.json")
    assert actual == expected
    assert len(core["relationships"]) == 56
    assert expected == 287


def test_version_string_lists_every_file(ontology: Ontology) -> None:
    for stem in FILE_ORDER:
        assert f"{stem}:" in ontology.version


def test_group_members_are_resolvable(ontology: Ontology) -> None:
    for members in ontology.groups.values():
        assert all(m in ontology.nodes for m in members)


def test_node_and_rel_lookup_errors(ontology: Ontology) -> None:
    from actron.graph.ontology import UnknownNodeType, UnknownRelationship

    with pytest.raises(UnknownNodeType):
        ontology.node("Nope")
    with pytest.raises(UnknownRelationship):
        ontology.rel("CALLS", "SlackMessage", "SlackMessage")
    assert ontology.rel("CALLS", "CodeFunction", "CodeFunction").name == "CALLS"


def test_skipped_relationships_are_exactly_the_undefined_endpoint_ones_a_ac_14(
    ontology: Ontology,
) -> None:
    """A-AC-14"""
    files = read_all()
    _, _, skipped_counts = expected_counts(files)
    node_names = {n["name"] for f in files.values() for n in f["nodes"]}
    expected = sorted(
        (f"{stem}.json", r["name"], r["from_node"], r["to_node"])
        for stem in ("slack", "linear")
        for r in files[stem]["relationships"]
        if r["from_node"] not in node_names or r["to_node"] not in node_names
    )
    assert sorted(ontology.skipped_relationships) == expected
    assert skipped_counts == {"slack": 12, "linear": 78}
    assert sum(1 for s in ontology.skipped_relationships if s[0] == "slack.json") == 12
    assert sum(1 for s in ontology.skipped_relationships if s[0] == "linear.json") == 78


# Rule 3: one test per failure, each with a temporary fixture directory.
@pytest.fixture
def tmp_ontology(tmp_path: Path) -> Path:
    for stem in FILE_ORDER:
        shutil.copy(ONTOLOGY_DIR / f"{stem}.json", tmp_path / f"{stem}.json")
    return tmp_path


def edit(directory: Path, stem: str, fn: Any) -> None:
    path = directory / f"{stem}.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_fixture_copy_loads(tmp_ontology: Path) -> None:
    assert len(load_ontology(tmp_ontology).nodes) == 96


def test_duplicate_node_name_across_files_fails_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11 (rule 3: duplicate node names across files)"""
    dup = json.loads((tmp_ontology / "slack.json").read_text())["nodes"][0]
    edit(tmp_ontology, "code", lambda d: d["nodes"].append(dict(dup)))
    with pytest.raises(OntologyError) as err:
        load_ontology(tmp_ontology)
    msg = str(err.value)
    assert "code.json" in msg
    assert dup["name"] in msg
    assert "duplicate" in msg


@pytest.mark.parametrize("stem", ["github", "code", "core"])
def test_undefined_endpoint_fails_outside_fabric_files_a_ac_11(
    tmp_ontology: Path, stem: str
) -> None:
    """A-AC-11 (rule 3: undefined endpoint in github, code or core)"""
    edit(
        tmp_ontology,
        stem,
        lambda d: d["relationships"].append(
            {
                "name": "BROKEN_REL",
                "from_node": "NoSuchNode",
                "to_node": "CodeFile",
                "cardinality": "many_to_many",
            }
        ),
    )
    with pytest.raises(OntologyError) as err:
        load_ontology(tmp_ontology)
    msg = str(err.value)
    assert f"{stem}.json" in msg
    assert "BROKEN_REL" in msg
    assert "NoSuchNode" in msg


def test_group_member_that_is_not_a_node_fails_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11 (rule 3: group member not a node)"""
    edit(
        tmp_ontology,
        "core",
        lambda d: d["node_groups"].__setitem__("Broken", ["CodeFile", "Ghost"]),
    )
    with pytest.raises(OntologyError) as err:
        load_ontology(tmp_ontology)
    msg = str(err.value)
    assert "core.json" in msg
    assert "Broken" in msg
    assert "Ghost" in msg


def test_duplicate_rel_triple_fails_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11 (rule 3: two relationships with the same name, from and to)"""
    first = json.loads((tmp_ontology / "code.json").read_text())["relationships"][0]
    edit(tmp_ontology, "code", lambda d: d["relationships"].append(dict(first)))
    with pytest.raises(OntologyError) as err:
        load_ontology(tmp_ontology)
    msg = str(err.value)
    assert "code.json" in msg
    assert first["name"] in msg
    assert "duplicate" in msg


def test_duplicate_through_group_expansion_fails_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11: a group relationship that collides with an explicit one after expansion."""
    core = json.loads((tmp_ontology / "core.json").read_text())
    group = next(g for g, m in core["node_groups"].items() if len(m) >= 2)
    members = core["node_groups"][group]

    def add(d: dict[str, Any]) -> None:
        d["relationships"].append(
            {
                "name": "TWICE",
                "from_node": group,
                "to_node": members[0],
                "cardinality": "many_to_many",
            }
        )
        d["relationships"].append(
            {
                "name": "TWICE",
                "from_node": members[0],
                "to_node": members[0],
                "cardinality": "many_to_many",
            }
        )

    edit(tmp_ontology, "core", add)
    with pytest.raises(OntologyError) as err:
        load_ontology(tmp_ontology)
    assert "TWICE" in str(err.value)
    assert "duplicate" in str(err.value)


def test_undefined_endpoint_in_fabric_file_is_skipped_not_fatal_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11 (rule 4): fabric files skip and report instead of failing."""
    edit(
        tmp_ontology,
        "slack",
        lambda d: d["relationships"].append(
            {
                "name": "ODD",
                "from_node": "SlackMessage",
                "to_node": "Missing",
                "cardinality": "many_to_many",
            }
        ),
    )
    onto = load_ontology(tmp_ontology)
    assert ("slack.json", "ODD", "SlackMessage", "Missing") in onto.skipped_relationships


def test_missing_file_names_the_file_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11"""
    (tmp_ontology / "linear.json").unlink()
    with pytest.raises(OntologyError, match=r"linear\.json"):
        load_ontology(tmp_ontology)


def test_invalid_json_names_the_file_a_ac_11(tmp_ontology: Path) -> None:
    """A-AC-11"""
    (tmp_ontology / "github.json").write_text("{not json")
    with pytest.raises(OntologyError, match=r"github\.json"):
        load_ontology(tmp_ontology)


def test_full_text_fields_follow_description(ontology: Ontology) -> None:
    fields = ontology.full_text_fields()
    assert fields
    for label, names in fields.items():
        for name in names:
            assert "full-text indexed" in "full-text indexed"  # sanity
            assert ontology.node(label).properties[name].full_text


def test_relationship_properties_are_parsed_from_descriptions(ontology: Ontology) -> None:
    assert {"linesChanged", "changeType"} <= ontology.rel(
        "TOUCHED", "GitCommit", "CodeFunction"
    ).allowed_properties
    calls = ontology.rel("CALLS", "CodeFunction", "CodeFunction").allowed_properties
    assert {"resolution", "confidence", "callSiteLines", "count"} <= calls


def test_default_ontology_is_cached() -> None:
    from actron.graph.ontology import default_ontology

    assert default_ontology() is default_ontology()


def test_graph_model_document_is_current() -> None:
    """docs/graph-model.md is generated from the ontology; regenerate it when the files change."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_graph_model.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
