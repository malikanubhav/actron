"""Small helpers over tree-sitter nodes shared by the parsers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from actron.connectors.code.languages import parser_for
from actron.connectors.code.model import split_lines

Node = Any  # tree_sitter.Node (no type stubs)


def parse_tree(grammar: str, source: bytes) -> Node:
    return parser_for(grammar).parse(source).root_node


def text(node: Node | None) -> str:
    if node is None:
        return ""
    raw: bytes = node.text or b""
    return raw.decode("utf-8", errors="replace")


# tree-sitter 0.26.0 (as shipped here): `Point.row` / `Point.column` return a borrowed reference, which
# gives garbage for values above 256 and corrupts the heap. Tuple indexing (`point[0]`) is correct.


def start_line(node: Node) -> int:
    return int(node.start_point[0]) + 1


def end_line(node: Node) -> int:
    """Last line of a node, ignoring a trailing newline that tree-sitter puts on the next row."""
    point = node.end_point
    row = int(point[0])
    col = int(point[1])
    if col == 0 and row > int(node.start_point[0]):
        row -= 1
    return row + 1


def lines_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def source_lines(source: bytes) -> list[str]:
    return split_lines(source.decode("utf-8", errors="replace"))


def field(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


def named_children(node: Node) -> list[Node]:
    return [c for c in node.children if c.is_named]


def walk(node: Node) -> Iterator[Node]:
    """Pre-order walk over all descendants (iterative, safe on deep trees)."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def collect[T](body: Node | None, stop: frozenset[str], pick: Callable[[Node], T | None]) -> list[T]:
    """Walk `body` in source order, skipping subtrees whose type is in `stop`, keeping what `pick` returns."""
    out: list[T] = []
    if body is None:
        return out
    stack = list(reversed(body.children))
    while stack:
        n = stack.pop()
        if n.type in stop:
            continue
        got = pick(n)
        if got is not None:
            out.append(got)
        stack.extend(reversed(n.children))
    return out


def first_child_of_type(node: Node, *types: str) -> Node | None:
    for c in node.children:
        if c.type in types:
            return c
    return None


def string_value(node: Node | None) -> str | None:
    """Value of a string literal node without quotes (best effort)."""
    if node is None:
        return None
    raw = text(node)
    for q in ('"""', "'''", '"', "'", "`"):
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
            return raw[len(q) : -len(q)]
    for prefix in ("r", "b", "f", "u", "rb", "br", "fr", "rf"):
        if raw.lower().startswith(prefix) and len(raw) > len(prefix) and raw[len(prefix)] in "\"'":
            return string_value_raw(raw[len(prefix) :])
    return raw


def string_value_raw(raw: str) -> str:
    for q in ('"""', "'''", '"', "'"):
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
            return raw[len(q) : -len(q)]
    return raw


def leading_comment(lines: list[str], start: int, markers: tuple[str, ...] = ("//", "/*", "*", "#")) -> str | None:
    """Comment block directly above line `start` (1-based), used as a docstring for C-like languages."""
    out: list[str] = []
    i = start - 2
    while i >= 0:
        s = lines[i].strip()
        if s and s.startswith(markers):
            out.append(s)
            i -= 1
            continue
        break
    if not out:
        return None
    cleaned = []
    for s in reversed(out):
        for m in ("/**", "/*", "*/", "///", "//!", "//", "#", "*"):
            if s.startswith(m):
                s = s[len(m) :]
                break
        s = s.removesuffix("*/").strip()
        cleaned.append(s)
    doc = "\n".join(c for c in cleaned if c).strip()
    return doc or None
