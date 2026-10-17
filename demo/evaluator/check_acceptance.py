"""Evaluator-only acceptance checks. Never copy into the model's input repository."""
import sys

sys.path.insert(0, sys.argv[1])
from app.reports import export_report  # noqa: E402
from app.invoices import export_invoice  # noqa: E402

cases = [
    ("admin report", export_report, {"role": "admin", "projects": ["atlas"], "admin_projects": ["atlas"]}, "atlas", True),
    ("admin invoice denied", export_invoice, {"role": "admin", "projects": ["atlas"], "admin_projects": ["atlas"]}, "atlas", False),
    ("admin membership required", export_report, {"role": "admin", "projects": [], "admin_projects": ["atlas"]}, "atlas", False),
    ("admin other project denied", export_report, {"role": "admin", "projects": ["atlas", "orion"], "admin_projects": ["atlas"]}, "orion", False),
    ("finance report", export_report, {"role": "finance", "projects": ["atlas"]}, "atlas", True),
    ("finance invoice", export_invoice, {"role": "finance", "projects": ["atlas"]}, "atlas", True),
    ("member denied", export_report, {"role": "member", "projects": ["atlas"]}, "atlas", False),
]
failures = []
for name, operation, user, project, expected in cases:
    actual = bool(operation(user, project))
    print(f"{name}: {'PASS' if actual == expected else 'FAIL'} (expected={expected}, actual={actual})")
    if actual != expected:
        failures.append(name)
sys.exit(bool(failures))
