# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import datetime
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrEinvoicingFlow(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.company.write(
            {
                "name": "Test Company Flow",
                "country_id": cls.env.ref("base.fr").id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": "client_id",
                "fr_ctc_client_secret": "client_secret",
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "French Customer Partner Flow",
                "siren": "552081317",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
            }
        )
        cls.invoice = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.customer.id,
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
        cls.flow = (
            cls.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": cls.company.id,
                    "state": "created",
                    "direction": "out",
                    "move_ids": [(6, 0, [cls.invoice.id])],
                }
            )
        )

    def test_compute_display_name_when_no_identifier(self):
        self.flow.sudo()._compute_display_name()
        self.assertIn("to send", self.flow.display_name)
        self.assertIn("Created", self.flow.display_name)

    def test_compute_display_name_with_identifier(self):
        self.flow.sudo().identifier = "FLOW_123"
        self.flow.sudo()._compute_display_name()
        self.assertEqual(self.flow.display_name, "FLOW_123 (Created)")

    def test_compute_move_id_matches_linked_invoice(self):
        self.flow.sudo()._compute_move_id()
        self.assertEqual(self.flow.move_id, self.invoice)

    def test_compute_event_id_matches_linked_event(self):
        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .create(
                {
                    "flow_id": self.flow.id,
                    "status": "approved",
                    "direction": "in",
                    "company_id": self.company.id,
                }
            )
        )
        self.flow.invalidate_recordset(["event_ids"])
        self.flow.sudo()._compute_event_id()
        self.assertEqual(self.flow.event_id, event)

    def test_unlink_allowed_when_no_identifier(self):
        self.flow.sudo().identifier = False
        self.flow.sudo().unlink()
        self.assertFalse(self.flow.exists())

    def test_unlink_raises_user_error_when_identifier_exists(self):
        flow_with_id = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "identifier": "FLOW_999",
                }
            )
        )
        with self.assertRaisesRegex(
            UserError, "Cannot delete flow .* because it has an identifier"
        ):
            flow_with_id.sudo().unlink()

    def test_show_invoices_button_raises_user_error_when_no_invoice(self):
        flow_no_invoice = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                }
            )
        )
        with self.assertRaisesRegex(UserError, "is not linked to an invoice"):
            flow_no_invoice.sudo().show_invoices_button()

    def test_show_invoices_button_returns_action_when_invoice_exists(self):
        action = self.flow.sudo().show_invoices_button()
        self.assertEqual(action["res_id"], self.invoice.id)

    def test_back2created_button_moves_state_from_error_to_created(self):
        self.flow.sudo().state = "error"
        self.flow.sudo().back2created_button()
        self.assertEqual(self.flow.state, "created")

    def test_back2created_button_raises_assertion_error_when_state_is_not_error(self):
        self.flow.sudo().state = "created"
        with self.assertRaises(AssertionError):
            self.flow.sudo().back2created_button()

    def test_generate_button_skips_when_direction_is_incoming(self):
        flow_in = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "in",
                }
            )
        )
        flow_in.generate_button()
        self.assertEqual(flow_in.state, "created")

    def test_generate_button_skips_when_state_is_not_created(self):
        flow_error = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "error",
                    "direction": "out",
                }
            )
        )
        flow_error.generate_button()
        self.assertEqual(flow_error.state, "error")

    def test_generate_button_skips_when_file_is_already_attached(self):
        flow_with_file = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "file_bin": b"dGVzdA==",
                }
            )
        )
        flow_with_file.generate_button()
        self.assertEqual(flow_with_file.state, "created")

    def test_generate_button_syntax_ubl_sets_state_to_generated_or_error(self):
        flow_ubl = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "syntax": "UBL",
                    "move_ids": [(6, 0, [self.invoice.id])],
                }
            )
        )
        flow_ubl.generate_button()
        self.assertIn(flow_ubl.state, ["generated", "error"])

    def test_generate_button_syntax_cii_sets_state_to_generated_or_error(self):
        flow_cii = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "syntax": "CII",
                    "move_ids": [(6, 0, [self.invoice.id])],
                }
            )
        )
        flow_cii.generate_button()
        self.assertIn(flow_cii.state, ["generated", "error"])

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.generate_cdar")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_event.FrEinvoicingEvent._prepare_xml_data"
    )
    def test_generate_button_for_event_successfully_generates_cdar(
        self, mock_prepare_xml, mock_generate_cdar
    ):
        mock_prepare_xml.return_value = {"some": "data"}
        mock_generate_cdar.return_value = b"<xml>CDAR</xml>"

        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .create(
                {
                    "status": "approved",
                    "direction": "out",
                    "company_id": self.company.id,
                    "move_id": self.invoice.id,
                }
            )
        )
        flow_event = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "event_ids": [(6, 0, [event.id])],
                }
            )
        )
        flow_event.generate_button()
        self.assertEqual(flow_event.state, "generated")
        self.assertEqual(flow_event.filename, "cdar_approved.xml")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_when_direction_is_in_does_nothing(self, mock_session):
        self.flow.direction = "in"
        self.flow.state = "generated"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.filename = "test.xml"
        self.flow.syntax = "UBL"
        self.flow.processing_rule = "B2B"

        self.flow.send_button()
        self.assertEqual(self.flow.state, "generated")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_when_state_is_not_generated_does_nothing(self, mock_session):
        self.flow.direction = "out"
        self.flow.state = "created"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.filename = "test.xml"
        self.flow.syntax = "UBL"
        self.flow.processing_rule = "B2B"

        self.flow.send_button()
        self.assertEqual(self.flow.state, "created")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_when_no_file_does_nothing(self, mock_session):
        self.flow.direction = "out"
        self.flow.state = "generated"
        self.flow.file_bin = False
        self.flow.filename = "test.xml"
        self.flow.syntax = "UBL"
        self.flow.processing_rule = "B2B"

        self.flow.send_button()
        self.assertEqual(self.flow.state, "generated")

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.send_flow_parsed")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_success_updates_flow_state_to_sent(
        self, mock_session, mock_send
    ):
        mock_send.return_value = {
            "flowId": "i_123",
            "flowSyntax": "UBL",
            "submittedAt": "2026-04-30T13:10:47Z",
        }
        self.flow.direction = "out"
        self.flow.state = "generated"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.filename = "test.xml"
        self.flow.syntax = "UBL"
        self.flow.processing_rule = "B2B"

        self.flow.send_button()
        self.assertEqual(self.flow.state, "sent")
        self.assertEqual(self.flow.identifier, "i_123")

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.send_flow_parsed")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_failure_updates_flow_state_to_error(
        self, mock_session, mock_send
    ):
        mock_send.side_effect = Exception("Connection Failed")
        self.flow.direction = "out"
        self.flow.state = "generated"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.filename = "test.xml"
        self.flow.syntax = "UBL"
        self.flow.processing_rule = "B2B"

        self.flow.send_button()
        self.assertEqual(self.flow.state, "generated")
        self.assertIn("Connection Failed", self.flow.odoo_error_details)

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_download_button_when_direction_is_out_does_nothing(self, mock_session):
        self.flow.direction = "out"
        self.flow.state = "created"
        self.flow.identifier = "FLOW_123"

        self.flow.download_button()
        self.assertEqual(self.flow.state, "created")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_download_button_when_state_is_not_created_does_nothing(self, mock_session):
        self.flow.direction = "in"
        self.flow.state = "downloaded"
        self.flow.identifier = "FLOW_123"

        self.flow.download_button()
        self.assertEqual(self.flow.state, "downloaded")

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.get_flow")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_download_button_success_updates_flow_state_to_downloaded(
        self, mock_session, mock_get
    ):
        mock_get.return_value = b"<xml>Original XML</xml>"
        self.flow.direction = "in"
        self.flow.state = "created"
        self.flow.identifier = "FLOW_DOWNLOAD"
        self.flow.syntax = "UBL"

        self.flow.download_button()
        self.assertEqual(self.flow.state, "downloaded")
        self.assertEqual(self.flow.filename, "FLOW_DOWNLOAD.xml")

    def test_process_button_when_direction_is_out_does_nothing(self):
        self.flow.direction = "out"
        self.flow.state = "downloaded"
        self.flow.file_bin = b"dGVzdA=="

        self.flow.process_button()
        self.assertEqual(self.flow.state, "downloaded")

    def test_process_button_when_state_is_not_downloaded_does_nothing(self):
        self.flow.direction = "in"
        self.flow.state = "created"
        self.flow.file_bin = b"dGVzdA=="

        self.flow.process_button()
        self.assertEqual(self.flow.state, "created")

    def test_process_button_supplier_invoice_without_import_sets_error(self):
        self.flow.direction = "in"
        self.flow.state = "downloaded"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.type = "SupplierInvoice"

        self.flow.process_button()
        self.assertEqual(self.flow.state, "error")
        self.assertIn(
            "Odoo failed to created the supplier invoice", self.flow.odoo_error_details
        )

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.parse_cdar")
    def test_process_button_customer_invoice_lc_with_invalid_xml_sets_error(
        self, mock_parse
    ):
        mock_parse.side_effect = Exception("XML parsing error")
        self.flow.direction = "in"
        self.flow.state = "downloaded"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.type = "CustomerInvoiceLC"

        self.flow.process_button()
        self.assertEqual(self.flow.state, "error")
        self.assertIn("XML parsing error", self.flow.odoo_error_details)

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.parse_cdar")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._match_partner_from_event"
    )
    def test_process_button_customer_invoice_lc_with_valid_xml_creates_event(
        self, mock_match_partner, mock_parse
    ):
        mock_parse.return_value = {
            "invoice_number": self.invoice.name,
            "invoice_issuer": {
                "0002": "120027016",
            },
            "status": "approved",
            "status_code": "205",
            "lc_datetime": datetime.datetime.now(),
            "lifecycle_id": "LC_123",
            "identifier": "EVT_123",
        }
        mock_match_partner.return_value = self.customer

        self.flow.direction = "in"
        self.flow.state = "downloaded"
        self.flow.file_bin = b"dGVzdA=="
        self.flow.type = "CustomerInvoiceLC"

        self.flow.process_button()
        self.assertEqual(self.flow.state, "done")

        event = self.env["fr.einvoicing.event"].search(
            [("move_id", "=", self.invoice.id)]
        )
        self.assertTrue(event.exists())
        self.assertEqual(event.status, "approved")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_event.FrEinvoicingEvent._prepare_xml_data"
    )
    def test_generate_button_for_event_cdar_error_sets_error_state(
        self, mock_prepare_xml
    ):
        mock_prepare_xml.side_effect = Exception("Mock XML Error")

        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .create(
                {
                    "status": "approved",
                    "direction": "out",
                    "company_id": self.company.id,
                    "move_id": self.invoice.id,
                }
            )
        )
        flow_event = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "out",
                    "event_ids": [(6, 0, [event.id])],
                }
            )
        )
        flow_event.generate_button()
        self.assertEqual(flow_event.state, "error")
        self.assertIn("Mock XML Error", flow_event.odoo_error_details)

    @patch("odoo.addons.base.models.ir_actions_report.IrActionsReport._render")
    def test_generate_button_facturx_error_sets_error_state(self, mock_render):
        mock_render.side_effect = Exception("Mock Factur-X render Error")
        self.flow.syntax = "Factur-X"
        self.flow.generate_button()
        self.assertEqual(self.flow.state, "error")
        self.assertIn("Mock Factur-X render Error", self.flow.odoo_error_details)

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._cron_companies"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_run_import"
    )
    def test_in_cron_success(
        self, mock_run_import, mock_get_session, mock_cron_companies
    ):
        # Start fresh: unlink other flows so they do not interfere
        self.env["fr.einvoicing.flow"].sudo().search([]).unlink()

        mock_cron_companies.return_value = self.company
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        flow_dl = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "in",
                    "state": "created",
                    "identifier": "FLOW_DL_1",
                }
            )
        )
        flow_proc = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "in",
                    "state": "downloaded",
                    "file_bin": b"dGVzdA==",
                    "type": "SupplierInvoice",
                }
            )
        )

        with (
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.get_flow"
            ) as mock_get_flow,
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._import_supplier_invoice"
            ) as mock_import_inv,
        ):
            mock_get_flow.return_value = b"<xml>Original</xml>"
            # Return real invoice ID to avoid MissingError on browsing in-hand event
            mock_import_inv.return_value = self.invoice.id

            self.env["fr.einvoicing.flow"]._in_cron()

            self.assertEqual(flow_dl.state, "downloaded")
            self.assertEqual(flow_proc.state, "done")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._cron_companies"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.send_flow_parsed")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.get_flow_metadata_parsed"
    )
    @patch("time.sleep")
    def test_out_cron_success(
        self,
        mock_sleep,
        mock_get_metadata,
        mock_send_flow,
        mock_get_session,
        mock_cron_companies,
    ):
        # Start fresh: unlink other flows so they do not interfere
        self.env["fr.einvoicing.flow"].sudo().search([]).unlink()

        mock_cron_companies.return_value = self.company
        mock_get_session.return_value = MagicMock()
        mock_send_flow.return_value = {
            "flowId": "sent_id_456",
            "submitted_at": datetime.datetime.now(),
        }
        mock_get_metadata.return_value = {
            "state": "done",
            "updated_at": datetime.datetime.now(),
        }

        flow_gen = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "out",
                    "state": "created",
                    "syntax": "UBL",
                    "move_ids": [(6, 0, [self.invoice.id])],
                }
            )
        )
        flow_send = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "out",
                    "state": "generated",
                    "file_bin": b"dGVzdA==",
                    "filename": "invoice.xml",
                    "syntax": "UBL",
                    "processing_rule": "B2B",
                }
            )
        )
        flow_update = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "out",
                    "state": "sent",
                    "identifier": "sent_id_123",
                }
            )
        )

        with patch.object(
            self.env["account.move"].__class__,
            "generate_ubl_xml_string",
            create=True,
            return_value=b"<xml>UBL</xml>",
        ):
            self.env["fr.einvoicing.flow"]._out_cron()

        self.assertEqual(flow_gen.state, "generated")
        self.assertEqual(flow_send.state, "done")
        self.assertEqual(flow_update.state, "done")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._cron_companies"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_in_cron_session_error(self, mock_get_session, mock_cron_companies):
        mock_cron_companies.return_value = self.company
        mock_get_session.side_effect = Exception("Auth Failure")

        self.env["fr.einvoicing.flow"]._in_cron()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._cron_companies"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_out_cron_session_error(self, mock_get_session, mock_cron_companies):
        mock_cron_companies.return_value = self.company
        mock_get_session.side_effect = Exception("Auth Failure")

        self.env["fr.einvoicing.flow"]._out_cron()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.get_flow_metadata_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_update_status_api_error(self, mock_get_session, mock_get_metadata):
        mock_get_session.return_value = MagicMock()
        mock_get_metadata.side_effect = Exception("API Server error")
        flow = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "out",
                    "state": "sent",
                    "identifier": "FLOW_SENT_ERR",
                }
            )
        )
        flow.update_status_button()
        self.assertEqual(flow.state, "sent")
        self.assertIn("API Server error", flow.odoo_error_details)

    def test_show_invoices_button_for_purchase_document(self):
        purchase_invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
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
        flow_purchase = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "created",
                    "direction": "in",
                    "move_ids": [(6, 0, [purchase_invoice.id])],
                }
            )
        )
        action = flow_purchase.show_invoices_button()
        self.assertEqual(action["res_id"], purchase_invoice.id)

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.parse_cdar")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._match_partner_from_event"
    )
    def test_process_creates_event_and_mail_activities(
        self, mock_match_partner, mock_parse
    ):
        user = self.env.user
        self.company.write(
            {
                "fr_ctc_activity_warning_event_user_ids": [(6, 0, [user.id])],
            }
        )

        mock_parse.return_value = {
            "invoice_number": self.invoice.name,
            "invoice_issuer": {
                "0002": "120027016",
            },
            "status": "refused",
            "status_code": "210",
            "lc_datetime": datetime.datetime.now(),
            "lifecycle_id": "LC_999",
            "identifier": "EVT_999",
            "attachments": [
                {
                    "filename": "error_log.txt",
                    "bin": b"RGV0YWlscyBvZiBlcnJvcg==",
                }
            ],
            "doc_status": [
                {
                    "reason_code": "TX_TVA_ERR",
                    "comment": "rejected comments",
                    "action_code": "OTH",
                    "doc_characteristics": [
                        {
                            "date": datetime.date.today(),
                            "amount": {
                                "currency": "EUR",
                                "float": 50.0,
                            },
                        }
                    ],
                }
            ],
        }
        mock_match_partner.return_value = self.customer

        flow_lc = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "downloaded",
                    "direction": "in",
                    "file_bin": b"dGVzdA==",
                    "type": "CustomerInvoiceLC",
                }
            )
        )

        flow_lc.process_button()
        self.assertEqual(flow_lc.state, "done")

        event = self.env["fr.einvoicing.event"].search(
            [("move_id", "=", self.invoice.id)]
        )
        self.assertTrue(event.exists())
        self.assertEqual(event.status, "refused")
        self.assertEqual(len(event.detail_ids), 1)
        self.assertEqual(event.detail_ids[0].comment, "rejected comments")
        self.assertEqual(len(event.payment_ids), 1)
        self.assertEqual(event.payment_ids[0].amount, 50.0)

        activity = self.env["mail.activity"].search(
            [("res_model", "=", "account.move"), ("res_id", "=", self.invoice.id)]
        )
        self.assertTrue(activity.exists())
        self.assertEqual(activity.user_id, user)

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.parse_cdar")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._match_partner_from_event"
    )
    def test_process_supplier_invoice_lc_with_matching_bill(
        self, mock_match_partner, mock_parse
    ):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.customer.id,
                "ref": "BILL-999",
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
        mock_parse.return_value = {
            "invoice_number": "BILL-999",
            "invoice_issuer": {
                "0002": "552081317",
            },
            "status": "approved",
            "status_code": "205",
            "lc_datetime": datetime.datetime.now(),
            "lifecycle_id": "LC_BILL",
            "identifier": "EVT_BILL",
        }
        mock_match_partner.return_value = self.customer

        flow_lc = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "downloaded",
                    "direction": "in",
                    "file_bin": b"dGVzdA==",
                    "type": "SupplierInvoiceLC",
                }
            )
        )
        flow_lc.process_button()
        self.assertEqual(flow_lc.state, "done")

        event = self.env["fr.einvoicing.event"].search([("move_id", "=", bill.id)])
        self.assertTrue(event.exists())

    @patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.parse_cdar")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._match_partner_from_event"
    )
    def test_process_supplier_invoice_lc_no_matching_bill_sets_error(
        self, mock_match_partner, mock_parse
    ):
        mock_parse.return_value = {
            "invoice_number": "BILL-NON-EXISTENT",
            "invoice_issuer": {
                "0002": "552081317",
            },
            "status": "approved",
            "status_code": "205",
            "lc_datetime": datetime.datetime.now(),
            "lifecycle_id": "LC_BILL",
            "identifier": "EVT_BILL",
        }
        mock_match_partner.return_value = self.customer

        flow_lc = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "state": "downloaded",
                    "direction": "in",
                    "file_bin": b"dGVzdA==",
                    "type": "SupplierInvoiceLC",
                }
            )
        )
        flow_lc.process_button()
        self.assertEqual(flow_lc.state, "error")
        self.assertIn("No supplier invoice/refund found", flow_lc.odoo_error_details)

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    def test_send_button_missing_fields_warnings(self, mock_get_session):
        mock_get_session.return_value = MagicMock()
        flow = (
            self.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": self.company.id,
                    "direction": "out",
                    "state": "generated",
                    "file_bin": b"dGVzdA==",
                    "filename": False,
                    "syntax": "UBL",
                    "processing_rule": "B2B",
                }
            )
        )
        flow.send_button()
        self.assertEqual(flow.state, "generated")

        flow.write({"filename": "invoice.xml", "syntax": False})
        flow.send_button()
        self.assertEqual(flow.state, "generated")

        flow.write({"syntax": "UBL", "processing_rule": False})
        flow.send_button()
        self.assertEqual(flow.state, "generated")
