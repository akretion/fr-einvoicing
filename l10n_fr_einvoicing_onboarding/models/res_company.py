# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import os

from odoo import _, fields, models, tools
from odoo.exceptions import UserError
from odoo.http import request

logger = logging.getLogger(__name__)
try:
    from pyfrctc import (
        get_authorization_url,
    )
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)

CALLBACK_PATH = "/fr_ctc_onboarding_callback"


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_ctc_accredited_platform = fields.Selection(
        [
            ("superpdp", "SUPER PDP"),
        ],
        default="superpdp",
        string="Accredited Platform",
    )

    def _fr_ctc_authorization_code_redirect(self):
        self.ensure_one()
        platform = self.fr_ctc_accredited_platform
        if not platform:
            raise UserError(
                _(
                    "No accredited platform selected for company '%s'.",
                    self.display_name,
                )
            )
        client_id_key = f"fr_ctc_{platform}_client_id"
        client_id = tools.config.get(client_id_key)
        if not client_id:
            raise UserError(
                _(
                    "Missing key '%s' in the Odoo server configuration file.",
                    client_id_key,
                )
            )
        optional_uri_params = {}
        if self.fr_ctc_accredited_platform == "superpdp":
            running_env = tools.config.get("running_env")
            siren = self.partner_id.siren
            optional_uri_params = {"superpdp_company_number": siren}
            if running_env in ("test", "dev"):
                optional_uri_params["superpdp_company_number_scheme"] = "sandbox"
            else:
                optional_uri_params["superpdp_company_number_scheme"] = "fr_siren"
        base_url = self.env["ir.config_parameter"].get_param("web.base.url")
        if base_url.startswith("http://"):
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        redirect_uri = f"{base_url}{CALLBACK_PATH}"
        authorization_url, state, code_verifier = get_authorization_url(
            self.fr_ctc_accredited_platform,
            client_id,
            redirect_uri,
            optional_uri_params=optional_uri_params,
        )

        if request:
            request.session["fr_ctc_company_id"] = self.id
            request.session["fr_ctc_code_verifier"] = code_verifier
            request.session["fr_ctc_state"] = state
            request.session.is_dirty = True

        logger.info("Redirecting to URL %s", authorization_url)
        action = {
            "type": "ir.actions.act_url",
            "url": authorization_url,
            "target": "new",
        }
        return action
