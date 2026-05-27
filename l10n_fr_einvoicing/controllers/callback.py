# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools, Command, http
from odoo.exceptions import UserError
from odoo.http import request
import werkzeug
from requests_oauthlib import OAuth2Session
from odoo.addons.l10n_fr_einvoicing.models.res_company import TOKEN_URL
from odoo.addons.l10n_fr_einvoicing.models.res_company import CALLBACK_URL

import logging
logger = logging.getLogger(__name__)


class FrCtcOnboardingCallback(http.Controller):

    @http.route(CALLBACK_URL, type='http', auth='user')
    def callback(self, **kwargs):
        logger.info('Onboarding callback for FR CTC received with kwargs=%s', kwargs)
        state = kwargs.get('state')
        code = kwargs.get('code')
        code_verifier = request.session.get('code_verifier')
        company = request.env["res.company"].browse(request.session.get("company_id"))
        client_id, _ = company._fr_ctc_credentials()
        base_url = company.fr_ctc_redirect_uri()
        callback_url = f"{base_url}?code={code}&scope=&state={state}"
        print('callback_url=', callback_url)
        oauth = OAuth2Session(client_id, redirect_uri=base_url, scope=[''])
        token = oauth.fetch_token(
            TOKEN_URL,
            authorization_response=callback_url,
            code_verifier=code_verifier,
        )
        if token:
            logger.info('Updating refresh_token in DB for company %s', company.display_name)
            company._fr_ctc_write_token(token)
        return request.render('l10n_fr_einvoicing.onboarding_success')
