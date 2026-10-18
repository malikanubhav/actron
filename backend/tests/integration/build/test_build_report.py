"""Build.report in the request view's shape (frontend/lib/build-report.ts): tests, constraints, filesChanged,
procedures. B-AC-76 (report for the Build tab), C-AC-26 (PR tab shows tests and constraints)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from actron.flow import test_runner as tr
from actron.flow.build import BuildInput, BuildResult, build_ui_report
from actron.flow.diff_check import parse_numstat
from tests.fakes.support import pg_ws  # noqa: F401

TICKET: dict[str, Any] = {
    "objective": "Add subtract.", "constraintsToPreserve": [{"text": "add keeps its signature", "evidenceIds": []},
                                                            {"text": "total stays linear"}],
    "targetBranch": "main",
}
PI_REPORT: dict[str, Any] = {
    "filesChanged": ["calc/ops.py", "tests/test_ops.py"], "testsAdded": ["tests/test_ops.py::test_subtract"],
    "testCommand": "pytest -q", "testsPassed": True,
    "constraintsPreserved": [{"constraint": "add keeps its signature.", "how": "test_add still passes"},
                             {"constraint": "Exports stay private", "how": "decision quoted in the PR"}],
    "stopped": False, "notes": "Added subtract next to add.",
}


def _inp(**over: Any) -> BuildInput:
    data: dict[str, Any] = dict(ws="w", request_id="req_1", build_id="b1", revision_hash="a" * 64, ticket=TICKET,
                                procedures=[{"id": "actron:procedure:py", "title": "Python tests",
                                             "testCommand": "pytest -q"}, {"id": "actron:procedure:x"}])
    data.update(over)
    return BuildInput(**data)


def test_numstat_lines_become_counts() -> None:
    text = "12\t3\tcalc/ops.py\n-\t-\tlogo.png\n0\t7\tREADME.md\n\nbroken line\n"
    assert parse_numstat(text) == {"calc/ops.py": [12, 3], "logo.png": [0, 0], "README.md": [0, 7]}


def test_b_ac_76_passed_build_report_has_every_section_in_the_ui_shape() -> None:
    """B-AC-76: tests, constraints (with proof), filesChanged with line counts, procedures; Pi's report kept."""
    result = BuildResult(status="passed", files_changed=["calc/ops.py", "tests/test_ops.py"])
    tests = tr.TestResult(passed=3, failed=0)
    report = build_ui_report(_inp(), result, PI_REPORT, tests, {"calc/ops.py": [4, 0], "tests/test_ops.py": [3, 1]})
    assert report["tests"] == [{"name": "tests/test_ops.py::test_subtract", "status": "pass"}]
    assert report["constraints"] == [
        {"text": "add keeps its signature", "status": "holds", "proof": {"kind": "test", "label": "test_add still passes"}},
        {"text": "total stays linear", "status": "unverified", "proof": None},
        {"text": "Exports stay private", "status": "holds",
         "proof": {"kind": "evidence", "label": "decision quoted in the PR"}},
    ]
    assert report["filesChanged"] == [{"path": "calc/ops.py", "additions": 4, "deletions": 0},
                                      {"path": "tests/test_ops.py", "additions": 3, "deletions": 1}]
    assert report["procedures"] == [{"title": "Python tests", "testCommand": "pytest -q"},
                                    {"title": "actron:procedure:x", "testCommand": ""}]
    assert report["testsAdded"] == PI_REPORT["testsAdded"] and report["notes"] == PI_REPORT["notes"]
    assert report["pi"] == PI_REPORT
    json.dumps(report)  # stored as JSONB


def test_failed_build_lists_failing_tests_and_marks_their_constraints_broken() -> None:
    result = BuildResult(status="failed", files_changed=["calc/ops.py"])
    tests = tr.TestResult(passed=1, failed=1, exit_code=1,
                          failing=[tr.FailingTest(name="test_add", output="assert 5 == -1")])
    pi = dict(PI_REPORT, constraintsPreserved=[{"constraint": "add keeps its signature", "how": "test_add passes"}])
    report = build_ui_report(_inp(), result, pi, tests, {})
    assert report["tests"][0] == {"name": "test_add", "status": "fail", "output": "assert 5 == -1"}
    assert report["tests"][1] == {"name": "tests/test_ops.py::test_subtract", "status": "pass"}
    assert report["constraints"][0]["status"] == "broken"
    assert report["constraints"][1]["status"] == "unverified"
    assert report["filesChanged"] == [{"path": "calc/ops.py", "additions": 0, "deletions": 0}]


def test_stopped_build_without_pi_report_still_has_the_shape() -> None:
    report = build_ui_report(_inp(procedures=[]), BuildResult(status="stopped"), None, None, {})
    assert report == {"tests": [], "constraints": [
        {"text": "add keeps its signature", "status": "unverified", "proof": None},
        {"text": "total stays linear", "status": "unverified", "proof": None}],
        "filesChanged": [], "procedures": [], "testsAdded": [], "notes": "", "pi": None}


async def test_record_build_result_keeps_the_ui_report(pg_ws: str) -> None:  # noqa: F811
    """record_build_result stores Build.report as sent (it used to replace filesChanged with plain paths)."""
    from datetime import UTC, datetime

    from actron.activities.request import record_build_result
    from actron.db import models as m
    from actron.db.session import session_scope

    rid, bid = f"req_{uuid.uuid4().hex[:10]}", f"b{uuid.uuid4().hex[:10]}"
    with session_scope() as s:
        s.add(m.Request(id=rid, workspace_id=pg_ws, kind="feature", title="t", text="t", state="Building",
                        temporal_workflow_id=f"request:{rid}", data={}))
        s.flush()
        s.add(m.BuildRun(id=bid, request_id=rid, status="running", branch="actron/x", started_at=datetime.now(UTC)))
    report = build_ui_report(_inp(), BuildResult(status="passed", files_changed=["calc/ops.py"]), PI_REPORT,
                             tr.TestResult(passed=3), {"calc/ops.py": [4, 0]})
    await record_build_result({"requestId": rid, "buildId": bid, "branch": "actron/x", "result": {
        "status": "passed", "headSha": "c" * 40, "filesChanged": ["calc/ops.py"], "testsPassed": 3,
        "report": report}})
    legacy_bid = f"b{uuid.uuid4().hex[:10]}"
    await record_build_result({"requestId": rid, "buildId": legacy_bid, "branch": "actron/y", "result": {
        "status": "failed", "filesChanged": ["a.py"], "report": {"filesChanged": ["a.py"]}}})
    with session_scope() as s:
        row = s.get(m.BuildRun, bid)
        legacy = s.get(m.BuildRun, legacy_bid)
        assert row is not None and legacy is not None
        assert row.report == report
        assert legacy.report == {"filesChanged": [{"path": "a.py", "additions": 0, "deletions": 0}],
                                 "tests": [], "constraints": [], "procedures": []}
