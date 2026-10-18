"""Spec coverage: every acceptance id in specs/ must be referenced by at least one test.

Scans `specs/*.md` for ids like A-AC-12, B-AC-3, C-AC-41 and the test trees
(`backend/tests`, `frontend/tests`, `frontend/**/*.test.ts(x)`) for references.
Prints a table per spec and exits 1 when any id has no test.

Usage: python scripts/spec_coverage.py [--quiet] [--json]
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"\b([ABC])-AC-(\d{1,3})\b")
TEST_DIRS = [ROOT / "backend" / "tests", ROOT / "frontend" / "tests", ROOT / "frontend" / "lighthouserc.json"]
TEST_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml"}
SKIP_PARTS = {"node_modules", ".next", "__pycache__", "screenshots", "fixtures"}


def spec_ids() -> dict[str, set[int]]:
    ids: dict[str, set[int]] = defaultdict(set)
    for spec in sorted((ROOT / "specs").glob("[ABC]-*.md")):
        for letter, num in ID_RE.findall(spec.read_text(encoding="utf-8")):
            ids[letter].add(int(num))
    return ids


def test_refs() -> dict[str, dict[int, set[str]]]:
    refs: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for base in TEST_DIRS:
        if not base.exists():
            continue
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            if not path.is_file() or path.suffix not in TEST_SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.relative_to(ROOT).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for letter, num in ID_RE.findall(text):
                refs[letter][int(num)].add(str(path.relative_to(ROOT)))
    return refs


def main() -> int:
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv
    ids = spec_ids()
    refs = test_refs()
    missing: dict[str, list[int]] = {}
    summary = []
    for letter in sorted(ids):
        wanted = sorted(ids[letter])
        gaps = [n for n in wanted if n not in refs[letter]]
        missing[letter] = gaps
        summary.append((letter, len(wanted), len(wanted) - len(gaps), gaps))
    if as_json:
        print(json.dumps({"specs": {s[0]: {"total": s[1], "covered": s[2], "missing": s[3]} for s in summary}}))
    else:
        print(f"{'Spec':<6}{'Criteria':>10}{'Covered':>10}{'Missing':>10}")
        for letter, total, covered, gaps in summary:
            print(f"{letter:<6}{total:>10}{covered:>10}{len(gaps):>10}")
        if not quiet:
            for letter, gaps in missing.items():
                if gaps:
                    print(f"\n{letter} missing: " + ", ".join(f"{letter}-AC-{n}" for n in gaps))
    return 1 if any(missing.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
