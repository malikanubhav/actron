"""External provider contract fixtures, never evidence of live connectivity."""

from copy import deepcopy
from typing import Any

from actron.contracts import Payload, UnknownOutcome


class SlackFixture:
    def __init__(self) -> None:
        self.messages: list[Payload] = []

    def post(
        self,
        channel: str,
        text: str,
        thread: str | None = None,
        blocks: list[Payload] | None = None,
    ) -> str:
        ts = str(len(self.messages) + 1)
        self.messages.append(
            {"channel": channel, "text": text, "thread": thread, "blocks": blocks, "ts": ts}
        )
        return ts


class LinearFixture:
    def __init__(self) -> None:
        self.issues: dict[str, Payload] = {}
        self.lose_response = False

    def create(self, operation: str, scope: Payload) -> Payload:
        found = self.find(operation)
        if found:
            return found
        issue = {
            "id": f"DEMO-{len(self.issues) + 1}",
            "url": "fixture://linear/issue",
            "operation": operation,
            "scope": deepcopy(scope),
        }
        self.issues[issue["id"]] = issue
        if self.lose_response:
            self.lose_response = False
            raise UnknownOutcome("simulated lost Linear response after write")
        return deepcopy(issue)

    def find(self, operation: str) -> Payload | None:
        return next(
            (deepcopy(i) for i in self.issues.values() if i["operation"] == operation), None
        )

    def read(self, issue: str) -> Payload:
        return deepcopy(self.issues[issue])

    def update(self, issue: str, scope: Payload) -> Payload:
        self.issues[issue]["scope"] = deepcopy(scope)
        return self.read(issue)


class GitHubFixture:
    def __init__(self) -> None:
        self.prs: dict[str, Payload] = {}
        self.lose_create = False
        self.lose_merge = False
        self.race_head: str | None = None

    def create(self, operation: str, run: Payload, scope: Payload) -> Payload:
        found = self.find(operation)
        if found:
            self.prs[found["id"]]["head"] = run["commit"]
            return self.read(found["id"])
        pr = {
            "id": str(len(self.prs) + 1),
            "url": "fixture://github/pull/1",
            "operation": operation,
            "head": run["commit"],
            "state": "open",
            "merged": False,
            "merge_commit": None,
            "checks": [],
            "reviews": [],
            "required_checks": ["suite"],
            "reviews_required": 1,
            "checks_complete": True,
            "reviews_complete": True,
        }
        self.prs[pr["id"]] = pr
        if self.lose_create:
            self.lose_create = False
            raise UnknownOutcome("simulated lost PR response after write")
        return deepcopy(pr)

    def find(self, operation: str) -> Payload | None:
        return next((deepcopy(p) for p in self.prs.values() if p["operation"] == operation), None)

    def read(self, pr: str) -> Payload:
        return deepcopy(self.prs[pr])

    def ready(self, pr: str) -> None:
        head = self.prs[pr]["head"]
        self.prs[pr]["checks"] = [{"name": "suite", "status": "success", "head": head}]
        self.prs[pr]["reviews"] = [{"state": "APPROVED", "head": head, "user": "reviewer"}]

    def merge(self, pr: str, expected_head: str) -> Payload:
        if self.race_head:
            self.prs[pr]["head"] = self.race_head
        if self.prs[pr]["head"] != expected_head:
            from actron.contracts import Rejected

            raise Rejected("GitHub expected-head mismatch")
        self.prs[pr].update(state="closed", merged=True, merge_commit=expected_head)
        if self.lose_merge:
            self.lose_merge = False
            raise UnknownOutcome("simulated lost merge response after write")
        return self.read(pr)


class StimulusCoding:
    """Labeled controlled implementation stimulus; never an autonomous model."""

    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once

    def propose(
        self, checkout: Any, packet: Payload, remaining_tokens: int, timeout: float
    ) -> Payload:
        import difflib

        path = checkout / "app/reports.py"
        original = path.read_text()
        if self.fail_once:
            replacement = original.replace("return can_export(user, project)", "return False")
            self.fail_once = False
        else:
            target = (
                'return can_export(user, project) or (user.get("role") == "admin" '
                'and project in user.get("projects", []) '
                'and project in user.get("admin_projects", []))'
            )
            if "return False" in original:
                replacement = original.replace("return False", target)
            elif target in original:
                replacement = original + "\n# Revision requested in the Slack review thread.\n"
            else:
                replacement = original.replace("return can_export(user, project)", target)
        patch = "diff --git a/app/reports.py b/app/reports.py\n" + "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile="a/app/reports.py",
                tofile="b/app/reports.py",
            )
        )
        if (
            "return False" not in replacement
            and not (checkout / "tests/test_admin_exports.py").exists()
        ):
            feature_tests = """import unittest
from app.reports import export_report
from app.invoices import export_invoice

class AdminExport(unittest.TestCase):
    def test_admin_reports_preserve_membership_and_invoice_boundaries(self):
        admin = {"role": "admin", "projects": ["atlas"], "admin_projects": ["atlas"]}
        self.assertTrue(export_report(admin, "atlas"))
        self.assertFalse(export_report(admin, "orion"))
        self.assertFalse(export_invoice(admin, "atlas"))
        self.assertFalse(export_report({**admin, "projects": []}, "atlas"))
        self.assertFalse(export_report({**admin, "role": "member"}, "atlas"))
"""
            patch += (
                "diff --git a/tests/test_admin_exports.py b/tests/test_admin_exports.py\nnew file mode 100644\n"
                + "".join(
                    difflib.unified_diff(
                        [],
                        feature_tests.splitlines(keepends=True),
                        fromfile="/dev/null",
                        tofile="b/tests/test_admin_exports.py",
                    )
                )
            )
        return {"patch": patch, "tokens": 0, "mechanism": "controlled-test-stimulus"}
