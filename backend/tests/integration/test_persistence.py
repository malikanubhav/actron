"""A-AC-15: tricky values written through upsert_nodes read back identical after FalkorDB restarts.

The test starts its own FalkorDB container (see falkor_scratch.py), same pinned image and settings as
compose, so restarting it does not interrupt other people's test runs.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from actron.graph import ids
from actron.graph.ontology import Ontology
from actron.graph.store import Binding, GraphStore
from tests.integration.falkor_scratch import Server, server  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.slow]


TRICKY: dict[str, str] = {
    "double_quotes": 'she said "hello" and "bye"',
    "single_quotes": "it's a 'quoted' value",
    "both_quotes": """mix of ' and " and ''' and \"\"\"""",
    "backslashes": "C:\\path\\to\\file and \\n literally and \\\\ two",
    "newlines": "line one\nline two\r\nline three\n\n",
    "tabs": "col1\tcol2\t\tcol4",
    "emoji": "ship it \U0001f680\U0001f389 family \U0001f468\u200d\U0001f469\u200d\U0001f467",
    "cjk": "\u4e2d\u6587\u6d4b\u8bd5 \u65e5\u672c\u8a9e\u306e\u30c6\u30b9\u30c8 \ud55c\uad6d\uc5b4",
    "literal_param": "price is $param and $other and ${x}",
    "literal_cypher_prefix": "CYPHER x=1",
    "cypher_prefix_inline": "see CYPHER name='v' MATCH (n) RETURN n",
    "big_50kb": ("0123456789abcdef" * 64 + "\n") * 50,
    "braces_and_backticks": "{id: 'x'} `tick` [list] (paren) // comment /* c */",
    "unicode_escapes_text": "literal \\u0041 and \\ud83d and \\x41",
    "null_like": "null NULL true false 0 -1 1e5",
    "leading_trailing_space": "   padded   ",
    "empty_like": "-",
    "rtl_and_combining": "\u05e9\u05dc\u05d5\u05dd e\u0301 \u0645\u0631\u062d\u0628\u0627",
    "control_chars": "bell\x07 vt\x0b ff\x0c",
    "semicolon_injection": "x'}) DETACH DELETE n; //",
}


def message(key: str, text: str) -> dict[str, Any]:
    ts = f"{1700000000 + abs(hash(key)) % 100000}.{abs(hash(key)) % 1000000:06d}"
    return {
        "id": ids.slack_msg("CPERSIST", f"{key}"),
        "text": text,
        "ts": ts,
        "channelId": "CPERSIST",
        "postedAt": "2026-10-17T10:00:00Z",
    }


@pytest.mark.parametrize("binding", ["params", "literal"])
def test_tricky_values_survive_restart_a_ac_15(
    server: Server, ontology: Ontology, binding: Binding  # noqa: F811
) -> None:
    """A-AC-15"""
    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    store = GraphStore(server.url, name, ontology, workspace_id=name, binding=binding)
    rows = [message(k, v) for k, v in TRICKY.items()]
    # Extra rows: a long list of ordinary and quirky strings in one UNWIND batch (51 values in total).
    extras = {
        f"extra_{i}": f"value {i} with \"quote\" and 'apostrophe' and $p{i} \n\t \U0001f680"
        for i in range(31)
    }
    rows += [message(k, v) for k, v in extras.items()]
    assert len(rows) >= 51
    expected = {r["id"]: r["text"] for r in rows}
    store.upsert_nodes("SlackMessage", rows, batch_size=20)
    before = {n["id"]: n["text"] for n in store.list_nodes("SlackMessage", limit=500)}
    assert before == expected, "values differ before the restart"
    store.close()

    server.restart()

    after_store = GraphStore(server.url, name, ontology, workspace_id=name, binding=binding)
    try:
        after = {n["id"]: n["text"] for n in after_store.list_nodes("SlackMessage", limit=500)}
        assert set(after) == set(expected)
        bad = [k for k in expected if after[k] != expected[k]]
        assert not bad, f"values changed by restart in mode {binding}: {bad}"
        assert len(after["slack:msg:CPERSIST:big_50kb"]) == len(TRICKY["big_50kb"])
    finally:
        after_store.drop()
        after_store.close()


def test_list_and_numeric_properties_survive_restart_a_ac_15(
    server: Server, ontology: Ontology  # noqa: F811
) -> None:
    """A-AC-15: arrays, integers, booleans and floats also come back identical."""
    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    store = GraphStore(server.url, name, ontology, workspace_id=name)
    node_id = "linear:issue:persist-1"
    store.upsert_nodes(
        "LinearIssue",
        [
            {
                "id": node_id,
                "title": 'T "quoted"',
                "url": "https://l/p",
                "labelIds": ["a", 'b"c', "d'e", "\U0001f680"],
                "priority": 2,
                "estimate": 2.5,
                "createdByActron": True,
                "number": 42,
            }
        ],
    )
    store.close()
    server.restart()
    store = GraphStore(server.url, name, ontology, workspace_id=name)
    try:
        node = store.get_node(node_id)
        assert node is not None
        assert node["labelIds"] == ["a", 'b"c', "d'e", "\U0001f680"]
        assert (node["priority"], node["estimate"], node["createdByActron"], node["number"]) == (
            2,
            2.5,
            True,
            42,
        )
        assert node["title"] == 'T "quoted"'
    finally:
        store.drop()
        store.close()
