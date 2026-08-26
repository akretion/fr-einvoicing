# Copyright 2026 Akretion France (https://www.akretion.com)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_chorus_invoice_format = fields.Selection(
        selection_add=[("pdf_factur-x", "Factur-X (new module)")],
        ondelete={"pdf_factur-x": "set null"},
    )
