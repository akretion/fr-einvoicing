# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class ResCurrency(models.Model):
    _inherit = "res.currency"

    def _en16931_format(self, amount):
        self.ensure_one()
        fmt = f"%.{self.decimal_places}f"
        amount_str = fmt % amount
        return amount_str
