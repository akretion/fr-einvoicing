# Copyright 2026 Akretion France (https://www.akretion.com)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class ChorusFlow(models.Model):
    _inherit = "chorus.flow"

    syntax = fields.Selection(
        selection_add=[("pdf_factur-x", "Factur-X")],
        ondelete={"pdf_factur-x": "set null"},
    )

    @api.model
    def syntax_odoo2chorus(self):
        res = super().syntax_odoo2chorus()
        res["pdf_factur-x"] = "IN_DP_E2_CII_FACTURX"
        return res
