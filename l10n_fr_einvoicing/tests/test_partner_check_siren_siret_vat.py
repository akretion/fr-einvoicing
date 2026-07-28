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

    def test_check_siren_siret_vat_remove_spaces_in_vat(self):
        self.env.cr.execute(
            "UPDATE res_partner SET vat='FR 86 792377731' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.vat, "FR86792377731")
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_bad_vat(self):
        self.env.cr.execute(
            "UPDATE res_partner SET vat='FR 87 792377999' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.vat)
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_bad_vat_but_valid_siren(self):
        self.env.cr.execute(
            "UPDATE res_partner SET vat='FR 87 792377731' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.vat)
        self.assertEqual(self.partner.siret, "792377731*****")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_set_siren_nic(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "79237773100023")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertEqual(self.partner.nic, "00023")

    def test_check_siren_siret_vat_bad_nic_checksum(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100029' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "792377731*****")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_bad_siren_checksum(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773900029' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_reset_all(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023', siren='662631639', "
            "nic='00017' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "66263163900017")
        self.assertEqual(self.partner.siren, "662631639")
        self.assertEqual(self.partner.nic, "00017")

    def test_check_siren_siret_vat_inconsistent_vat(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023', siren='792377731', "
            "nic='00023', vat='fr 13 648670396' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic", "vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)
        self.assertEqual(self.partner.vat, "FR13648670396")

    def test_check_siren_siret_vat_bad_nic(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023', siren='792377731', "
            "nic='000 2' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "792377731*****")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertFalse(self.partner.nic)

    def test_check_siren_siret_vat_spaces_siren(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023', siren='  ', "
            "nic=' ' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "79237773100023")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertEqual(self.partner.nic, "00023")

    def test_check_siren_siret_vat_spaces_siret(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='  ', siren='792377731', "
            "nic='00023' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertTrue(res)
        self.assertEqual(self.partner.siret, "79237773100023")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertEqual(self.partner.nic, "00023")

    def test_check_siren_siret_vat_all_spaces(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='  ', siren='  ', "
            "nic=' ', vat='  ' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic", "vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)
        self.assertFalse(self.partner.vat)

    def test_check_siren_siret_all_ok(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='79237773100023', siren='792377731', "
            "nic='00023', vat='FR 86 792377731' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic", "vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.siret, "79237773100023")
        self.assertEqual(self.partner.siren, "792377731")
        self.assertEqual(self.partner.nic, "00023")
        self.assertEqual(self.partner.vat, "FR86792377731")

    def test_check_siren_siret_superpdp(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='000000001*****', siren='000000001', "
            "vat='FR42000000001' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic", "vat"])
        res = self.partner._fr_directory_check_siren_siret_vat()
        self.assertFalse(res)
        self.assertEqual(self.partner.siren, "000000001")
        self.assertEqual(self.partner.vat, "FR42000000001")

    def test_full_wizard(self):
        self.env.cr.execute(
            "UPDATE res_partner SET siret='792377731*****', siren='792377731', "
            "vat='FR63763983269' WHERE id=%s",
            (self.partner.id,),
        )
        self.partner.invalidate_recordset(["siret", "siren", "nic", "vat"])
        action = self.env["res.config.settings"].fr_ctc_check_siren_siret_vat_button()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["params"]["type"], "warning")
        self.assertFalse(self.partner.siret)
        self.assertFalse(self.partner.siren)
        self.assertFalse(self.partner.nic)
        self.assertEqual(self.partner.vat, "FR63763983269")
