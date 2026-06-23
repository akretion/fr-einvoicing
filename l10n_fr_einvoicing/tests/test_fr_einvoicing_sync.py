# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import contextlib
import datetime
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tools import config

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestFrEinvoicingSync(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test Company AP",
                "country_id": cls.env.ref("base.fr").id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": "test_client_id",
                "fr_ctc_client_secret": "test_client_secret",
            }
        )
        cls.company.partner_id.write(
            {
                "siren": "120027016",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Partner AP",
                "siren": "120027016",
                "siret": "12002701600001",
                "country_id": cls.env.ref("base.fr").id,
                "is_company": True,
            }
        )

    @contextlib.contextmanager
    def _mock_cursor(self):
        yield self.env.cr

    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.get_session")
    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.healthcheck")
    def test_test_api_success(self, mock_healthcheck, mock_get_session):
        mock_healthcheck.return_value = True
        mock_get_session.return_value = MagicMock()

        action = self.company._fr_ctc_test_api()

        self.assertEqual(action["params"]["type"], "success")
        self.assertIn("Successful connection", action["params"]["message"])

    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.get_session")
    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.healthcheck")
    def test_test_api_failure(self, mock_healthcheck, mock_get_session):
        mock_get_session.return_value = MagicMock()
        mock_healthcheck.side_effect = Exception("Connection Failed")

        with self.assertRaisesRegex(UserError, "Odoo failed to connect to the API"):
            self.company._fr_ctc_test_api()

    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.get_authorization_url")
    def test_authorization_code_redirect(self, mock_get_auth_url):
        mock_get_auth_url.return_value = (
            "https://example.com/oauth",
            "state123",
            "verifier123",
        )
        self.company.fr_ctc_auth_method = "authorization_code"

        with patch.dict(
            config.options, {"fr_ctc_superpdp_client_id": "dummy_client_id"}
        ):
            action = self.company._fr_ctc_authorization_code_redirect()

        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["url"], "https://example.com/oauth")

    def test_is_vat_registered_returns_false_for_non_france_company(self):
        non_fr_company = self.env["res.company"].create(
            {
                "name": "Non FR Company",
                "country_id": self.env.ref("base.us").id,
            }
        )

        res = non_fr_company._fr_ctc_is_vat_registered()

        self.assertFalse(res)

    def test_is_vat_registered_raises_no_country(self):
        non_country_company = self.env["res.company"].create(
            {
                "name": "No Country Company",
            }
        )
        with self.assertRaisesRegex(UserError, "Country is not set on company"):
            non_country_company._fr_ctc_is_vat_registered(raise_if_misconfigured=True)

    def test_is_vat_registered_raises_no_entity_type(self):
        self.company.partner_id.write(
            {
                "fr_directory_entity_type": False,
                "fr_directory_last_sync_date": False,
            }
        )
        with self.assertRaisesRegex(UserError, "Entity type is not set on partner"):
            self.company._fr_ctc_is_vat_registered(raise_if_misconfigured=True)

    def test_is_vat_registered_raises_public_entity_type(self):
        self.company.partner_id.write(
            {
                "fr_directory_entity_type": "public",
                "fr_directory_last_sync_date": datetime.date.today(),
            }
        )
        with self.assertRaisesRegex(
            UserError, "is a public entity. This scenario is not supported"
        ):
            self.company._fr_ctc_is_vat_registered(raise_if_misconfigured=True)

    def test_is_vat_registered_raises_private_no_siren(self):
        self.company.partner_id.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": datetime.date.today(),
                "siren": False,
            }
        )
        with self.assertRaisesRegex(UserError, "SIREN is not set on partner"):
            self.company._fr_ctc_is_vat_registered(raise_if_misconfigured=True)

    def test_fr_ctc_credentials_raises_no_platform(self):
        self.company.fr_ctc_accredited_platform = False
        with self.assertRaisesRegex(
            UserError, "No accredited platform selected for company"
        ):
            self.company._fr_ctc_credentials()

    def test_fr_ctc_credentials_raises_no_auth_method(self):
        self.company.fr_ctc_auth_method = False
        with self.assertRaisesRegex(
            UserError,
            "The authentication method for the accredited platform is not configured",
        ):
            self.company._fr_ctc_credentials()

    def test_fr_ctc_credentials_raises_client_credentials_no_client_id(self):
        self.company.write(
            {
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": False,
            }
        )
        with self.assertRaisesRegex(
            UserError, "The Client ID of the accredited platform is not configured"
        ):
            self.company._fr_ctc_credentials()

    def test_fr_ctc_credentials_raises_client_credentials_no_client_secret(self):
        self.company.write(
            {
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_secret": False,
            }
        )
        with self.assertRaisesRegex(
            UserError, "The Client Secret of the accredited platform is not configured"
        ):
            self.company._fr_ctc_credentials()

    def test_fr_ctc_credentials_raises_authorization_code_no_client_id_config(self):
        self.company.write(
            {
                "fr_ctc_auth_method": "authorization_code",
            }
        )
        with patch.dict(config.options, {"fr_ctc_superpdp_client_id": ""}):
            with self.assertRaisesRegex(
                UserError,
                (
                    "Missing key 'fr_ctc_superpdp_client_id' "
                    "in the Odoo server configuration file"
                ),
            ):
                self.company._fr_ctc_credentials()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_lines_parsed"
    )
    def test_partner_directory_sync_private_company(
        self, mock_get_lines, mock_get_siren
    ):
        mock_get_siren.return_value = {
            "entity_type": "private",
            "closed": False,
            "name": "Test Partner AP Clean",
        }
        mock_get_lines.return_value = {
            "120027016": {
                "state": "active",
                "routing_code_name": "ROUTING_A",
                "commitment_required": False,
                "type": "siren",
            }
        }
        mock_session = MagicMock()

        self.partner._fr_directory_sync(
            mock_session, result={"logs": [], "new_count": 0, "updated_count": 0}
        )

        self.assertEqual(self.partner.fr_directory_entity_type, "private")
        self.assertEqual(self.partner.fr_directory_name, "Test Partner AP Clean")
        self.assertFalse(self.partner.fr_directory_closed)
        self.assertEqual(len(self.partner.fr_directory_line_ids), 1)
        self.assertEqual(self.partner.fr_directory_line_ids[0].identifier, "120027016")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    def test_partner_directory_sync_closed_company(self, mock_get_siren):
        mock_get_siren.return_value = {
            "entity_type": "private",
            "closed": True,
            "name": "Test Partner Closed",
        }
        mock_session = MagicMock()

        self.partner._fr_directory_sync(
            mock_session, result={"logs": [], "new_count": 0, "updated_count": 0}
        )

        self.assertEqual(self.partner.fr_directory_entity_type, "private")
        self.assertTrue(self.partner.fr_directory_closed)

    def test_token_get_and_write(self):
        with patch.object(self.env.registry, "cursor", side_effect=self._mock_cursor):
            self.company._fr_ctc_write_token(
                {
                    "access_token": "abc_access",
                    "refresh_token": "abc_refresh",
                    "expires_at": 123456789.0,
                }
            )
            token = self.company._fr_ctc_get_token("authorization_code")

            self.assertEqual(token["access_token"], "abc_access")
            self.assertEqual(token["refresh_token"], "abc_refresh")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany.fr_ctc_run_import_log"
    )
    def test_run_import_log_action_returns_correct_action(self, mock_run_import_log):
        result = {
            "new_count": 2,
            "warning_count": 1,
            "error_count": 0,
        }
        mock_run_import_log.return_value = (None, result)
        action = self.company.fr_ctc_run_import_log_action("Test Origin")

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["params"]["type"], "warning")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siret_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_lines_parsed"
    )
    def test_partner_directory_sync_public_entity(
        self, mock_get_lines, mock_get_siret, mock_get_siren
    ):
        mock_get_siren.return_value = {
            "entity_type": "public",
            "closed": False,
            "name": "Public Entity AP",
        }
        mock_get_siret.return_value = {
            "closed": False,
            "name": "Public Branch AP",
        }
        mock_get_lines.return_value = {
            "12002701600001": {
                "state": "active",
                "routing_code_name": "ROUTING_B",
                "commitment_required": True,
                "type": "siret",
            }
        }
        mock_session = MagicMock()

        self.partner._fr_directory_sync(
            mock_session, result={"logs": [], "new_count": 0, "updated_count": 0}
        )
        self.assertEqual(self.partner.fr_directory_entity_type, "public")
        self.assertEqual(self.partner.fr_directory_name, "Public Branch AP")
        self.assertEqual(len(self.partner.fr_directory_line_ids), 1)

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_lines_parsed"
    )
    def test_partner_directory_sync_button(
        self, mock_get_lines, mock_get_siren, mock_get_session
    ):
        mock_get_siren.return_value = {
            "entity_type": "private",
            "closed": False,
            "name": "Sync Button Partner",
        }
        mock_get_lines.return_value = {}

        action = self.partner.fr_directory_sync_button()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["params"]["type"], "success")

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_lines_parsed"
    )
    def test_partner_directory_sync_cron(
        self, mock_get_lines, mock_get_siren, mock_get_session
    ):
        mock_get_siren.return_value = {
            "entity_type": "private",
            "closed": False,
            "name": "Cron Sync Partner",
        }
        mock_get_lines.return_value = {}

        self.partner.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_closed": False,
                "fr_directory_last_sync_date": datetime.date.today()
                - datetime.timedelta(days=100),
            }
        )

        self.env["res.partner"]._fr_directory_sync_cron()
        self.assertEqual(self.partner.fr_directory_name, "Cron Sync Partner")

    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.get_session")
    @patch("odoo.addons.l10n_fr_einvoicing.models.res_company.search_flows_parsed")
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_prepare_in_flow"
    )
    def test_fr_ctc_run_import_log_real(
        self, mock_prepare_in_flow, mock_search_flows, mock_get_session
    ):
        mock_get_session.return_value = MagicMock()
        mock_search_flows.return_value = [
            {
                "flowId": "flow_in_999",
                "flowSyntax": "UBL",
                "flowType": "SupplierInvoice",
                "processingRule": "B2B",
                "flow_direction": "in",
                "type": "SupplierInvoice",
            }
        ]
        mock_prepare_in_flow.return_value = {
            "direction": "in",
            "identifier": "flow_in_999",
            "syntax": "UBL",
            "type": "SupplierInvoice",
            "processing_rule": "B2B",
            "company_id": self.company.id,
        }

        with (
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._download"
            ) as mock_download,
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.FrEinvoicingFlow._process"
            ),
        ):
            flows, result = self.company.fr_ctc_run_import_log("Cron Origin")

            self.assertEqual(len(flows), 1)
            self.assertEqual(flows.identifier, "flow_in_999")
            self.assertEqual(result["new_count"], 1)
            mock_download.assert_called_once()

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    def test_partner_directory_sync_not_in_directory(
        self, mock_get_siren, mock_get_session
    ):
        mock_get_siren.return_value = {
            "entity_type": "no",
            "closed": False,
            "name": "Unknown Partner",
        }
        action = self.partner.fr_directory_sync_button()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("is not in the directory", action["params"]["message"])

    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_company.ResCompany._fr_ctc_get_session"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_siren_parsed"
    )
    @patch(
        "odoo.addons.l10n_fr_einvoicing.models.res_partner.get_directory_lines_parsed"
    )
    def test_partner_directory_sync_lines_failure(
        self, mock_get_lines, mock_get_siren, mock_get_session
    ):
        mock_get_siren.return_value = {
            "entity_type": "private",
            "closed": False,
            "name": "Some Partner",
        }
        mock_get_lines.side_effect = Exception("API connection timed out")
        with self.assertRaisesRegex(
            UserError, "Failed to query directory with SIREN or SIRET"
        ):
            self.partner.fr_directory_sync_button()
