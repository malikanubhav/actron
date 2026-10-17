"""Security and actual execution tests at the disposable worker boundary."""

import shutil
import subprocess
from pathlib import Path

from actron.worker import LocalRunner, RepositoryWorker


class PatchCoding:
    """Controlled test stimulus; this is deliberately not an autonomous coding agent."""

    def __init__(self, patch: str):
        self.patch = patch
        self.calls = 0

    def propose(self, checkout, packet, remaining_tokens, timeout):
        self.calls += 1
        return {"patch": self.patch, "tokens": 10}


def repository(tmp_path):
    repo = tmp_path / "source"
    shutil.copytree(Path(__file__).parents[1] / "demo/repository", repo)
    for args in (
        ["init", "-b", "main"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Baseline",
        ],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return repo, base


def test_worker_executes_real_suite_and_reconciles_completed_run(tmp_path):
    repo, base = repository(tmp_path)
    coder = PatchCoding("""diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,5 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
-    return can_export(user, project)
+    return can_export(user, project) or project in user.get("admin_projects", [])
""")
    worker = RepositoryWorker(str(repo), tmp_path / "runs", coder, LocalRunner(trusted=True))
    result = worker.run(
        "op-1", {"objective": "Project admins can export reports", "checks": []}, {}, base
    )
    assert result["status"] == "succeeded", result
    assert result["commit"] != base
    assert all(c["exit_code"] == 0 for c in result["checks"])
    assert {c["kind"] for c in result["checks"]} == {"baseline", "suite"}
    assert "test_project_admin_cannot_export_invoice" in result["checks"][-1]["output"]
    assert worker.run("op-1", {}, {}, base) == result
    assert coder.calls == 1


def test_worker_refuses_weakening_existing_invoice_regressions(tmp_path):
    repo, base = repository(tmp_path)
    original = (repo / "tests/test_exports.py").read_text()
    replacement = original.replace(
        'self.assertFalse(export_invoice(user, "atlas"))', "self.assertTrue(True)"
    )
    (repo / "tests/test_exports.py").write_text(replacement)
    patch = subprocess.check_output(["git", "-C", str(repo), "diff"], text=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "--", "tests/test_exports.py"], check=True)
    worker = RepositoryWorker(
        str(repo), tmp_path / "runs", PatchCoding(patch), LocalRunner(trusted=True)
    )
    result = worker.run("malicious", {"checks": []}, {}, base)
    assert result["status"] == "failed"
    assert "protected path" in result["output"]
    assert result["commit"] == base


def test_interrupted_worker_is_unknown_and_never_reexecuted(tmp_path):
    import hashlib
    import json

    coder = PatchCoding("unused")
    worker = RepositoryWorker("unused", tmp_path / "runs", coder, LocalRunner(trusted=True))
    directory = tmp_path / "runs" / hashlib.sha256(b"interrupted").hexdigest()
    directory.mkdir()
    (directory / "record.json").write_text(
        json.dumps({"operation": "interrupted", "status": "running"})
    )
    assert worker.find("interrupted")["status"] == "unknown"
    assert worker.run("interrupted", {}, {}, "base")["status"] == "unknown"
    assert coder.calls == 0


def test_worker_retains_actual_failed_commit_then_repairs_inside_scope(tmp_path):
    repo, base = repository(tmp_path)
    bad = """diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,5 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
-    return can_export(user, project)
+    return False
"""
    repair = """diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,5 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
-    return False
+    return can_export(user, project) or project in user.get("admin_projects", [])
"""

    class RepairCoding:
        def __init__(self):
            self.patches = iter([bad, repair])

        def propose(self, checkout, packet, remaining_tokens, timeout):
            return {"patch": next(self.patches), "tokens": 20}

    worker = RepositoryWorker(
        str(repo), tmp_path / "runs", RepairCoding(), LocalRunner(trusted=True)
    )
    result = worker.run("repair", {"checks": []}, {}, base)
    assert result["status"] == "succeeded"
    assert len(result["attempts"]) == 2
    failed = result["attempts"][0]
    assert failed["checks"][0]["exit_code"] != 0
    assert "FAILED" in failed["checks"][0]["output"]
    assert failed["commit"] != result["commit"]
    assert result["tokens"] == 40
    assert (Path(result["path"]).parent / "commands.jsonl").is_file()


def test_review_revision_preserves_branch_and_checks_new_commit(tmp_path):
    repo, base = repository(tmp_path)
    first_patch = """diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,5 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
-    return can_export(user, project)
+    return can_export(user, project) or project in user.get("admin_projects", [])
"""
    first = RepositoryWorker(
        str(repo), tmp_path / "runs", PatchCoding(first_patch), LocalRunner(trusted=True)
    ).run("initial", {"checks": []}, {}, base)
    revision_patch = '''diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,6 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
+    """Exports reports for Finance and administrators of this exact project."""
     return can_export(user, project) or project in user.get("admin_projects", [])
'''
    worker = RepositoryWorker(
        first["path"], tmp_path / "runs", PatchCoding(revision_patch), LocalRunner(trusted=True)
    )
    revised = worker.run(
        "review",
        {"checks": []},
        {"_execution_branch": first["branch"]},
        first["commit"],
        "Document membership",
    )
    assert revised["status"] == "succeeded", revised
    assert revised["branch"] == first["branch"]
    assert revised["commit"] != first["commit"]
    assert revised["checks"][-1]["head"] == revised["commit"]
    assert revised["checks"][0]["head"] == first["commit"]


