# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import ValidationError

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestResPartner(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.france = cls.env.ref("base.fr")
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Partner ResPartner",
                "country_id": cls.france.id,
                "is_company": True,
                "siren": "120027016",
                "siret": "12002701600001",
            }
        )

    def test_fr_directory_line_show_when_private_or_public(self):
        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": False,
                "fr_directory_last_sync_date": "2026-06-23",
            }
        )
        self.partner._compute_fr_directory_line_show()
        self.assertTrue(self.partner.fr_directory_line_show)

        self.partner.write(
            {
                "fr_directory_closed": True,
            }
        )
        self.partner._compute_fr_directory_line_show()
        self.assertFalse(self.partner.fr_directory_line_show)

    def test_fr_directory_line_active_count_increments_on_active_lines(self):
        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": False,
                "fr_directory_last_sync_date": "2026-06-23",
            }
        )

        self.partner._compute_fr_directory_line_active_count()
        self.assertEqual(self.partner.fr_directory_line_active_count, 0)

        self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": "123456789",
                "type": "siren",
                "state": "active",
            }
        )
        self.partner._compute_fr_directory_line_active_count()
        self.assertEqual(self.partner.fr_directory_line_active_count, 1)

    def test_fr_directory_entity_changed_warning_triggers_on_siren_or_siret_diff(self):
        self.partner.write(
            {
                "fr_directory_entity_type": "public",
                "fr_directory_siret": "12002701600001",
                "fr_directory_last_sync_date": "2026-06-23",
                "siret": "12002701600027",
            }
        )
        self.partner._compute_fr_directory_entity_changed_warning()
        self.assertIsNotNone(self.partner.fr_directory_entity_changed_warning)

        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_siren": "120027016",
                "fr_directory_last_sync_date": "2026-06-23",
                "siret": "55208131700018",
            }
        )
        self.partner._compute_fr_directory_entity_changed_warning()
        self.assertIsNotNone(self.partner.fr_directory_entity_changed_warning)

    def test_fr_directory_show_warning_missing_siren_on_french_company(self):
        # We need to use another partner to avoid validation checks on
        # siren/siret fields of self.partner
        tmp_partner = self.env["res.partner"].create(
            {
                "name": "Tmp Partner",
                "is_company": True,
                "parent_id": False,
                "vat": False,
                "siren": False,
                "country_id": self.france.id,
            }
        )
        tmp_partner._compute_fr_directory_show_warning_missing_siren()
        self.assertTrue(tmp_partner.fr_directory_show_warning_missing_siren)

    def test_fr_directory_reset_parent_clears_fields_when_parent_is_set(self):
        parent = self.env["res.partner"].create({"name": "Parent Partner"})
        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": True,
                "fr_directory_name": "Test Name",
                "fr_directory_last_sync_date": "2026-06-23",
                "parent_id": parent.id,
            }
        )
        self.partner._compute_fr_directory_reset_parent()
        self.assertFalse(self.partner.fr_directory_entity_type)
        self.assertFalse(self.partner.fr_directory_closed)
        self.assertFalse(self.partner.fr_directory_name)
        self.assertFalse(self.partner.fr_directory_last_sync_date)

    def test_fr_directory_check_raises_validation_error_on_missing_sync_date(self):
        with self.assertRaises(ValidationError):
            self.env["res.partner"].create(
                {
                    "name": "Invalid Partner",
                    "fr_directory_entity_type": "private",
                    "fr_directory_last_sync_date": False,
                }
            )

    def test_fr_directory_confirm_common_checks_returns_error_if_closed(self):
        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": True,
                "fr_directory_last_sync_date": "2026-06-23",
            }
        )
        err = self.partner._fr_directory_confirm_common_checks()
        self.assertIn("is marked as closed", err)

    def test_fr_directory_siren_change_error_returns_error_on_mismatch(self):
        self.partner.write(
            {
                "siret": "55208131700018",
                "fr_directory_siren": "120027016",
            }
        )
        err = self.partner._fr_directory_siren_change_error()
        self.assertIn("SIREN currently configured", err)

    def test_fr_directory_siret_change_error_returns_error_on_mismatch(self):
        self.partner.write(
            {
                "siret": "12002701600027",
                "fr_directory_siret": "12002701600001",
            }
        )
        err = self.partner._fr_directory_siret_change_error()
        self.assertIn("SIRET currently configured", err)

    def test_fr_directory_sync_if_old_get_days_invalid_and_negative(self):
        self.env["ir.config_parameter"].set_param(
            "fr_directory.update_partner_if_older_than_days", "invalid_value"
        )
        self.env["ir.config_parameter"].set_param(
            "fr_directory.update_private_inactive_partner_if_older_than_days", "-10"
        )

        result = {"logs": [], "new_count": 0, "updated_count": 0}
        days = self.env["res.partner"]._fr_directory_sync_if_old_get_days(result)
        # DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS = 30
        # DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS = 5
        self.assertEqual(days[0], 30)
        self.assertEqual(days[1], 5)
        self.assertTrue(
            any(
                "Failed to convert ir.config_parameter" in log[1]
                for log in result["logs"]
            )
        )
        self.assertTrue(any("is negative" in log[1] for log in result["logs"]))

    def test_fr_directory_confirm_common_checks_returns_none(self):
        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": False,
                "fr_directory_last_sync_date": "2026-06-23",
                "fr_directory_siren": "120027016",
            }
        )
        self.assertIsNone(self.partner._fr_directory_confirm_common_checks())

        # Also cover no-change paths for siret/siren error methods directly
        self.assertIsNone(self.partner._fr_directory_siren_change_error("120027016"))
        self.assertIsNone(
            self.partner._fr_directory_siret_change_error("12002701600001")
        )

        self.partner.write(
            {
                "fr_directory_entity_type": "public",
                "fr_directory_siret": "12002701600001",
            }
        )
        self.assertIsNone(self.partner._fr_directory_confirm_common_checks())
