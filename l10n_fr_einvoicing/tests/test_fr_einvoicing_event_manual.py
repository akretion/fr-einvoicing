# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import copy
from unittest.mock import patch

from odoo.exceptions import UserError

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrEinvoicingEventManual(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "French Customer Partner Wizard",
                "siren": "552081317",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
            }
        )
        cls.invoice_sale = cls.env["account.move"].create(
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
        cls.flow_sale = (
            cls.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": cls.company.id,
                    "state": "created",
                    "direction": "out",
                    "move_ids": [(6, 0, [cls.invoice_sale.id])],
                }
            )
        )
        cls.invoice_sale.sudo().fr_einvoicing_flow_id = cls.flow_sale.id

        cls.invoice_purchase = cls.env["account.move"].create(
            {
                "move_type": "in_invoice",
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
        cls.flow_purchase = (
            cls.env["fr.einvoicing.flow"]
            .sudo()
            .create(
                {
                    "company_id": cls.company.id,
                    "state": "created",
                    "direction": "in",
                    "move_ids": [(6, 0, [cls.invoice_purchase.id])],
                }
            )
        )
        cls.invoice_purchase.sudo().fr_einvoicing_flow_id = cls.flow_purchase.id

    def test_default_get_loads_status_selections(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_sale.id,
        }
        wiz = self.env["fr.einvoicing.event.manual"].with_context(**ctx).create({})
        self.assertTrue(len(wiz._status_sale_selection()) > 0)
        self.assertTrue(len(wiz._status_purchase_selection()) > 0)

    def test_empty_status_computes_no_required_fields(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_sale.id,
        }
        wiz = self.env["fr.einvoicing.event.manual"].with_context(**ctx).create({})
        wiz._compute_required_fields()
        self.assertFalse(wiz.detail_required)

    def test_status_completed_on_sales_document_creates_event_and_copies_attachments(
        self,
    ):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_sale.id,
        }
        wiz = self.env["fr.einvoicing.event.manual"].with_context(**ctx).create({})
        wiz.status_sale = "completed"
        wiz._compute_required_fields()
        self.assertFalse(wiz.detail_required)
        self.assertFalse(wiz.confirm_required)

        attachment = self.env["ir.attachment"].create(
            {
                "name": "test.txt",
                "raw": b"Hello world",
            }
        )
        wiz.attachment_ids = [(6, 0, [attachment.id])]

        wiz.run()
        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .search([("move_id", "=", self.invoice_sale.id)])
        )
        self.assertEqual(event.status, "completed")
        self.assertTrue(event.attachment_ids.exists())

    def test_status_dispute_requires_details_and_raises_user_error(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "dispute",
                }
            )
        )
        wiz._compute_required_fields()
        self.assertTrue(wiz.detail_required)

        with self.assertRaisesRegex(
            UserError, "you must create at least one line of details"
        ):
            wiz.run()

    def test_status_dispute_with_details_creates_event_successfully(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "dispute",
                }
            )
        )
        self.env["fr.einvoicing.event.detail.manual"].create(
            {
                "event_id": wiz.id,
                "reason_dispute": "JUSTIF_ABS",
                "comment": "Missing documentation",
            }
        )
        wiz.run()
        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .search(
                [("move_id", "=", self.invoice_purchase.id), ("status", "=", "dispute")]
            )
        )
        self.assertTrue(event.exists())

    def test_status_refused_without_details_raises_user_error(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "refused",
                }
            )
        )
        wiz._compute_required_fields()
        with self.assertRaisesRegex(
            UserError, "you must create at least one line of details"
        ):
            wiz.run()

    def test_status_refused_without_confirmation_raises_user_error(self):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "refused",
                }
            )
        )
        self.env["fr.einvoicing.event.detail.manual"].create(
            {
                "event_id": wiz.id,
                "reason_refused": "JUSTIF_ABS",
                "comment": "Refused bill",
            }
        )
        wiz._compute_required_fields()
        with self.assertRaisesRegex(UserError, "You must confirm the refusal"):
            wiz.run()

    def test_status_refused_with_details_and_confirmation_creates_event_successfully(
        self,
    ):
        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "refused",
                }
            )
        )
        self.env["fr.einvoicing.event.detail.manual"].create(
            {
                "event_id": wiz.id,
                "reason_refused": "JUSTIF_ABS",
                "comment": "Refused bill",
            }
        )
        wiz.confirm = True
        wiz.run()
        event = (
            self.env["fr.einvoicing.event"]
            .sudo()
            .search(
                [("move_id", "=", self.invoice_purchase.id), ("status", "=", "refused")]
            )
        )
        self.assertTrue(event.exists())

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_event.FrEinvoicingEvent._get_all_status"
    )
    def test_manual_event_wizard_generic_confirm(self, mock_status):
        all_status = self.env["fr.einvoicing.event"]._get_all_status()
        all_status_copy = copy.deepcopy(all_status)
        all_status_copy["dispute"]["confirm_required"] = True
        mock_status.return_value = all_status_copy

        ctx = {
            "active_model": "account.move",
            "active_id": self.invoice_purchase.id,
        }
        wiz = (
            self.env["fr.einvoicing.event.manual"]
            .with_context(**ctx)
            .create(
                {
                    "status_purchase": "dispute",
                    "confirm": False,
                }
            )
        )
        self.env["fr.einvoicing.event.detail.manual"].create(
            {
                "event_id": wiz.id,
                "reason_dispute": "JUSTIF_ABS",
                "comment": "Missing documentation",
            }
        )
        wiz._compute_required_fields()
        self.assertTrue(wiz.confirm_required)
        with self.assertRaisesRegex(
            UserError, "You must confirm the creation of the event"
        ):
            wiz.run()

    def test_transient_selection_methods(self):
        detail_model = self.env["fr.einvoicing.event.detail.manual"]
        self.assertTrue(len(detail_model._reason_dispute_selection()) > 0)
        self.assertTrue(len(detail_model._reason_partially_approved_selection()) > 0)
        self.assertTrue(len(detail_model._reason_suspended()) > 0)
        self.assertTrue(len(detail_model._reason_refused()) > 0)
        self.assertTrue(len(detail_model._action_selection()) > 0)