def test_explicit_new_operation_can_repair_owned_unpushed_failed_commit(tmp_path):
    repo, base = repository(tmp_path)
    bad = """diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,5 +1,5 @@
 from app.permissions import can_export
\x20
\x20
 def export_report(user, project):
-    return can_export(user, project)
+    return False
"""
    repair = bad.replace(
        "-    return can_export(user, project)\n+    return False",
        '-    return False\n+    return can_export(user, project) or project in user.get("admin_projects", [])',
    )
    failed = RepositoryWorker(
        str(repo), tmp_path / "runs", PatchCoding(bad), LocalRunner(trusted=True), max_attempts=1
    ).run("failure", {"checks": []}, {}, base)
    assert failed["status"] == "failed"
    repaired = RepositoryWorker(
        str(repo), tmp_path / "runs", PatchCoding(repair), LocalRunner(trusted=True)
    ).run("authorized-repair", {"checks": []}, {}, failed["commit"])
    assert repaired["status"] == "succeeded", repaired
    assert repaired["commit"] != failed["commit"]
    assert all(check["exit_code"] == 0 for check in repaired["checks"])
    assert repaired["check_history"][0]["kind"] == "predecessor"
    assert repaired["check_history"][0]["exit_code"] != 0


def test_model_http_boundary_uses_provider_usage_and_total_token_ceiling(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from actron.model_cli import ResponsesCoding

    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body))
            response = {"input_tokens": 300}
            if self.path == "/v1/responses":
                response = {
                    "id": "response-contract-fixture",
                    "status": "completed",
                    "usage": {"input_tokens": 300, "output_tokens": 50, "total_tokens": 350},
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"patch": "test fixture patch", "scope_revision": ""}
                                    ),
                                }
                            ],
                        }
                    ],
                }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "app").mkdir()
        (tmp_path / "app/main.py").write_text("def actual_source(): pass")
        (tmp_path / "golden_answers.json").write_text("NEVER SEND EVALUATOR ANSWERS")
        model = ResponsesCoding(
            "fake-contract-key",
            "configured-test-model",
            f"http://127.0.0.1:{server.server_port}/v1",
        )
        result = model.propose(
            tmp_path, {"max_tokens": 1000, "scope": {"objective": "Test provider contract"}}
        )
        assert result["tokens"] == 350
        assert result["patch"] == "test fixture patch"
        assert calls[1][1]["max_output_tokens"] == 444
        assert "actual_source" in calls[1][1]["input"]
        assert "NEVER SEND EVALUATOR" not in calls[1][1]["input"]
        assert calls[1][1]["store"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_github_transport_refreshes_head_checks_reviews_and_sends_expected_sha(monkeypatch):
    import io
    import json
    from urllib.parse import urlparse

    from actron.github import GitHubPRs

    head = "a" * 40
    sent = []

    class Response(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def transport(request, timeout):
        path = urlparse(request.full_url).path
        sent.append((request.method, path, json.loads(request.data) if request.data else None))
        if request.method == "PUT":
            payload = {"merged": True, "sha": "b" * 40}
        elif path.endswith("/pulls/1"):
            payload = {
                "html_url": "https://github.com/example/dedicated/pull/1",
                "head": {"sha": head, "ref": "actron/" + "c" * 24},
                "base": {"ref": "main"},
                "state": "open",
                "merged": False,
                "mergeable": True,
            }
        elif path.endswith("/check-runs"):
            payload = {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "suite",
                        "head_sha": head,
                        "app": {"id": 7},
                        "status": "completed",
                        "conclusion": "failure",
                    },
                    {
                        "id": 2,
                        "name": "suite",
                        "head_sha": head,
                        "app": {"id": 7},
                        "status": "completed",
                        "conclusion": "success",
                    },
                ]
            }
        elif path.endswith("/statuses"):
            payload = [{"id": 3, "context": "lint", "state": "success"}]
        elif path.endswith("/reviews"):
            payload = [
                {"id": 1, "state": "APPROVED", "commit_id": head, "user": {"login": "reviewer"}},
                {"id": 2, "state": "COMMENTED", "commit_id": head, "user": {"login": "reviewer"}},
            ]
        elif path.endswith("/protection"):
            payload = {
                "required_status_checks": {"checks": [{"context": "suite", "app_id": 7}]},
                "required_pull_request_reviews": {"required_approving_review_count": 1},
            }
        elif "/rules/branches/" in path:
            payload = []
        else:
            raise AssertionError(path)
        return Response(json.dumps(payload))

    monkeypatch.setattr("actron.github.urlopen", transport)
    provider = GitHubPRs("example/dedicated", "fake-test-token", "example/dedicated")
    current = provider.read("1")
    assert current["checks_complete"] is True
    assert current["reviews_complete"] is True
    assert len(current["check_history"]) == 3
    assert all(c["status"] == "success" for c in current["checks"])
    merged = provider.merge("1", head)
    assert merged["merged"] is True
    assert sent[-1] == (
        "PUT",
        "/repos/example/dedicated/pulls/1/merge",
        {"sha": head, "merge_method": "merge"},
    )
