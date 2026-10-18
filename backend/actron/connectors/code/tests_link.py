"""Test detection and `TESTS`, `TESTS_CLASS`, `TEST_FILE_FOR` links (spec A, A6.7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from actron.connectors.code.model import ParsedFile
from actron.connectors.code.resolve import Resolution, Snapshot
from actron.graph import ids

NAMING_CONFIDENCE = 0.6
FILE_NAMING_CONFIDENCE = 0.8

_JS = ("typescript", "tsx", "javascript")


def is_test_file(path: str, language: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    parts = p.parts[:-1]
    lower_parts = [x.lower() for x in parts]
    if language == "python":
        return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
                or "tests" in lower_parts or "test" in lower_parts)
    if language in _JS:
        return (bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", name)) or bool(re.search(r"-test\.[cm]?[jt]sx?$", name))
                or "__tests__" in parts or "test" in lower_parts or "tests" in lower_parts
                or path.startswith("src/extension-test/") or any(x.endswith("-test") for x in lower_parts))
    if language == "clojure":
        return bool(re.search(r"_test\.clj[sc]?$", name)) or "test" in lower_parts
    if language == "go":
        return name.endswith("_test.go")
    if language == "java":
        return "src/test/" in path or bool(re.search(r"Tests?\.java$", name))
    if language == "rust":
        return "tests" in lower_parts
    return (any(x in ("spec", "test", "tests") for x in lower_parts) or bool(re.search(r"_test\.\w+$", name))
            or bool(re.search(r"Tests?\.\w+$", name)) or bool(re.search(r"_spec\.\w+$", name)))


def mark_tests(files: dict[str, ParsedFile]) -> set[str]:
    """Set `is_test` on test functions and classes; returns the set of test file paths."""
    test_files: set[str] = set()
    for path, pf in files.items():
        in_test_file = is_test_file(path, pf.language)
        if in_test_file:
            test_files.add(path)
        by_key = pf.by_key()
        for sym in pf.symbols:
            if sym.is_test:
                continue
            parent = by_key.get(sym.parent) if sym.parent else None
            lang = pf.language
            if lang == "python":
                if (sym.kind == "class" and sym.name.startswith("Test") and in_test_file) or (sym.kind == "function" and sym.name.startswith("test") and in_test_file and (
                        parent is None or (parent.kind == "class" and parent.name.startswith("Test")))):
                    sym.is_test = True
            elif lang == "go":
                if in_test_file and sym.kind == "function" and re.match(r"^(Test|Benchmark|Example)", sym.name):
                    sym.is_test = True
            elif lang == "java":
                if sym.kind == "class" and in_test_file and re.search(r"Tests?$", sym.name):
                    sym.is_test = True
            elif lang in _JS or lang in ("rust", "clojure"):
                pass  # parsers mark `it`/`test` callbacks, `#[test]` and `deftest`
            elif in_test_file and sym.kind == "function" and sym.name.lower().startswith("test"):
                sym.is_test = True
    return test_files


@dataclass
class TestLinks:
    tests: dict[tuple[str, str], tuple[str, float]] = field(default_factory=dict)
    tests_class: dict[tuple[str, str], tuple[str, float]] = field(default_factory=dict)
    test_file_for: dict[tuple[str, str], tuple[str, float]] = field(default_factory=dict)


def _strip_test_name(name: str) -> str | None:
    for pat in (r"^test_+(.+)$", r"^Test_?(.+)$", r"^test([A-Z].*)$", r"^(.+?)_?[Tt]est$"):
        m = re.match(pat, name)
        if m:
            return m.group(1)
    return None


def _file_stem(path: str) -> str:
    name = PurePosixPath(path).name
    stem = name.split(".", 1)[0]
    for pat in (r"^test_", r"_test$", r"-test$", r"_spec$", r"Tests?$"):
        stem = re.sub(pat, "", stem)
    return stem.lower()


def link_tests(snap: Snapshot, res: Resolution, test_files: set[str]) -> TestLinks:
    out = TestLinks()
    refs = snap.refs
    for (caller, callee), edge in res.calls.items():
        a, b = refs.get(caller), refs.get(callee)
        if a is not None and b is not None and a.sym.is_test and not b.sym.is_test:
            out.tests[(caller, callee)] = ("calls", edge.confidence)
    for (caller, callee), edge in res.instantiates.items():
        a, b = refs.get(caller), refs.get(callee)
        if a is not None and b is not None and a.sym.is_test and not b.sym.is_test:
            out.tests_class[(caller, callee)] = ("calls", edge.confidence)

    imported: dict[str, set[str]] = {}
    for (fa, fb) in res.imports:
        imported.setdefault(ids.parse_id(fa).parts["path"], set()).add(ids.parse_id(fb).parts["path"])

    # naming: test_make_response <-> make_response in an imported module
    for ref in refs.values():
        if not (ref.sym.is_test and ref.sym.kind == "function"):
            continue
        base = _strip_test_name(ref.sym.name)
        if not base:
            continue
        for target_path in imported.get(ref.path, set()):
            for name, target in snap.top.get(target_path, {}).items():
                if name.lower() != base.lower() or target.sym.is_test:
                    continue
                key = (ref.id, target.id)
                if target.sym.kind == "function" and key not in out.tests:
                    out.tests[key] = ("naming", NAMING_CONFIDENCE)
                elif target.sym.kind == "class" and key not in out.tests_class:
                    out.tests_class[key] = ("naming", NAMING_CONFIDENCE)

    # TEST_FILE_FOR by file name, else by where most TESTS targets live
    source_by_stem: dict[tuple[str, str], list[str]] = {}
    for path, pf in snap.files.items():
        if path in test_files:
            continue
        fam = pf.language if pf.language not in _JS else "js"
        source_by_stem.setdefault((fam, _file_stem(path)), []).append(path)
    for tpath in test_files:
        tpf = snap.files.get(tpath)
        if tpf is None:
            continue
        fam = tpf.language if tpf.language not in _JS else "js"
        tid = ids.code_file(snap.repo, tpath)
        cands = source_by_stem.get((fam, _file_stem(tpath)), [])
        preferred = [c for c in cands if c in imported.get(tpath, set())] or cands
        if len(preferred) == 1 and _file_stem(tpath):
            out.test_file_for[(tid, ids.code_file(snap.repo, preferred[0]))] = ("naming", FILE_NAMING_CONFIDENCE)
            continue
        counts: dict[str, int] = {}
        total = 0
        for (caller, callee) in list(out.tests) + list(out.tests_class):
            a = refs.get(caller)
            b = refs.get(callee)
            if a is None or b is None or a.path != tpath:
                continue
            counts[b.path] = counts.get(b.path, 0) + 1
            total += 1
        for spath, n in counts.items():
            if total and n / total > 0.5:
                out.test_file_for[(tid, ids.code_file(snap.repo, spath))] = ("calls", round(n / total, 3))
    return out
