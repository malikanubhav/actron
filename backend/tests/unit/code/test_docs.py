"""A-AC-32: Markdown and rst sections, slugs with `~n`, hierarchy, explicit mentions."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.docs import MentionIndex, find_mentions, split_document

MD = dedent(
    """\
    Intro line before any heading.

    # Calva Guide

    Some text about `src/extension.ts` and `activate`.

    ## Setup
    Run `npm install`.

    ```bash
    # not a heading
    ```

    ## Setup

    Second setup.

    Usage
    -----
    Call `Service.run()` or `missing_fn`.

    Big Title
    =========
    End.
    """
)

RST = dedent(
    """\
    =====
    Title
    =====

    Intro.

    Section A
    ---------
    Text with ``helper``.

    Sub A
    ~~~~~
    More.

    Section B
    ---------
    Last.
    """
)


def test_markdown_sections_slugs_and_hierarchy() -> None:
    """A-AC-32"""
    secs = split_document("docs/guide.md", MD)
    assert [(s.title, s.level, s.key) for s in secs] == [
        ("guide.md", 0, "guide-md"),
        ("Calva Guide", 1, "calva-guide"),
        ("Setup", 2, "setup"),
        ("Setup", 2, "setup~2"),
        ("Usage", 2, "usage"),
        ("Big Title", 1, "big-title"),
    ]
    assert secs[2].parent == 1 and secs[3].parent == 1 and secs[4].parent == 1
    assert secs[1].parent is None and secs[5].parent is None
    # sections partition the file: every line is in exactly one section
    lines = MD.count("\n")
    covered = [n for s in secs for n in range(s.start, s.end + 1)]
    assert sorted(covered) == list(range(1, lines + 1))
    assert secs[2].start == 7 and secs[2].end == 13


def test_rst_sections() -> None:
    """A-AC-32"""
    secs = split_document("docs/index.rst", RST)
    assert [(s.title, s.level) for s in secs] == [("Title", 1), ("Section A", 2), ("Sub A", 3), ("Section B", 2)]
    assert secs[0].start == 1
    assert secs[2].parent == 1 and secs[3].parent == 0
    covered = sorted(n for s in secs for n in range(s.start, s.end + 1))
    assert covered == list(range(1, RST.count("\n") + 1))


def test_explicit_mentions() -> None:
    """A-AC-32"""
    idx = MentionIndex(files={"src/extension.ts": "F1", "README.md": "F2"})
    idx.add_symbol("CodeFunction", "FN1", "activate", "activate")
    idx.add_symbol("CodeFunction", "FN2", "run", "Service.run")
    idx.add_symbol("CodeClass", "C1", "Service", "Service")
    idx.add_symbol("CodeFunction", "FN3", "dup", "dup")
    idx.add_symbol("CodeFunction", "FN4", "dup", "dup")
    text = "See `src/extension.ts`, `activate`, `Service.run()`, `Service`, `dup`, `README.md` and `nothing`."
    assert find_mentions(text, idx) == [
        ("CodeFile", "F1"), ("CodeFunction", "FN1"), ("CodeFunction", "FN2"), ("CodeClass", "C1"),
        ("CodeFile", "F2"),
    ]
    assert find_mentions("```\n`activate`\n```", idx) == []
