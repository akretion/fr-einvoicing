# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models

# AFNOR XP Z12-014 v1.3, Annexe A (normative), §3.2.43 "Cas n°44 : Transactions
# avec des entités établies dans les DROM / COM / TAAF" (rule BR-FR-MAP-14):
# "Dans le flux 1, [...] seul le code Pays FR doit être utilisé" for the three
# DROM in the France VAT group (Métropole, Guadeloupe, Martinique, Réunion).
# Guyane and Mayotte are explicitly excluded from that group and must never
# be sent as FR; the norm has them corrected from the postal code (973 for
# Guyane, 976 for Mayotte) when they wrongly are. Every other DROM/COM/TAAF
# (Nouvelle-Calédonie, Polynésie française, Saint-Barthélemy, Saint-Martin,
# Saint-Pierre-et-Miquelon, Wallis-et-Futuna, TAAF) is out of flux 1's scope
# and is left untouched.
FRANCE_VAT_GROUP_MAPPED_TO_FR = {"GP", "MQ", "RE"}
GUYANE_MAYOTTE_ZIP_PREFIX_TO_CODE = {"973": "GF", "976": "YT"}


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _en16931_partner_data(self, speedy, country_required=True):
        self.ensure_one()
        vals = super()._en16931_partner_data(speedy, country_required=country_required)
        # This one value feeds BT-40/BT-55/BT-80 in both the Factur-X (CII)
        # and UBL exports, which both build on the same vals dict.
        code = vals.get("country_code")
        if code in FRANCE_VAT_GROUP_MAPPED_TO_FR:
            vals["country_code"] = "FR"
        elif code == "FR" and vals.get("postcode"):
            overseas_code = GUYANE_MAYOTTE_ZIP_PREFIX_TO_CODE.get(vals["postcode"][:3])
            if overseas_code:
                vals["country_code"] = overseas_code
        if speedy["company_is_france_country"]:
            siren = self.commercial_partner_id._get_siren()
            if siren:
                vals["legal_identifier"] = siren
                vals["legal_identifier_schemeid"] = "0002"
            siret = self.commercial_partner_id._get_siret()
            if siret:
                vals['identifiers']['0009'] = siret
        return vals
