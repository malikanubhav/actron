"""A-AC-28 (property): functions, classes, chunks and document sections cover every line of a file;
chunks never overlap a function or class and are at most 80 lines. A-AC-25: ids stay stable when unrelated
lines shift."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from actron.connectors.code.chunks import plan_chunks
from actron.connectors.code.docs import split_document
from actron.connectors.code.model import split_lines
from actron.connectors.code.parse import parse_file

_names = st.sampled_from(["alpha", "beta", "gamma", "delta", "run", "helper"])


@st.composite
def py_block(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["blank", "stmt", "func", "class", "comment", "long"]))
    name = draw(_names)
    if kind == "blank":
        return "\n" * draw(st.integers(1, 3))
    if kind == "stmt":
        return f"{name.upper()} = {draw(st.integers(0, 99))}\n"
    if kind == "comment":
        return f"# {name}\n"
    if kind == "long":
        return "".join(f"V{i} = {i}\n" for i in range(draw(st.integers(70, 200))))
    if kind == "func":
        body = "".join(f"    x{i} = {i}\n" for i in range(draw(st.integers(1, 5))))
        nested = f"    def inner_{name}():\n        return 1\n" if draw(st.booleans()) else ""
        return f"def {name}():\n{nested}{body}    return {name}()\n"
    methods = "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(draw(st.integers(0, 3))))
    return f"class {name.title()}:\n    '''doc'''\n{methods}"


@st.composite
def ts_block(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["blank", "stmt", "func", "class", "arrow", "test"]))
    name = draw(_names)
    if kind == "blank":
        return "\n" * draw(st.integers(1, 3))
    if kind == "stmt":
        return f"console.log({draw(st.integers(0, 9))});\n"
    if kind == "func":
        return f"export function {name}(a: number) {{\n  return a + 1;\n}}\n"
    if kind == "arrow":
        return f"const {name}Fn = () => {{\n  {name}();\n}};\n"
    if kind == "test":
        return f"describe('{name}', () => {{\n  it('works', () => {{\n    {name}();\n  }});\n}});\n"
    return f"class {name.title()} {{\n  m() {{ return 1; }}\n}}\n"


def _assert_coverage(path: str, text: str) -> None:
    lines = split_lines(text)
    pf = parse_file(path, text.encode())
    sym_lines: set[int] = set()
    if pf is not None:
        for s in pf.symbols:
            sym_lines.update(range(s.start_line, s.end_line + 1))
    chunk_lines: set[int] = set()
    for c in plan_chunks(path, text, pf):
        assert c.end - c.start + 1 <= 80
        span = set(range(c.start, c.end + 1))
        assert not (span & sym_lines), "chunk overlaps a function or class"
        chunk_lines |= span
    doc_lines: set[int] = set()
    if path.endswith((".md", ".rst")):
        for sec in split_document(path, text):
            doc_lines.update(range(sec.start, sec.end + 1))
    assert sym_lines | chunk_lines | doc_lines == set(range(1, len(lines) + 1))


@settings(max_examples=120, deadline=None)
@given(st.lists(py_block(), min_size=0, max_size=12))
def test_python_coverage(blocks: list[str]) -> None:
    """A-AC-28"""
    _assert_coverage("pkg/mod.py", "".join(blocks))


@settings(max_examples=120, deadline=None)
@given(st.lists(ts_block(), min_size=0, max_size=12))
def test_typescript_coverage(blocks: list[str]) -> None:
    """A-AC-28"""
    _assert_coverage("src/mod.ts", "".join(blocks))


@settings(max_examples=120, deadline=None)
@given(st.lists(st.sampled_from(["# H1\n", "## H2\n", "text\n", "\n", "Title\n=====\n", "```\n# x\n```\n",
                                  "- item\n", "Sub\n---\n"]), max_size=20))
def test_markdown_coverage(blocks: list[str]) -> None:
    """A-AC-28"""
    _assert_coverage("docs/x.md", "".join(blocks))


@settings(max_examples=60, deadline=None)
@given(st.lists(py_block(), min_size=1, max_size=8), st.integers(1, 30))
def test_ids_stable_when_lines_shift(blocks: list[str], shift: int) -> None:
    """A-AC-25"""
    text = "".join(blocks)
    a = parse_file("m.py", text.encode())
    b = parse_file("m.py", ("# shifted\n" * shift + "\n" + text).encode())
    assert a is not None and b is not None
    assert [s.key for s in a.symbols] == [s.key for s in b.symbols]
    assert [s.content_hash for s in a.symbols] == [s.content_hash for s in b.symbols]
