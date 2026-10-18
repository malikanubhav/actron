"""A-AC-39 (parsing part): git log records with statuses, old paths, numstat, merges; refs."""

from __future__ import annotations

from pathlib import Path

from actron.connectors.code.git_log import BlobReader, is_ancestor, read_log, read_refs
from tests.unit.code.repo_builder import SyntheticRepo

BOB = ("Bob Builder", "Bob@Example.com")


def _repo(tmp_path: Path) -> SyntheticRepo:
    r = SyntheticRepo(tmp_path / "repo")
    r.write("app.py", "def a():\n    return 1\n")
    r.write("old.py", "def moved():\n    return 2\n")
    r.write_bytes("logo.png", b"\x89PNG\x00\x01")
    r.commit("init")
    r.write("app.py", "def a():\n    return 10\n")
    r.commit("modify a", author=BOB)
    r.move("old.py", "new.py")
    r.commit("rename file")
    r.remove("logo.png")
    r.commit("delete logo")
    r.git("checkout", "-q", "-b", "feature")
    r.write("feat.py", "def feat():\n    return 3\n")
    r.commit("feature work")
    r.git("checkout", "-q", "main")
    r.write("app.py", "def a():\n    return 11\n")
    r.commit("main work")
    r.git("merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    return r


def test_read_log_statuses_and_merge(tmp_path: Path) -> None:
    """A-AC-39"""
    r = _repo(tmp_path)
    commits = list(read_log(r.root, None, 100))
    by_subject = {c.subject: c for c in commits}
    assert commits[0].subject == "merge feature" and commits[0].is_merge and commits[0].changes == []
    assert len(commits[0].parents) == 2
    init = by_subject["init"]
    assert {(c.status, c.path) for c in init.changes} == {("added", "app.py"), ("added", "old.py"),
                                                          ("added", "logo.png")}
    logo = next(c for c in init.changes if c.path == "logo.png")
    assert logo.is_binary
    mod = by_subject["modify a"]
    assert mod.author_email == "Bob@Example.com" and mod.author_name == "Bob Builder"
    ch = mod.changes[0]
    assert (ch.status, ch.additions, ch.deletions) == ("modified", 1, 1)
    assert ch.old_blob and ch.new_blob and ch.old_blob != ch.new_blob
    ren = by_subject["rename file"].changes[0]
    assert (ren.status, ren.path, ren.old_path, ren.similarity) == ("renamed", "new.py", "old.py", 1.0)
    dele = by_subject["delete logo"].changes[0]
    assert dele.status == "deleted" and dele.new_blob is None
    assert by_subject["modify a"].authored_at.startswith("2026-01-01T")


def test_incremental_range_and_ancestry(tmp_path: Path) -> None:
    """A-AC-42"""
    r = _repo(tmp_path)
    head = r.head()
    r.write("app.py", "def a():\n    return 12\n")
    r.commit("next one")
    r.write("app.py", "def a():\n    return 13\n")
    r.commit("next two")
    new = list(read_log(r.root, head, 100))
    assert [c.subject for c in new] == ["next two", "next one"]
    assert is_ancestor(r.root, head)
    newest = r.head()
    r.git("reset", "-q", "--hard", "HEAD~1")
    r.write("app.py", "def a():\n    return 99\n")
    r.commit("rewritten")
    assert not is_ancestor(r.root, newest)  # history rewritten (force push)


def test_refs_and_blob_reader(tmp_path: Path) -> None:
    """A-AC-39"""
    r = _repo(tmp_path)
    r.git("tag", "-a", "v1.0", "-m", "first release")
    refs = {(x.kind, x.name): x for x in read_refs(r.root)}
    assert ("branch", "main") in refs and ("branch", "feature") in refs
    assert refs[("tag", "v1.0")].sha == r.head() and refs[("tag", "v1.0")].message == "first release"
    with BlobReader(r.root) as blobs:
        assert blobs.read("HEAD:app.py") == b"def a():\n    return 11\n"
        assert blobs.read("HEAD:missing.py") is None
        assert blobs.read("HEAD:new.py") == b"def moved():\n    return 2\n"
