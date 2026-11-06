# Copyright 2026 FactorLibre (https://factorlibre.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import tools
from odoo.exceptions import UserError
from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestNeutralize(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        france = cls.env.ref("base.fr")
        cls.company_a = cls.env["res.company"].create(
            {
                "name": "Neutralize Company A",
                "country_id": france.id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": "test-client-id-a",
                "fr_ctc_client_secret": "test-client-secret-a",
                "fr_ctc_send_out_invoice": "all",
                "fr_ctc_get_in_invoice": True,
                "fr_ctc_directory_sync_on_invoice_post": "blocking",
            }
        )
        cls.company_b = cls.env["res.company"].create(
            {
                "name": "Neutralize Company B",
                "country_id": france.id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "authorization_code",
                "fr_ctc_directory_sync_on_invoice_post": "no",
            }
        )
        # Non French company left with the default settings
        cls.company_c = cls.env["res.company"].create(
            {"name": "Neutralize Company C", "country_id": cls.env.ref("base.es").id}
        )
        token_model = cls.env["fr.einvoicing.token"].sudo()
        token_model.create({"company_id": cls.company_a.id, "access_token": "a"})
        token_model.create(
            {
                "company_id": cls.company_b.id,
                "access_token": "b",
                "refresh_token": "refresh-b",
            }
        )

    def _neutralize(self):
        self.env.flush_all()
        for query in get_neutralization_queries(["l10n_fr_einvoicing"]):
            self.cr.execute(query)
        self.env.invalidate_all()

    def test_01_neutralize_removes_credentials_and_disables_exchange(self):
        token_model = self.env["fr.einvoicing.token"].sudo()
        self.assertEqual(token_model.search_count([]), 2)
        self.assertEqual(self.company_a.sudo().fr_ctc_client_id, "test-client-id-a")
        self.assertEqual(self.company_a.fr_ctc_send_out_invoice, "all")
        self.assertTrue(self.company_a.fr_ctc_get_in_invoice)
        self._neutralize()
        self.assertEqual(token_model.search_count([]), 0)
        companies = self.env["res.company"].sudo().search([])
        self.assertIn(self.company_b, companies)
        self.assertEqual(set(companies.mapped("fr_ctc_auth_method")), {False})
        self.assertEqual(set(companies.mapped("fr_ctc_client_id")), {False})
        self.assertEqual(set(companies.mapped("fr_ctc_client_secret")), {False})
        self.assertEqual(set(companies.mapped("fr_ctc_send_out_invoice")), {"none"})
        self.assertEqual(set(companies.mapped("fr_ctc_get_in_invoice")), {False})

    def test_02_neutralize_blocks_session_both_auth_methods(self):
        self._neutralize()
        # With authorization_code the client ID comes from the server config
        with (
            patch.dict(tools.config.options, {"fr_ctc_superpdp_client_id": "test"}),
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.res_company.get_session"
            ) as mock_get_session,
        ):
            with self.assertRaisesRegex(UserError, "authentication method"):
                self.company_a._fr_ctc_get_session()
            with self.assertRaisesRegex(UserError, "authentication method"):
                self.company_b._fr_ctc_get_session()
            mock_get_session.assert_not_called()

    def test_03_neutralize_directory_sync(self):
        companies = self.company_a | self.company_b | self.company_c
        self.assertEqual(
            companies.mapped("fr_ctc_directory_sync_on_invoice_post"),
            ["blocking", "no", "not_blocking"],
        )
        self._neutralize()
        self.assertEqual(
            companies.mapped("fr_ctc_directory_sync_on_invoice_post"),
            ["not_blocking", "no", "not_blocking"],
        )
