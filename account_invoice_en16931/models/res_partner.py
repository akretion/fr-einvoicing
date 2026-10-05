# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _en16931_partner_data(self, speedy, country_required=True):
        # country_required correspond in fact to postal_address_required
        # country is always required in a postal address block.
        # Postal address is only required for seller, buyer and fiscal representative
        # (not for agents, payee, invoicee..)
        self.ensure_one()
        country = self.country_id or self.commercial_partner_id.country_id
        if country_required and not country:
            raise UserError(
                _(
                    "Country is not set on partner '%s'. "
                    "Country is required in EN16931.",
                    self.display_name,
                )
            )
        vat = self.commercial_partner_id.vat
        vals = {
            "name": self.commercial_partner_id.name,
            "addr_l1": self.street,
            "addr_l2": self.street2,
            "postcode": self.zip,
            "city": self.city,
            "country_code": country and country.code or None,
            "vat_identifier": vat if vat != "/" else None,
            "identifiers": {},  # to make it easier to inherit
        }
        if self.state_id:
            vals["country_subdivision"] = self.state_id.name
        if hasattr(self, "street3") and self.street3:
            vals["addr_l3"] = self.street3
        if self.phone or self.mobile or self.email:
            vals["contacts"] = [
                {
                    "name": self.parent_id and self.name or None,
                    "phone": self.phone or self.mobile,
                    "email": self.email,
                }
            ]
        return vals
