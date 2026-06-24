# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestResConfigSettings(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wizard = cls.env["res.config.settings"].create({})

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_test_api"
    )
    def test_fr_ctc_test_api_button(self, mock_test_api):
        mock_test_api.return_value = {"type": "ir.actions.client"}
        res = self.wizard.fr_ctc_test_api_button()
        self.assertEqual(res, {"type": "ir.actions.client"})

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_authorization_code_redirect"
    )
    def test_fr_ctc_authorization_code_onboarding(self, mock_redirect):
        mock_redirect.return_value = {"type": "ir.actions.act_url"}
        res = self.wizard.fr_ctc_authorization_code_onboarding()
        self.assertEqual(res, {"type": "ir.actions.act_url"})
