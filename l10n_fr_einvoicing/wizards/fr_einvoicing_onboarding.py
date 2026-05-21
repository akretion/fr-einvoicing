# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools
from odoo.exceptions import UserError
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # TODO remove
from requests_oauthlib import OAuth2Session
import hashlib
import base64
import secrets

import logging
logger = logging.getLogger(__name__)

REDIRECT_URI = 'http://localhost:8069/fr_ctc_onboarding_callback'


class FrEinvoicingOnboarding(models.TransientModel):
    _name = "fr.einvoicing.onboarding"
    _description = "Onboarding wizard for eInvoicing"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, readonly=True)
    accredited_platform = fields.Selection(related='company_id.fr_ctc_accredited_platform')
    state_code = fields.Char(readonly=True)
    code_verifier = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env['res.company'].browse(res['company_id'])
        company._fr_ctc_credentials()  # we call it just to get the error messages
        return res

    def redirect(self):
        self.ensure_one()
        company = self.company_id
        assert company.fr_ctc_auth_method == 'authorization_code'
        siren = company.partner_id._get_siren(raise_if_none=True)

        authorize_url = 'https://api.superpdp.tech/oauth2/authorize'  # TODO
        client_id, _ = company._fr_ctc_credentials()
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = hashlib.sha256(code_verifier.encode('ascii')).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode('ascii').replace('=', '')

        oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, scope=[''])
        running_env = tools.config.get("running_env")
        optional_url_params = {}
        if self.accredited_platform == "superpdp":
            optional_url_params = {"superpdp_company_number": siren}
            if running_env in ("test", "dev"):
                optional_url_params['superpdp_company_number_scheme'] = 'sandbox'
            else:
                optional_url_params['superpdp_company_number_scheme'] = 'fr_siren'

        authorization_url, state_code = oauth.authorization_url(
            authorize_url,
            code_challenge=code_challenge,
            code_challenge_method='S256',
            **optional_url_params
        )
        logger.info("Redirecting to URL %s", authorization_url)
        action = {
            'type': 'ir.actions.act_url',
            'url': authorization_url,
            'target': 'new',
            # TODO find a way to close the wizard... it doesn't work for the moment
            #'params': {
            #    'next': {'type': 'ir.actions.act_window_close'}},
            }
        print('action=', action)
        self.write({'state_code': state_code, 'code_verifier': code_verifier})
        return action
