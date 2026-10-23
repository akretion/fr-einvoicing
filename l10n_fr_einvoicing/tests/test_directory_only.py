# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

GET_SESSION = "odoo.addons.l10n_fr_einvoicing.models.res_company.get_session"


@tagged("post_install", "-at_install")
class TestDirectoryOnly(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write(
            {
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_auth_method": "client_credentials",
                "fr_ctc_client_id": "test-client-id",
                "fr_ctc_client_secret": "test-client-secret",
                "fr_ctc_directory_only": True,
            }
        )

    def test_flow_session_refused(self):
        with patch(GET_SESSION) as get_session:
            with self.assertRaisesRegex(UserError, "directory only"):
                self.company._fr_ctc_get_session()
            get_session.assert_not_called()

    def test_directory_session_allowed(self):
        with patch(GET_SESSION, return_value="session") as get_session:
            self.assertEqual(
                self.company._fr_ctc_get_session(directory=True), "session"
            )
            get_session.assert_called_once()

    def test_flow_session_allowed_without_option(self):
        self.company.fr_ctc_directory_only = False
        with patch(GET_SESSION, return_value="session"):
            self.assertEqual(self.company._fr_ctc_get_session(), "session")

    def test_flow_crons_skip_company(self):
        flow_obj = self.env["fr.einvoicing.flow"]
        self.company.partner_id.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": "2026-10-20",
            }
        )
        self.assertNotIn(self.company, flow_obj._cron_companies())
        self.company.fr_ctc_directory_only = False
        self.assertIn(self.company, flow_obj._cron_companies())

    def test_partner_directory_sync_uses_directory_session(self):
        partner = self.env["res.partner"].create(
            {"name": "Directory partner", "is_company": True}
        )
        with patch(GET_SESSION, return_value="session"), patch.object(
            type(partner), "_fr_directory_sync", return_value=None
        ) as sync:
            partner._fr_directory_sync_logs(self.company, "test")
            sync.assert_called_once()
