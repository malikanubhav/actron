"""A-AC-23, A-AC-24, A-AC-25: id formats from spec A.C3, parsing, and stability under line changes."""

from __future__ import annotations

import pytest

from actron.graph import ids

CASES: list[tuple[str, str]] = [
    (ids.code_repo("BetterThanTomorrow/Calva"), "code:repo:betterthantomorrow/calva"),
    (ids.code_component("Owner/Name", "."), "code:component:owner/name:."),
    (ids.code_component("Owner/Name", "packages/Web"), "code:component:owner/name:packages/Web"),
    (ids.code_dep("NPM", "Mocha"), "code:dep:npm:mocha"),
    (ids.code_file("Owner/Name", "src/Extension.ts"), "code:file:owner/name:src/Extension.ts"),
    (
        ids.code_class("Owner/Name", "src/A.ts", "Outer.Inner"),
        "code:class:owner/name:src/A.ts::Outer.Inner",
    ),
    (
        ids.code_class("Owner/Name", "src/A.ts", "Outer", 2),
        "code:class:owner/name:src/A.ts::Outer~2",
    ),
    (
        ids.code_fn("Owner/Name", "src/extension.ts", "activate"),
        "code:fn:owner/name:src/extension.ts::activate",
    ),
    (ids.code_fn("Owner/Name", "a.py", "Cls.method", 3), "code:fn:owner/name:a.py::Cls.method~3"),
    (ids.code_chunk("Owner/Name", "src/a.ts", 1, 54), "code:chunk:owner/name:src/a.ts#L1-L54"),
    (ids.code_doc("Owner/Name", "README.md", "install"), "code:doc:owner/name:README.md#install"),
    (
        ids.code_doc("Owner/Name", "README.md", "install", 2),
        "code:doc:owner/name:README.md#install~2",
    ),
    (ids.code_owners("Owner/Name", 7), "code:owners:owner/name:7"),
    (ids.git_commit("Owner/Name", "ABCDEF1"), "git:commit:owner/name:abcdef1"),
    (ids.git_author("Dev@Example.COM"), "git:author:dev@example.com"),
    (ids.git_branch("Owner/Name", "feature/x"), "git:branch:owner/name:feature/x"),
    (ids.git_tag("Owner/Name", "v1.0"), "git:tag:owner/name:v1.0"),
    (ids.git_change("Owner/Name", "abc123", "src/A.ts"), "git:change:owner/name:abc123:src/A.ts"),
    (ids.github_repo(42), "github:repo:42"),
    (ids.github_org(7), "github:org:7"),
    (ids.github_user(9), "github:user:9"),
    (ids.github_pr("Owner/Name", 12), "github:pr:owner/name#12"),
    (ids.github_prfile("Owner/Name", 12, "src/A.ts"), "github:prfile:owner/name#12:src/A.ts"),
    (ids.github_review(5), "github:review:5"),
    (ids.github_review_comment(6), "github:reviewcomment:6"),
    (ids.github_issue("Owner/Name", 3), "github:issue:owner/name#3"),
    (ids.github_issue_comment(8), "github:issuecomment:8"),
    (ids.github_label("Owner/Name", "bug"), "github:label:owner/name:bug"),
    (ids.github_milestone("Owner/Name", 2), "github:milestone:owner/name#2"),
    (ids.github_release(11), "github:release:11"),
    (ids.github_branch("Owner/Name", "main"), "github:branch:owner/name:main"),
    (ids.github_run(13), "github:run:13"),
    (ids.github_check(14), "github:check:14"),
    (ids.slack_workspace("T0123"), "slack:workspace:T0123"),
    (ids.slack_channel("C0456"), "slack:channel:C0456"),
    (ids.slack_user("U1"), "slack:user:U1"),
    (ids.slack_msg("C0456", "1712345678.000100"), "slack:msg:C0456:1712345678.000100"),
    (ids.slack_msg("C0456", "1712345678.000100", 2), "slack:msg:C0456:1712345678.000100@v2"),
    (ids.slack_usergroup("S1"), "slack:usergroup:S1"),
    (ids.slack_file("F1"), "slack:file:F1"),
    (ids.slack_reaction("C1", "1.2", "eyes"), "slack:reaction:C1:1.2:eyes"),
    (ids.linear_team("u-1"), "linear:team:u-1"),
    (ids.linear_user("u-2"), "linear:user:u-2"),
    (ids.linear_issue("u-3"), "linear:issue:u-3"),
    (ids.linear_issue("u-3", 1), "linear:issue:u-3@v1"),
    (ids.linear_comment("u-4"), "linear:comment:u-4"),
    (ids.linear_state("u-5"), "linear:state:u-5"),
    (ids.linear_label("u-6"), "linear:label:u-6"),
    (ids.linear_project("u-7"), "linear:project:u-7"),
    (ids.workspace("acme"), "actron:workspace:acme"),
    (ids.request("req_01ABC"), "actron:request:req_01ABC"),
    (ids.investigation("inv1"), "actron:investigation:inv1"),
    (ids.build("b1"), "actron:build:b1"),
]


