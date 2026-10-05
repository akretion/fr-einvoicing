# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _en16931_partner_data(self, speedy, country_required=True):
        self.ensure_one()
        vals = super()._en16931_partner_data(speedy, country_required=country_required)
        if speedy["company_is_france_country"]:
            siren = self.commercial_partner_id._get_siren()
            if siren:
                vals["legal_identifier"] = siren
                vals["legal_identifier_schemeid"] = "0002"
        return vals
