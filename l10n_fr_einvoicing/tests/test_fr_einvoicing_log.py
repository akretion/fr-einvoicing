# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import datetime, timedelta

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrEinvoicingLog(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test Company Log",
                "country_id": cls.env.ref("base.fr").id,
            }
        )

    def test_log_preparation_with_info_only_sets_success_status(self):
        result = {
            "log_type": "directory_all",
            "log_origin": "Test Origin",
            "company_id": self.company.id,
            "logs": [],
            "new_count": 5,
            "updated_count": 2,
        }
        self.env["fr.einvoicing.log"]._info_log(result, "This is info message")

        log_vals = self.env["fr.einvoicing.log"]._prepare_log(result)

        self.assertEqual(log_vals["status"], "success")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["warning_count"], 0)
        self.assertIn("INFO", log_vals["logs"])
        self.assertIn("This is info message", log_vals["logs"])

    def test_log_preparation_with_warnings_sets_success_warn_status(self):
        result = {
            "log_type": "flow_import_single",
            "log_origin": "Test Origin",
            "company_id": self.company.id,
            "logs": [],
        }
        self.env["fr.einvoicing.log"]._info_log(result, "Info message")
        self.env["fr.einvoicing.log"]._warning_log(result, "Warning message")

        log_vals = self.env["fr.einvoicing.log"]._prepare_log(result)

        self.assertEqual(log_vals["status"], "success_warn")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["warning_count"], 1)

    def test_log_preparation_with_errors_sets_failure_status(self):
        result = {
            "log_type": "flow_send",
            "log_origin": "Test Origin",
            "company_id": self.company.id,
            "logs": [],
        }
        self.env["fr.einvoicing.log"]._info_log(result, "Info message")
        self.env["fr.einvoicing.log"]._warning_log(result, "Warning message")
        self.env["fr.einvoicing.log"]._error_log(result, "Error message")

        log_vals = self.env["fr.einvoicing.log"]._prepare_log(result)

        self.assertEqual(log_vals["status"], "failure")
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["warning_count"], 1)

    def test_create_log_persists_log_record(self):
        result = {
            "log_type": "flow_process",
            "log_origin": "Test Origin",
            "company_id": self.company.id,
            "logs": [("info", "Process message")],
        }
        initial_count = self.env["fr.einvoicing.log"].search_count([])

        self.env["fr.einvoicing.log"]._create_log(result)

        new_count = self.env["fr.einvoicing.log"].search_count([])
        self.assertEqual(new_count, initial_count + 1)
        created_log = self.env["fr.einvoicing.log"].search([], limit=1)
        self.assertEqual(created_log.type, "flow_process")
        self.assertEqual(created_log.company_id, self.company)

    def test_gc_old_logs_removes_logs_older_than_configured_days(self):
        result_new = {
            "log_type": "flow_download",
            "company_id": self.company.id,
            "logs": [("info", "New Log")],
        }
        result_old = {
            "log_type": "flow_download",
            "company_id": self.company.id,
            "logs": [("info", "Old Log")],
        }
        self.env["fr.einvoicing.log"]._create_log(result_new)
        self.env["fr.einvoicing.log"]._create_log(result_old)

        logs = self.env["fr.einvoicing.log"].search([], order="id desc", limit=2)
        log_new = logs[0]
        log_old = logs[1]

        old_date = datetime.now() - timedelta(days=601)
        self.env.cr.execute(
            "UPDATE fr_einvoicing_log SET create_date = %s WHERE id = %s",
            (old_date, log_old.id),
        )
        self.env.invalidate_all()

        self.env["fr.einvoicing.log"]._gc_old_logs()

        self.assertTrue(log_new.exists())
        self.assertFalse(log_old.exists())

    def test_gc_old_logs_uses_default_days_if_config_is_invalid(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "fr_einvoicing.log_days", "invalid_integer"
        )
        result_old = {
            "log_type": "flow_download",
            "company_id": self.company.id,
            "logs": [("info", "Old Log")],
        }
        self.env["fr.einvoicing.log"]._create_log(result_old)
        log_old = self.env["fr.einvoicing.log"].search([], limit=1)

        old_date = datetime.now() - timedelta(days=601)
        self.env.cr.execute(
            "UPDATE fr_einvoicing_log SET create_date = %s WHERE id = %s",
            (old_date, log_old.id),
        )
        self.env.invalidate_all()

        self.env["fr.einvoicing.log"]._gc_old_logs()

        self.assertFalse(log_old.exists())
