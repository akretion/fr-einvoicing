# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestAccountMove(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.company.write(
            {
                "name": "Test Company Main",
                "country_id": cls.env.ref("base.fr").id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": "client_id",
                "fr_ctc_client_secret": "client_secret",
                "fr_ctc_directory_sync_on_invoice_post": "no",
            }
        )
        cls.company.partner_id.write(
            {
                "siren": "120027016",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": fields.Date.today(),
            }
        )
        cls.company_dir_line = cls.env["fr.directory.line"].create(
            {
                "partner_id": cls.company.partner_id.id,
                "identifier": "120027016",
                "type": "siren",
                "state": "active",
            }
        )

        cls.customer = cls.env["res.partner"].create(
            {
                "name": "French Customer Partner",
                "siren": "552081317",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": fields.Date.today(),
            }
        )
        cls.customer_dir_line = cls.env["fr.directory.line"].create(
            {
                "partner_id": cls.customer.id,
                "identifier": "552081317",
                "type": "siren",
                "state": "active",
            }
        )

    def _create_invoice(self):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.customer.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Line 1",
                            "quantity": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )

    def test_invoice_computes_directory_lines(self):
        invoice = self._create_invoice()
        self.assertEqual(invoice.fr_directory_line_id, self.customer_dir_line)
        self.assertEqual(invoice.company_fr_directory_line_id, self.company_dir_line)
        self.assertTrue(invoice.fr_einvoicing_required)

    def test_invoice_post_raises_if_company_dir_line_inactive(self):
        invoice = self._create_invoice()
        self.company_dir_line.state = "inactive"
        with self.assertRaisesRegex(
            UserError, "the selected company directory line .* is not active"
        ):
            invoice.action_post()
        self.company_dir_line.state = "active"

    def test_invoice_post_raises_if_customer_dir_line_inactive(self):
        invoice = self._create_invoice()
        self.customer_dir_line.state = "inactive"
        with self.assertRaisesRegex(UserError, "is not active"):
            invoice.action_post()
        self.customer_dir_line.state = "active"

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_invoice_post_creates_flow_successfully(self, mock_sync_logs):
        invoice = self._create_invoice()
        invoice.action_post()
        self.assertTrue(invoice.fr_einvoicing_flow_id)
        self.assertEqual(invoice.fr_einvoicing_flow_id.move_id, invoice)

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_fr_directory_sync_action_server_with_move_context(self, mock_sync):
        invoice = self._create_invoice()
        ctx = {"fr_directory_sync_move_id": invoice.id}
        action = invoice.with_context(**ctx)._fr_directory_sync_action_server()
        self.assertEqual(action["res_id"], invoice.id)

    def test_fr_directory_sync_action_server_without_move_context(self):
        invoice = self._create_invoice()
        action = invoice._fr_directory_sync_action_server()
        self.assertEqual(action, {})

    @patch("odoo.addons.l10n_fr_einvoicing.models.account_move.get_flow")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_fr_ctc_get_readable_invoice_button_success(
        self, mock_session, mock_get_flow
    ):
        mock_get_flow.return_value = b"PDF_CONTENT"
        purchase_invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.customer.id,
                "ref": "BILL_999",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Line 1",
                            "quantity": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )
        flow = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "in",
                    "identifier": "FLOW_BILL",
                    "syntax": "UBL",
                    "move_ids": [(6, 0, [purchase_invoice.id])],
                }
            )
        )
        purchase_invoice.sudo().fr_einvoicing_flow_id = flow.id
        purchase_invoice._compute_fr_einvoicing_show_readable_invoice_button()
        self.assertTrue(purchase_invoice.fr_einvoicing_show_readable_invoice_button)

        action = purchase_invoice.fr_ctc_get_readable_invoice_button()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertFalse(purchase_invoice.fr_einvoicing_show_readable_invoice_button)

        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", purchase_invoice.id),
                ("name", "=", "readable_BILL_999.pdf"),
            ]
        )
        self.assertTrue(attachment.exists())
        self.assertEqual(attachment.raw, b"PDF_CONTENT")

    @patch("odoo.addons.l10n_fr_einvoicing.models.account_move.get_flow")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_fr_ctc_get_readable_invoice_button_failure(
        self, mock_session, mock_get_flow
    ):
        mock_get_flow.side_effect = Exception("API connection timeout")
        purchase_invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.customer.id,
                "ref": "BILL_ERR",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Line 1",
                            "quantity": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )
        flow = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "in",
                    "identifier": "FLOW_ERR",
                    "syntax": "UBL",
                    "move_ids": [(6, 0, [purchase_invoice.id])],
                }
            )
        )
        purchase_invoice.sudo().fr_einvoicing_flow_id = flow.id

        with self.assertRaisesRegex(
            UserError, "Failed to get the readable version of vendor bill"
        ):
            purchase_invoice.fr_ctc_get_readable_invoice_button()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_invoice_post_with_missing_partner_directory_entity_type_triggers_sync_success(  # noqa: E501
        self, mock_sync_logs
    ):
        self.customer.write(
            {
                "fr_directory_entity_type": False,
                "fr_directory_last_sync_date": False,
            }
        )
        self.company.write(
            {
                "fr_ctc_directory_sync_on_invoice_post": "not_blocking",
            }
        )

        # Mock successful sync setting private status
        def side_effect(company, origin):
            self.customer.write(
                {
                    "fr_directory_entity_type": "private",
                    "fr_directory_last_sync_date": fields.Date.today(),
                }
            )

        mock_sync_logs.side_effect = side_effect

        invoice = self._create_invoice()
        invoice.action_post()
        self.assertEqual(self.customer.fr_directory_entity_type, "private")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_invoice_post_with_missing_partner_directory_entity_type_triggers_sync_failure(  # noqa: E501
        self, mock_sync_logs
    ):
        self.customer.write(
            {
                "fr_directory_entity_type": False,
                "fr_directory_last_sync_date": False,
            }
        )
        self.company.write(
            {
                "fr_ctc_directory_sync_on_invoice_post": "not_blocking",
            }
        )
        mock_sync_logs.side_effect = Exception("Directory Down")

        invoice = self._create_invoice()
        invoice.action_post()
        # Post should succeed even if sync fails because it is "not_blocking"
        self.assertEqual(invoice.state, "posted")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_invoice_post_with_old_sync_date_triggers_sync_success(
        self, mock_sync_logs
    ):
        self.customer.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": fields.Date.today() - timedelta(days=10),
            }
        )
        self.company.write(
            {
                "fr_ctc_directory_sync_on_invoice_post": "not_blocking",
            }
        )

        invoice = self._create_invoice()
        invoice.action_post()
        mock_sync_logs.assert_called_once()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.ResPartner._fr_directory_sync_logs"
    )
    def test_invoice_post_with_old_sync_date_triggers_sync_blocking_failure(
        self, mock_sync_logs
    ):
        self.customer.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": fields.Date.today() - timedelta(days=10),
            }
        )
        self.company.write(
            {
                "fr_ctc_directory_sync_on_invoice_post": "blocking",
            }
        )
        mock_sync_logs.side_effect = Exception("Directory Down")

        invoice = self._create_invoice()
        with self.assertRaisesRegex(
            UserError, "Failed to query the directory for partner"
        ):
            invoice.action_post()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany.fr_ctc_run_import_log"
    )
    def test_journal_run_import_button(self, mock_run_import_log):
        journal = self.env["account.journal"].create(
            {
                "name": "Customer Invoice Journal Test",
                "code": "TESTJ",
                "type": "sale",
                "company_id": self.company.id,
            }
        )
        mock_run_import_log.return_value = (
            None,
            {"new_count": 0, "warning_count": 0, "error_count": 0},
        )
        action = journal.fr_einvoicing_run_import_button()
        self.assertEqual(action["type"], "ir.actions.client")