@pytest.mark.parametrize(("built", "expected"), CASES)
def test_documented_format_a_ac_23(built: str, expected: str) -> None:
    """A-AC-23"""
    assert built == expected


@pytest.mark.parametrize(("built", "_"), CASES)
def test_every_id_resolves_to_a_label_a_ac_23(built: str, _: str) -> None:
    """A-AC-23: parse_id knows every prefix, and the label exists in the ontology."""
    from actron.config import REPO_ROOT
    from actron.graph.ontology import load_ontology

    parsed = ids.parse_id(built)
    assert parsed.label in load_ontology(REPO_ROOT / "ontology").nodes


def test_every_prefix_is_covered_by_a_builder_a_ac_23() -> None:
    """A-AC-23: each id prefix in the label table has a documented example above."""
    seen = {":".join(built.split(":", 2)[:2]) for built, _ in CASES}
    core_with_hashes = {
        "actron:person",
        "actron:identity",
        "actron:ref",
        "actron:feature",
        "actron:decision",
        "actron:procedure",
        "actron:team",
    }
    assert set(ids.PREFIX_LABELS) - seen <= core_with_hashes


def test_repo_lowercased_path_and_qualname_keep_case_a_ac_24() -> None:
    """A-AC-24"""
    fn = ids.code_fn("Foo/Bar", "Src/MyFile.ts", "MyClass.doThing")
    assert fn == "code:fn:foo/bar:Src/MyFile.ts::MyClass.doThing"


def test_dup_suffix_only_from_two_a_ac_24() -> None:
    """A-AC-24"""
    assert "~" not in ids.code_fn("a/b", "x.py", "f", 1)
    assert ids.code_fn("a/b", "x.py", "f", 2).endswith("::f~2")
    assert ids.code_class("a/b", "x.py", "C", 2).endswith("::C~2")
    assert ids.code_doc("a/b", "R.md", "s", 3).endswith("#s~3")
    with pytest.raises(ids.InvalidId):
        ids.code_fn("a/b", "x.py", "f", 0)


@pytest.mark.parametrize("bad", ["justname", "a/b/c", "/", "a/", "/b", ""])
def test_bad_repo_rejected(bad: str) -> None:
    with pytest.raises(ids.InvalidId):
        ids.code_repo(bad)


def test_function_ids_do_not_contain_line_numbers_a_ac_25() -> None:
    """A-AC-25: the id is built from repo, path and qualified name only, so inserting lines above a
    function cannot change it. The parser-level check is in W2's tests (tests/unit/code)."""
    before = ids.code_fn("a/b", "src/x.py", "Outer.method")
    after = ids.code_fn(
        "a/b", "src/x.py", "Outer.method"
    )  # same inputs after "lines were inserted"
    assert before == after
    assert "#L" not in before
    assert not any(part.isdigit() for part in before.split("::")[-1].split("."))


def test_parse_function_and_class_ids() -> None:
    parsed = ids.parse_id(ids.code_fn("a/b", "src/x.py", "Outer.inner", 2))
    assert parsed.label == "CodeFunction"
    assert parsed.parts["repo"] == "a/b"
    assert parsed.parts["path"] == "src/x.py"
    assert parsed.parts["qualname"] == "Outer.inner"
    assert parsed.parts["dup"] == "2"
    assert ids.parse_id(ids.code_class("a/b", "x.py", "C")).parts["dup"] == "1"


def test_parse_chunk_doc_and_slack_version() -> None:
    chunk = ids.parse_id(ids.code_chunk("a/b", "x.py", 3, 9))
    assert (chunk.parts["start"], chunk.parts["end"]) == ("3", "9")
    doc = ids.parse_id(ids.code_doc("a/b", "R.md", "usage", 2))
    assert (doc.parts["slug"], doc.parts["dup"]) == ("usage", "2")
    msg = ids.parse_id(ids.slack_msg("C1", "1.5", 3))
    assert msg.parts["version"] == "3"
    assert msg.parts["ts"] == "1.5"


@pytest.mark.parametrize("bad", ["nope", "a:b", "unknown:prefix:x", "code:fn:no-double-colon"])
def test_parse_rejects_unknown_ids(bad: str) -> None:
    with pytest.raises(ids.InvalidId):
        ids.parse_id(bad)


def test_label_of_and_graph_name() -> None:
    assert ids.label_of("slack:msg:C1:1.2") == "SlackMessage"
    assert ids.graph_name("actron", "my-ws") == "actron_my_ws"


def test_slugify_and_stable_uuid() -> None:
    assert ids.slugify("  Hello, World!  ") == "hello-world"
    assert ids.slugify("!!!") == "section"
    assert ids.stable_uuid("a", "b") == ids.stable_uuid("a", "b")
    assert ids.stable_uuid("a", "b") != ids.stable_uuid("ab")
    assert ids.person("ws", "k") == ids.person("ws", "k")
    assert ids.decision("x", "y") == ids.decision("x", "y")
    assert ids.feature("My Feature") == "actron:feature:my-feature"
    assert ids.procedure("Release Notes") == "actron:procedure:release-notes"
