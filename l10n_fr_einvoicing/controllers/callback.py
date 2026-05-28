# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import http
# from odoo.exceptions import UserError
from odoo.http import request
# import werkzeug
from odoo.addons.l10n_fr_einvoicing.models.res_company import CALLBACK_PATH

import logging
logger = logging.getLogger(__name__)

try:
    from pyfrctc import authorization_code_first_token
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class FrCtcOnboardingCallback(http.Controller):

    @http.route(CALLBACK_PATH, type='http', auth='user')
    def callback(self, **kwargs):
        logger.info('Onboarding callback for FR CTC received with kwargs=%s', kwargs)
        state = kwargs.get('state')
        callback_code = kwargs.get('code')
        code_verifier = request.session.get('fr_ctc_code_verifier')
        state_initial = request.session.get('fr_ctc_state')
        if state != state_initial:
            logger.error(f"The initial state ({state_initial}) is different from "
            f"the state received by the callback({state}). This should never happen.")
            return request.render('l10n_fr_einvoicing.onboarding_failure')
        try:
            company = request.env["res.company"].browse(request.session.get("fr_ctc_company_id"))
            client_id, _ = company._fr_ctc_credentials()
            redirect_uri = company._fr_ctc_redirect_uri()
            authorization_code_first_token(company.fr_ctc_accredited_platform, client_id, code_verifier, state, callback_code, redirect_uri, company._fr_ctc_write_token)
        except Exception as e:
            logger.error(f"Odoo failed to get the first refresh token. Error: {e}")
            return request.render('l10n_fr_einvoicing.onboarding_failure')
        return request.render('l10n_fr_einvoicing.onboarding_success')
