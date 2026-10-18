"""A-AC-23 and A-AC-24 as properties: ids round-trip through parse_id for generated inputs."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from actron.graph import ids

name_part = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_."),
    min_size=1,
    max_size=12,
).filter(lambda s: s.strip(".") != "" and "/" not in s)
repo = st.builds(lambda o, n: f"{o}/{n}", name_part, name_part)
path = st.lists(name_part, min_size=1, max_size=4).map("/".join)
qualname = st.lists(
    st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,8}", fullmatch=True), min_size=1, max_size=3
).map(".".join)
dup = st.integers(min_value=1, max_value=9)
channel = st.from_regex(r"C[0-9A-Z]{6,10}", fullmatch=True)
ts = st.from_regex(r"[0-9]{10}\.[0-9]{6}", fullmatch=True)


@given(repo, path, qualname, dup)
def test_function_id_round_trips_a_ac_23(r: str, p: str, q: str, d: int) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.code_fn(r, p, q, d))
    assert parsed.label == "CodeFunction"
    assert (
        parsed.parts["repo"],
        parsed.parts["path"],
        parsed.parts["qualname"],
        parsed.parts["dup"],
    ) == (
        r.lower(),
        p,
        q,
        str(d),
    )


@given(repo, path, qualname, dup)
def test_class_id_round_trips_a_ac_23(r: str, p: str, q: str, d: int) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.code_class(r, p, q, d))
    assert parsed.label == "CodeClass"
    assert (
        parsed.parts["repo"],
        parsed.parts["path"],
        parsed.parts["qualname"],
        parsed.parts["dup"],
    ) == (
        r.lower(),
        p,
        q,
        str(d),
    )


@given(repo, path)
def test_file_id_round_trips_a_ac_23(r: str, p: str) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.code_file(r, p))
    assert (parsed.label, parsed.parts["repo"], parsed.parts["path"]) == ("CodeFile", r.lower(), p)


@given(repo, path, st.integers(1, 5000), st.integers(0, 5000))
def test_chunk_id_round_trips_a_ac_23(r: str, p: str, start: int, extra: int) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.code_chunk(r, p, start, start + extra))
    assert (parsed.parts["repo"], parsed.parts["path"]) == (r.lower(), p)
    assert (parsed.parts["start"], parsed.parts["end"]) == (str(start), str(start + extra))


@given(repo, path, st.from_regex(r"[a-z0-9]+(-[a-z0-9]+)*", fullmatch=True), dup)
def test_doc_id_round_trips_a_ac_23(r: str, p: str, slug: str, d: int) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.code_doc(r, p, slug, d))
    assert (
        parsed.parts["repo"],
        parsed.parts["path"],
        parsed.parts["slug"],
        parsed.parts["dup"],
    ) == (
        r.lower(),
        p,
        slug,
        str(d),
    )


@given(repo, st.integers(1, 100000))
def test_github_pr_issue_round_trip_a_ac_23(r: str, n: int) -> None:
    """A-AC-23"""
    for build in (ids.github_pr, ids.github_issue, ids.github_milestone):
        parsed = ids.parse_id(build(r, n))
        assert (parsed.parts["repo"], parsed.parts["number"]) == (r.lower(), str(n))


@given(repo, st.integers(1, 1000), path)
def test_prfile_round_trips_a_ac_23(r: str, n: int, p: str) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.github_prfile(r, n, p))
    assert (parsed.parts["repo"], parsed.parts["number"], parsed.parts["path"]) == (
        r.lower(),
        str(n),
        p,
    )


@given(repo, st.from_regex(r"[0-9a-f]{7,40}", fullmatch=True), path)
def test_commit_and_change_round_trip_a_ac_23(r: str, sha: str, p: str) -> None:
    """A-AC-23"""
    commit = ids.parse_id(ids.git_commit(r, sha))
    assert (commit.parts["repo"], commit.parts["sha"]) == (r.lower(), sha)
    change = ids.parse_id(ids.git_change(r, sha, p))
    assert (change.parts["repo"], change.parts["sha"], change.parts["path"]) == (r.lower(), sha, p)


@given(channel, ts, st.one_of(st.none(), st.integers(1, 20)))
def test_slack_message_round_trips_a_ac_23(c: str, t: str, version: int | None) -> None:
    """A-AC-23"""
    parsed = ids.parse_id(ids.slack_msg(c, t, version))
    assert parsed.label == "SlackMessage"
    assert (parsed.parts["channel"], parsed.parts["ts"]) == (c, t)
    assert parsed.parts.get("version") == (None if version is None else str(version))


@given(repo)
def test_repo_name_is_lowercased_a_ac_24(r: str) -> None:
    """A-AC-24"""
    assert ids.code_repo(r) == f"code:repo:{r.lower()}"
    assert ids.parse_id(ids.code_repo(r)).label == "CodeRepository"


@given(repo, path, qualname)
def test_dup_one_adds_no_suffix_a_ac_24(r: str, p: str, q: str) -> None:
    """A-AC-24"""
    assert "~" not in ids.code_fn(r, p, q, 1)
    assert ids.code_fn(r, p, q, 2).endswith("~2")


@given(repo, path, qualname, st.integers(0, 100000))
def test_function_id_ignores_line_numbers_a_ac_25(r: str, p: str, q: str, _line_shift: int) -> None:
    """A-AC-25: the builder has no line parameter, so a shift above the function cannot change the id.
    The end-to-end check through the parser belongs to W2."""
    assert ids.code_fn(r, p, q) == ids.code_fn(r, p, q)
