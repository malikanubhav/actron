"""Canonical ticket hash is invariant to key order and whitespace (B-AC-32, PROMPT 9.2)."""

from __future__ import annotations

import json
import random

from hypothesis import given
from hypothesis import strategies as st

from actron.flow.ticket import canonical_json, ticket_hash

scalars = st.one_of(st.text(max_size=20), st.integers(), st.booleans(), st.none())
values = st.recursive(scalars, lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=8), c, max_size=4),
                      max_leaves=12)
tickets = st.dictionaries(st.text(min_size=1, max_size=12).filter(lambda k: k != "revision"), values, max_size=8)


def _shuffled(obj: object, rnd: random.Random) -> object:
    if isinstance(obj, dict):
        items = list(obj.items())
        rnd.shuffle(items)
        return {k: _shuffled(v, rnd) for k, v in items}
    if isinstance(obj, list):
        return [_shuffled(v, rnd) for v in obj]
    return obj


@given(tickets, st.integers(min_value=0, max_value=2**16))
def test_hash_invariant_to_key_order(ticket: dict[str, object], seed: int) -> None:
    """B-AC-32: key order does not change the hash."""
    assert ticket_hash(ticket) == ticket_hash(_shuffled(ticket, random.Random(seed)))  # type: ignore[arg-type]


@given(tickets, st.integers(min_value=0, max_value=8))
def test_hash_invariant_to_whitespace(ticket: dict[str, object], indent: int) -> None:
    """B-AC-32: re-serialising with other whitespace and parsing back gives the same hash."""
    reparsed = json.loads(json.dumps(ticket, indent=indent))
    assert ticket_hash(reparsed) == ticket_hash(ticket)


@given(tickets, st.integers())
def test_revision_is_ignored(ticket: dict[str, object], rev: int) -> None:
    """B-AC-32: the revision number is not part of the hash."""
    assert ticket_hash({**ticket, "revision": rev}) == ticket_hash(ticket)
    assert "revision" not in json.loads(canonical_json({**ticket, "revision": rev}))


@given(tickets, st.text(min_size=1, max_size=10).filter(lambda k: k != "revision"), st.text(max_size=10))
def test_content_change_changes_hash(ticket: dict[str, object], key: str, value: str) -> None:
    """B-AC-32: changing a field changes the hash."""
    changed = {**ticket, key: value}
    if changed == ticket:
        return
    assert ticket_hash(changed) != ticket_hash(ticket)
