"""The load test script runs and reports throughput and p95 latency (spec B, B14)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from actron.config import REPO_ROOT

SCRIPT = Path(REPO_ROOT) / "scripts" / "load_test.py"


@pytest.mark.slow
def test_load_test_reports_throughput_and_p95(small_graph: Any, tmp_path: Path) -> None:
    """B-AC-68: concurrent readers (shared query, callers, impact) and writers (500-row batches) run without
    errors, and the report has per-operation throughput and p95 latency."""
    out = tmp_path / "load.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--ws", "loadtest-fixture", "--graph", small_graph.graph_name,
         "--seconds", "4", "--readers", "2", "--writers", "1", "--json", str(out)],
        check=True, capture_output=True, text=True, timeout=180, cwd=str(Path(REPO_ROOT) / "backend"),
    )
    report = json.loads(out.read_text())
    assert report["rowsWritten"] > 0 and report["rowsPerSecond"] > 0
    for op in ("shared_query", "callers", "impact", "upsert_500"):
        stats = report["operations"][op]
        assert stats["count"] > 0, op
        assert stats["errors"] == 0, op
        assert stats["p95Ms"] >= stats["p50Ms"] > 0


def test_percentile_picks_the_right_rank() -> None:
    """B-AC-68: p95 of 1..100 is 95 (nearest rank)."""
    spec = importlib.util.spec_from_file_location("actron_load_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.percentile([float(i) for i in range(1, 101)], 95) == 95.0
    assert module.percentile([], 95) == 0.0
