# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import datetime

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrEinvoicingEvent(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "French Customer Partner Event",
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
        cls.event = (
            cls.env["fr.einvoicing.event"]
            .sudo()
            .create(
                {
                    "flow_id": cls.flow.id,
                    "status": "approved",
                    "direction": "in",
                    "company_id": cls.company.id,
                    "move_id": cls.invoice.id,
                }
            )
        )

    def test_status_selection_returns_non_empty_list(self):
        status_sel = self.event._status_selection()
        self.assertTrue(len(status_sel) > 0)

    def test_status_selection_manual_returns_non_empty_lists(self):
        manual_sale = self.event._status_selection_manual("sale")
        manual_purchase = self.event._status_selection_manual("purchase")
        self.assertTrue(len(manual_sale) > 0)
        self.assertTrue(len(manual_purchase) > 0)

    def test_get_status_key_for_submitted(self):
        status_key = self.event._get_status_key("200")
        self.assertEqual(status_key, "submitted")

    def test_convert_datetime2str_returns_formatted_string(self):
        dt = datetime(2026, 4, 30, 13, 37, 56)
        dt_str = self.event._convert_datetime2str(dt, "%Y-%m-%dT%H:%M:%S")
        self.assertEqual(dt_str, "2026-04-30T13:37:56")

    def test_compute_status_decoration_returns_expected_decoration(self):
        self.event.status = "approved"
        self.event._compute_status_decoration()
        self.assertEqual(self.event.status_decoration, "success")

        self.event.status = "rejected"
        self.event._compute_status_decoration()
        self.assertEqual(self.event.status_decoration, "danger")

    def test_compute_display_name_includes_status(self):
        self.event.status = "rejected"
        self.event._compute_display_name()
        self.assertIn("Rejected", self.event.display_name)

    def test_event_detail_selection_methods_return_valid_data(self):
        detail_model = self.env["fr.einvoicing.event.detail"]
        all_reasons = detail_model._get_all_reasons()
        self.assertTrue(isinstance(all_reasons, dict))

        reasons_sel = detail_model._reason_selection()
        self.assertTrue(len(reasons_sel) > 0)

        actions_sel = detail_model._action_selection()
        self.assertTrue(len(actions_sel) > 0)

    def test_prepare_xml_data_out_invoice(self):
        self.company.partner_id.write(
            {
                "siren": "120027016",
            }
        )
        self.invoice.write(
            {
                "invoice_date": datetime(2026, 4, 30).date(),
                "fr_directory_line_identifier": "120027016",
                "name": "INV/2026/0001",
            }
        )
        self.event.write(
            {
                "status": "approved",
            }
        )
        data = self.event._prepare_xml_data()
        self.assertEqual(data["MDT-88"], "1")
        self.assertEqual(data["MDT-87"], "INV/2026/0001")
        self.assertEqual(data["MDT-73"], "120027016")
