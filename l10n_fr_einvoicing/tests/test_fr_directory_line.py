# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrDirectoryLine(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Partner Directory Line",
            }
        )

    def test_directory_line_active_computation(self):
        line_active = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "123456789",
                "type": "siren",
                "state": "active",
            }
        )
        line_disabled = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "987654321",
                "type": "siren",
                "state": "disabled",
            }
        )

        self.assertTrue(line_active.active)
        self.assertFalse(line_disabled.active)

    def test_directory_line_display_name_computation(self):
        line_routing = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "ROUTING123",
                "type": "routing_code",
                "routing_code_name": "Test Code",
                "state": "active",
            }
        )
        line_inactive = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "111222333",
                "type": "siren",
                "state": "inactive",
            }
        )

        self.assertEqual(line_routing.display_name, "ROUTING123 Test Code")
        self.assertEqual(line_inactive.display_name, "[Inactive] 111222333")

    def test_confirm_common_checks_when_inactive_returns_error(self):
        line = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "111222333",
                "type": "siren",
                "state": "inactive",
            }
        )

        error = line._confirm_common_checks(commitment_ref=False, origin="INV1")

        self.assertIsNotNone(error)
        self.assertIn("is not active", error)

    def test_confirm_common_checks_when_commitment_required_and_missing_returns_error(
        self,
    ):
        line = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "111222333",
                "type": "siren",
                "state": "active",
                "commitment_required": True,
            }
        )

        error = line._confirm_common_checks(commitment_ref=False, origin="INV1")

        self.assertIsNotNone(error)
        self.assertIn("requires a commitment reference", error)

    def test_confirm_common_checks_when_valid_returns_none(self):
        line = self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "111222333",
                "type": "siren",
                "state": "active",
                "commitment_required": True,
            }
        )

        error = line._confirm_common_checks(commitment_ref="REF123", origin="INV1")

        self.assertIsNone(error)

    @mute_logger("odoo.sql_db")
    def test_partner_identifier_unique_constraint(self):
        self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "111222333",
                "type": "siren",
                "state": "active",
            }
        )

        with self.assertRaises(IntegrityError):
            self.env["fr.directory.line"].create(
                {
                    "partner_id": self.partner.id,
                    "identifier": "111222333",
                    "type": "siren",
                    "state": "active",
                }
            )
