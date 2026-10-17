import unittest

from app.invoices import export_invoice
from app.reports import export_report


class ExportPolicy(unittest.TestCase):
    def test_finance_can_export_reports_and_invoices_in_own_project(self):
        user = {"role": "finance", "projects": ["atlas"]}
        self.assertTrue(export_report(user, "atlas"))
        self.assertTrue(export_invoice(user, "atlas"))

    def test_project_admin_cannot_export_invoice(self):
        user = {"role": "admin", "projects": ["atlas"], "admin_projects": ["atlas"]}
        self.assertFalse(export_invoice(user, "atlas"))

    def test_finance_cannot_cross_project_boundary(self):
        user = {"role": "finance", "projects": ["atlas"]}
        self.assertFalse(export_invoice(user, "orion"))
        self.assertFalse(export_report(user, "orion"))

    def test_regular_member_cannot_export(self):
        user = {"role": "member", "projects": ["atlas"]}
        self.assertFalse(export_report(user, "atlas"))
        self.assertFalse(export_invoice(user, "atlas"))
