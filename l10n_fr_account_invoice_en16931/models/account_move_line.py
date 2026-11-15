# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from odoo import models

from .account_move import NOT_REGISTERED_VATEX_PREFIX


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _check_en16931(self, speedy):
        # This inherit modifies the VAT exemption reason code for invoice lines
        # For modification in BG-23 is made by the inherit of _prepare_bg23()
        vat_dict, non_vat_taxes = super()._check_en16931(speedy)
        if (
            vat_dict.get("vatex_code")
            and vat_dict["vatex_code"].startswith(NOT_REGISTERED_VATEX_PREFIX)
            and speedy["company_is_france_country"]
        ):
            if self.env.context.get("fr_ereporting"):
                vat_dict["vatex_code"] = "NR"
            else:
                vat_dict["vatex_code"] = None
        return vat_dict, non_vat_taxes
