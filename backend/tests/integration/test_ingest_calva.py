"""Real data: BetterThanTomorrow/calva (public, MIT) at a pinned commit, ingested into graph
`actron_calva_check`. A-AC-36 counts, idempotent second run, hand-checked files; A-AC-28 full line coverage;
A-AC-43 five most recent commits touching `activate` match `git log -L`.

Needs the clone at `.actron/clones/test/betterthantomorrow__calva` (cloned from GitHub when missing)."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from actron.config import REPO_ROOT
from actron.connectors.code.clone import clone_or_fetch
from actron.connectors.code.history_tools import history
from actron.connectors.code.model import split_lines
from actron.connectors.code.pipeline import CodeIngestReport, ingest_code
from actron.graph import ids
from actron.graph.ontology import Ontology
from actron.graph.store import GraphStore

pytestmark = pytest.mark.slow

FIXTURE = yaml.safe_load((Path(__file__).parents[1] / "fixtures" / "code" / "calva_expected.yaml").read_text())
PINNED = FIXTURE["sha"]
REPO = FIXTURE["repo"]
CLONE = REPO_ROOT / ".actron" / "clones" / "test" / "betterthantomorrow__calva"
GRAPH = "actron_calva_check"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(CLONE), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(scope="module")
def calva_dir() -> Path:
    if not (CLONE / ".git").exists():
        clone_or_fetch("https://github.com/BetterThanTomorrow/calva.git", CLONE, FIXTURE["branch"], 2000)
    if _git("rev-parse", "HEAD") != PINNED:
        _git("checkout", "-q", "--detach", PINNED)
    return CLONE


@pytest.fixture(scope="module")
def calva_graph(falkordb_url: str, ontology: Ontology) -> Any:
    store = GraphStore(falkordb_url, GRAPH, ontology, workspace_id="calva-check")
    while store.query("MATCH (n) WITH n LIMIT 20000 DETACH DELETE n RETURN count(n) AS c", timeout_ms=60000)[0]["c"]:
        pass
    yield store  # kept after the run so it can be inspected; never dropped
    store.close()


@pytest.fixture(scope="module")
def runs(calva_dir: Path, calva_graph: Any) -> tuple[CodeIngestReport, CodeIngestReport, float]:
    def run() -> CodeIngestReport:
        return asyncio.run(ingest_code("calva-check", REPO, url="https://github.com/BetterThanTomorrow/calva.git",
                                       branch=FIXTURE["branch"], repo_dir=calva_dir, depth=2000, store=calva_graph))

    t0 = time.perf_counter()
    first = run()
    seconds = time.perf_counter() - t0
    second = run()
    return first, second, seconds


def test_counts_and_idempotent_rerun(runs: tuple[CodeIngestReport, CodeIngestReport, float]) -> None:
    """A-AC-36"""
    first, second, seconds = runs
    print(f"\nCalva @ {PINNED[:12]} ingested in {seconds:.1f}s")
    for label, n in first.counts.items():
        print(f"  {label}: {n}")
    print(f"  unresolved calls: {first.unresolved_calls}")
    print(f"  links: { {k: v for k, v in first.links.items() if v} }")
    assert first.head_sha == PINNED
    assert first.counts["CodeFile"] > 1000 and first.counts["CodeFunction"] > 3000
    assert first.counts["GitCommit"] == 2000
    assert first.pagerank_method == "procedure"
    assert second.counts == first.counts
    assert second.links == first.links


def test_hand_checked_files(runs: Any, calva_graph: Any) -> None:
    """A-AC-36"""
    for path, exp in FIXTURE["files"].items():
        rows = calva_graph.query(
            "MATCH (n)-[:FUNCTION_DEFINED_IN|CLASS_DEFINED_IN]->(f:CodeFile {id: $f}) WHERE coalesce(n.deleted, false) = false "
            "RETURN labels(n)[0] AS l, n.qualifiedName AS q, n.startLine AS s, n.endLine AS e, n.kind AS k, "
            "n.isPublic AS p, n.isAsync AS a", {"f": ids.code_file(REPO, path)})
        got_classes = {(r["q"], r["s"], r["e"]) for r in rows if r["l"] == "CodeClass"}
        assert got_classes == {(c["name"], c["start"], c["end"]) for c in exp["classes"]}, path
        got_fns = {r["q"]: r for r in rows if r["l"] == "CodeFunction"}
        assert set(got_fns) == {f["name"] for f in exp["functions"]}, path
        for f in exp["functions"]:
            g = got_fns[f["name"]]
            assert (g["s"], g["e"], g["k"]) == (f["start"], f["end"], f["kind"]), (path, f)
            if "public" in f:
                assert g["p"] is f["public"], (path, f)
            if "async" in f:
                assert g["a"] is f["async"], (path, f)


def test_full_line_coverage(runs: Any, calva_graph: Any, calva_dir: Path) -> None:
    """A-AC-28"""
    covered: dict[str, set[int]] = {}
    skip = 0
    while True:
        rows = calva_graph.query(
            "MATCH (n)-[:FUNCTION_DEFINED_IN|CLASS_DEFINED_IN|CHUNK_OF|SECTION_OF]->(f:CodeFile) "
            "WHERE coalesce(n.deleted, false) = false RETURN f.path AS p, n.startLine AS s, n.endLine AS e "
            "ORDER BY p, s, e SKIP $k LIMIT 5000", {"k": skip}, timeout_ms=60000)
        for r in rows:
            covered.setdefault(r["p"], set()).update(range(r["s"], r["e"] + 1))
        if len(rows) < 5000:
            break
        skip += 5000
    files = calva_graph.query("MATCH (f:CodeFile) WHERE coalesce(f.isSkipped, false) = false AND "
                              "coalesce(f.deleted, false) = false RETURN f.path AS p, f.loc AS loc")
    assert len(files) > 800
    gaps = {}
    for f in files:
        text = (calva_dir / f["p"]).read_bytes().decode("utf-8", "replace") if not (calva_dir / f["p"]).is_symlink() \
            else str((calva_dir / f["p"]).readlink())
        n = len(split_lines(text))
        missing = set(range(1, n + 1)) - covered.get(f["p"], set())
        if missing:
            gaps[f["p"]] = sorted(missing)[:5]
    assert not gaps, gaps


def test_recent_commits_match_git_log_L(runs: Any, calva_graph: Any) -> None:
    """A-AC-43"""
    h = FIXTURE["history_function"]
    fn_id = ids.code_fn(REPO, h["path"], h["qualname"])
    node = calva_graph.get_node(fn_id)
    assert node is not None and (node["startLine"], node["endLine"]) == (h["start"], h["end"])
    rows = history(calva_graph, fn_id, limit=5)
    assert all(r["authorEmail"] and r["authoredAt"] for r in rows)
    live = [line.split()[1] for line in _git("log", "--no-merges", "-L", f"{h['start']},{h['end']}:{h['path']}",
                                               "--format=COMMIT %H", "-s").splitlines() if line.startswith("COMMIT")][:5]
    assert [r["sha"] for r in rows] == live == h["recent_commits"]
