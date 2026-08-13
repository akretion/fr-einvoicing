# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestFrIntrastatService(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.fr_country_id = cls.env.ref("base.fr").id
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test partner",
                "is_company": True,
                "country_id": cls.env.ref("base.fr").id,
            }
        )

    def _write_raw(self, **vals):
        """Write straight in SQL to bypass the constraints of l10n_fr_siret:
        the point of these tests is precisely to feed the cleanup method with
        data that the constraints would have rejected."""
        columns = ", ".join(f"{field}=%s" for field in vals)
        self.env.cr.execute(
            f"UPDATE res_partner SET {columns} WHERE id=%s",
            list(vals.values()) + [self.partner.id],
        )
        self.partner.invalidate_recordset(list(vals.keys()))

    def test_check_siren_siret_vat_remove_spaces_in_vat(self):
        self._write_raw(vat="FR 86 792377731")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.vat, "FR86792377731")
        self.assertFalse(self.partner.company_registry)

    def test_check_siren_siret_vat_bad_vat(self):
        self._write_raw(vat="FR 87 792377999")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.vat)
        self.assertFalse(self.partner.company_registry)

    def test_check_siren_siret_vat_bad_vat_but_valid_siren(self):
        self._write_raw(vat="FR 87 792377731")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.vat)
        self.assertEqual(self.partner.company_registry, "792377731")

    def test_check_siren_siret_vat_valid_siret_untouched(self):
        self._write_raw(company_registry="79237773100023")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.company_registry, "79237773100023")
        self.assertEqual(self.partner._get_siren(), "792377731")
        self.assertEqual(self.partner._get_nic(), "00023")

    def test_check_siren_siret_vat_bad_nic_checksum(self):
        # SIRET checksum is wrong but the SIREN it starts with is valid
        self._write_raw(company_registry="79237773100029")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.company_registry, "792377731")
        self.assertFalse(self.partner._get_nic())

    def test_check_siren_siret_vat_bad_siren_checksum(self):
        self._write_raw(company_registry="79237773900029")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.company_registry)

    def test_check_siren_siret_vat_not_only_digits(self):
        self._write_raw(company_registry="RCS 792377731")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.company_registry)

    def test_check_siren_siret_vat_truncated_siret(self):
        # Neither 9 nor 14 digits: only the SIREN part can be trusted
        self._write_raw(company_registry="792377731000")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.company_registry, "792377731")

    def test_check_siren_siret_vat_inconsistent_vat(self):
        self._write_raw(company_registry="79237773100023", vat="fr 13 648670396")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.company_registry)
        self.assertEqual(self.partner.vat, "FR13648670396")

    def test_check_siren_siret_vat_non_fr_vat(self):
        self._write_raw(company_registry="79237773100023", vat="BE0477472701")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.company_registry, "79237773100023")
        self.assertFalse(self.partner.vat)

    def test_check_siren_siret_vat_spaces_siret(self):
        self._write_raw(company_registry=" 792 377 731 00023 ")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.company_registry, "79237773100023")

    def test_check_siren_siret_vat_all_spaces(self):
        self._write_raw(company_registry="  ", vat="  ")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertFalse(self.partner.company_registry)
        self.assertFalse(self.partner.vat)

    def test_check_siren_siret_all_ok(self):
        self._write_raw(company_registry="79237773100023", vat="FR 86 792377731")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.company_registry, "79237773100023")
        self.assertEqual(self.partner.vat, "FR86792377731")

    def test_check_siren_siret_superpdp(self):
        self._write_raw(company_registry="000000001", vat="FR42000000001")
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.company_registry, "000000001")
        self.assertEqual(self.partner.vat, "FR42000000001")

    def test_full_wizard(self):
        self._write_raw(company_registry="792377731", vat="FR63763983269")
        action = self.env["res.config.settings"].fr_ctc_check_siren_siret_vat_button()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["params"]["type"], "warning")
        self.assertFalse(self.partner.company_registry)
        self.assertEqual(self.partner.vat, "FR63763983269")
