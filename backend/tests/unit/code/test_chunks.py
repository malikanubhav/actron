"""A-AC-28: chunks cover every line outside functions and classes (80 lines max, 10 lines overlap)."""

from __future__ import annotations

from actron.connectors.code.chunks import plan_chunks, split_run, uncovered_runs
from actron.connectors.code.parse import parse_file


def test_split_run_overlap() -> None:
    """A-AC-28"""
    assert split_run(1, 80) == [(1, 80)]
    assert split_run(1, 200) == [(1, 80), (71, 150), (141, 200)]
    assert split_run(5, 5) == [(5, 5)]


def test_uncovered_runs() -> None:
    """A-AC-28"""
    assert uncovered_runs(10, [(2, 3), (6, 8)]) == [(1, 1), (4, 5), (9, 10)]
    assert uncovered_runs(3, []) == [(1, 3)]
    assert uncovered_runs(3, [(1, 3)]) == []


def test_python_file_chunks_and_kinds() -> None:
    """A-AC-28"""
    src = "import os\n\nX = 1\n\n\ndef f():\n    return X\n\nY = 2\n"
    pf = parse_file("m.py", src.encode())
    chunks = plan_chunks("m.py", src, pf)
    assert [(c.start, c.end, c.kind) for c in chunks] == [(1, 5, "module_level"), (8, 9, "module_level")]
    assert chunks[0].text == "import os\n\nX = 1\n\n"


def test_config_data_other_and_docs() -> None:
    """A-AC-28"""
    assert plan_chunks("pyproject.toml", "a = 1\n", None)[0].kind == "config"
    assert plan_chunks("data/x.csv", "a,b\n1,2\n", None)[0].kind == "data"
    assert plan_chunks("notes.txt", "hello\n", None)[0].kind == "other"
    assert plan_chunks("README.md", "# T\n", None) == []
    assert plan_chunks("empty.txt", "", None) == []


def test_go_methods_outside_struct_are_covered() -> None:
    """A-AC-28"""
    src = "package p\n\ntype T struct{}\n\nfunc (t T) M() {}\n"
    pf = parse_file("p.go", src.encode())
    chunks = plan_chunks("p.go", src, pf)
    assert [(c.start, c.end) for c in chunks] == [(1, 2), (4, 4)]
