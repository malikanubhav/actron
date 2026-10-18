"""A-AC-41: blame aggregation gives lines and lineShare per author on a two-author file."""

from __future__ import annotations

from pathlib import Path

from actron.connectors.code.blame import aggregate, read_blame
from tests.unit.code.repo_builder import SyntheticRepo

ADA = ("Ada Lovelace", "ada@example.com")
BOB = ("Bob Builder", "BOB@example.com")


def test_two_author_blame(tmp_path: Path) -> None:
    """A-AC-41"""
    r = SyntheticRepo(tmp_path / "repo")
    r.write("m.py", "def f():\n    a = 1\n    b = 2\n    return a + b\n\n\ndef g():\n    return 0\n")
    r.commit("ada writes", author=ADA)
    r.write("m.py", "def f():\n    a = 1\n    b = 3\n    c = 4\n    return a + b\n\n\ndef g():\n    return 0\n")
    r.commit("bob edits f", author=BOB)
    blame = read_blame(r.root, "m.py")
    assert len(blame) == 9
    assert {b.line: b.author_email for b in blame}[3] == "bob@example.com"
    f = {s.email: (s.lines, s.line_share) for s in aggregate(blame, 1, 5)}
    assert f == {"ada@example.com": (3, 0.6), "bob@example.com": (2, 0.4)}
    g = {s.email: (s.lines, s.line_share) for s in aggregate(blame, 8, 9)}
    assert g == {"ada@example.com": (2, 1.0)}
    whole = {s.email: s.lines for s in aggregate(blame, 1, 9)}
    assert whole == {"ada@example.com": 7, "bob@example.com": 2}
    assert read_blame(r.root, "nope.py") == []
