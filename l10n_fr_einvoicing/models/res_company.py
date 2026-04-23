# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools, Command
from odoo.exceptions import UserError
import logging
logger = logging.getLogger(__name__)
try:
    from pyfrctc import get_session, healthcheck
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_accredited_platform = fields.Selection([
        ('superpdp', 'SUPER PDP'),
        ], default='superpdp', string="Accredited Platform")

    def _fr_ctc_credentials(self):
        """Return (client_id, client_secret)"""
        self.ensure_one()
        platform = self.fr_accredited_platform
        if not platform:
            raise UserError(self.env._("No accredited platform selected for company '%s'.", self.display_name))

        client_id_key = f"fr_einvoicing_{platform}_client_id-{self.id}"
        client_id = tools.config.get(client_id_key)
        if not client_id:
            raise UserError(self.env._("Missing key '%s' in the Odoo server configuration file.", client_id_key))
        client_secret_key = f"fr_einvoicing_{platform}_client_secret-{self.id}"
        client_secret = tools.config.get(client_secret_key)
        if not client_secret:
            raise UserError(self.env._("Missing key '%s' in the Odoo server configuration file.", client_secret_key))
        return (client_id, client_secret)

    def _fr_ctc_test_api(self):
        self.ensure_one()
        client_id, client_secret = self._fr_ctc_credentials()
        platform = self.fr_accredited_platform
        platform_label = dict(self._fields['fr_accredited_platform']._description_selection(self.env))[platform]
        try:
            session = get_session(client_id, client_secret, platform=platform)
            healthcheck(session)
        except Exception as e:
            raise UserError(self.env._(
                "Odoo failed to connect to the API of %(platform)s. Error: %(error)s", error=e, platform=platform_label))
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": self.env._(
                    "Successful connection to the API of %(platform)s.",
                    platform=platform_label,
                ),
                "type": "success",
                "sticky": False,
            },
        }
        return action

    def _fr_ctc_get_session(self):
        self.ensure_one()
        client_id, client_secret = self._fr_ctc_credentials()
        platform = self.fr_accredited_platform
        try:
            session = get_session(client_id, client_secret, platform=platform)
        except Exception as e:
            platform_label = dict(self._fields['fr_accredited_platform']._description_selection(self.env))[self.fr_accredited_platform]
            raise UserError(self.env._(
                "Odoo failed to initiate a session with platform '%(platform)s'. Error: %(error)s", error=e, platform=platform_label))
        return session

    def _fr_ctc_is_vat_registered(self, raise_if_misconfigured=False):
        if not self.country_id and raise_if_misconfigured:
            raise UserError(self.env._("Country is not set on company '%s'.", company=self.display_name))
        if not self.is_france_country:
            return False
        cpartner = self.partner_id
        if not cpartner.fr_directory_entity_type:
            if raise_if_misconfigured:
                raise UserError(self.env._("Entity type is not set on partner '%s'. On that partner, click on the button 'Get/Update Directory Lines'.", cpartner.display_name))
        elif cpartner.fr_directory_entity_type == "public":
            if raise_if_misconfigured:
                raise UserError(self.env._("Partner '%s' is a public entity. This scenario is not supported.", cpartner.display_name))
        elif cpartner.fr_directory_entity_type == "private":
            if not cpartner._get_siren() and raise_if_misconfigured:
                raise UserError(self.env._("SIREN is not set on partner '%s'.", cpartner.display_name))
            return True
        return False
