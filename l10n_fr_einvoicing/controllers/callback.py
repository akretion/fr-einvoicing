# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools, Command, http
from odoo.exceptions import UserError
from odoo.http import request
import werkzeug
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # TODO remove
from requests_oauthlib import OAuth2Session
from odoo.addons.l10n_fr_einvoicing.models.res_company import TOKEN_URL
REDIRECT_URI = 'http://localhost:8069/fr_ctc_onboarding_callback'

import logging
logger = logging.getLogger(__name__)


class FrCtcOnboardingCallback(http.Controller):

    @http.route('/fr_ctc_onboarding_callback', type='http', auth='user')
    def callback(self, **kwargs):
        logger.info('Onboarding callback for FR CTC received with kwargs=%s', kwargs)
        state = kwargs.get('state')
        code = kwargs.get('code')
        wiz = request.env['fr.einvoicing.onboarding'].sudo().search([('state_code', '=', state), ('code_verifier', '!=', False)], limit=1)
        if not wiz:
            return  # TODO raise error
        company = wiz.company_id
        client_id, _ = company._fr_ctc_credentials()
        callback_url = f"http://localhost:8069/fr_ctc_onboarding_callback?code={code}&scope=&state={state}"
        print('callback_url=', callback_url)
        oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, scope=[''])
        token = oauth.fetch_token(
            TOKEN_URL,
            authorization_response=callback_url,
            code_verifier=wiz.code_verifier,
        )
        if token:
            logger.info('Updating refresh_token in DB for company %s', company.display_name)
            company.sudo().write({
                'fr_ctc_refresh_token': token['refresh_token'],
                'fr_ctc_access_token': token['access_token'],
                'fr_ctc_access_token_expiry': token['expires_at'],
                })
        # TODO it would be great to display something to the user, so that he can see that it was successful
