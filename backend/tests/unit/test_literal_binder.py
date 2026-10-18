"""A4: the safe literal binder (name validation, supported values, single pass, never re-scanned)."""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from actron.graph.store import bind_literal


def test_scalars_are_encoded() -> None:
    q = "RETURN $a, $b, $c, $d, $e, $f"
    out = bind_literal(q, {"a": None, "b": True, "c": False, "d": 7, "e": 1.5, "f": "x"})
    assert out == 'RETURN null, true, false, 7, 1.5, "x"'


def unescape(literal: str) -> str:
    """Reference decoder for the five escapes the binder emits."""
    assert literal[0] == literal[-1] == '"'
    body, out, i = literal[1:-1], [], 0
    table = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
    while i < len(body):
        if body[i] == "\\":
            out.append(table[body[i + 1]])
            i += 2
        else:
            assert body[i] != '"', "unescaped quote"
            out.append(body[i])
            i += 1
    return "".join(out)


def test_strings_are_escaped_and_non_ascii_stays_readable() -> None:
    """FalkorDB does not decode backslash-u escapes, so non-ASCII text goes in as it is (docs/falkordb.md)."""
    value = 'He said "hi"\n\tback\\slash é \U0001f600 中文'
    out = bind_literal("RETURN $v", {"v": value})
    literal = out[len("RETURN ") :]
    assert unescape(literal) == value
    assert "\n" not in literal
    assert "\\u" not in literal
    assert "\U0001f600" in literal


def test_nul_and_lone_surrogates_are_rejected() -> None:
    with pytest.raises(ValueError, match="NUL"):
        bind_literal("RETURN $v", {"v": "a\x00b"})
    with pytest.raises(ValueError, match="surrogate"):
        bind_literal("RETURN $v", {"v": "\ud83d"})


def test_lists_nest() -> None:
    assert bind_literal("RETURN $v", {"v": [1, [2, "a"], None]}) == 'RETURN [1, [2, "a"], null]'
    assert bind_literal("RETURN $v", {"v": []}) == "RETURN []"


def test_maps_are_supported_with_safe_keys() -> None:
    assert bind_literal("RETURN $v", {"v": {"id": "a", "n": 1}}) == 'RETURN {`id`: "a", `n`: 1}'
    with pytest.raises(ValueError, match="safe name"):
        bind_literal("RETURN $v", {"v": {"bad key": 1}})
    with pytest.raises(ValueError, match="safe name"):
        bind_literal("RETURN $v", {"v": {"a`b": 1}})


def test_substituted_text_is_not_scanned_again() -> None:
    """A value that looks like another parameter stays literal text."""
    out = bind_literal("RETURN $a, $b", {"a": "$b", "b": "real"})
    assert out == 'RETURN "$b", "real"'


def test_cypher_prefix_text_stays_inside_the_string() -> None:
    out = bind_literal("CREATE (n {t: $t})", {"t": "CYPHER x=1 RETURN 2"})
    assert out == 'CREATE (n {t: "CYPHER x=1 RETURN 2"})'


def test_names_must_match_template() -> None:
    with pytest.raises(ValueError, match="do not match"):
        bind_literal("RETURN $a", {"a": 1, "b": 2})
    with pytest.raises(ValueError, match="do not match"):
        bind_literal("RETURN $a, $b", {"a": 1})


@pytest.mark.parametrize("name", ["a b", "1a", "a-b", "a;b", "", "a`"])
def test_parameter_names_are_validated(name: str) -> None:
    with pytest.raises(ValueError, match="invalid parameter name"):
        bind_literal("RETURN 1", {name: 1})


@pytest.mark.parametrize("bad", [object(), {1, 2}, b"bytes", math.nan, math.inf, -math.inf])
def test_unsupported_values_raise(bad: Any) -> None:
    with pytest.raises(ValueError):
        bind_literal("RETURN $v", {"v": bad})


def test_repeated_parameter_is_replaced_everywhere() -> None:
    assert bind_literal("RETURN $a, $a", {"a": 1}) == "RETURN 1, 1"


def test_prefix_names_do_not_collide() -> None:
    assert bind_literal("RETURN $a, $ab", {"a": 1, "ab": 2}) == "RETURN 1, 2"


text = st.text(
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)), max_size=200
)


@given(text)
def test_any_string_round_trips(value: str) -> None:
    out = bind_literal("$v", {"v": value})
    assert unescape(out) == value
    assert "\n" not in out and "\r" not in out


@given(text, text)
def test_value_never_changes_other_parameters(a: str, b: str) -> None:
    out = bind_literal("$a|$b", {"a": a, "b": b})
    # Substituted text is final: the result is exactly the two literals around the separator.
    assert out == bind_literal("$a", {"a": a}) + "|" + bind_literal("$b", {"b": b})
