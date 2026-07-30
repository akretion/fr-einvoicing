# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import fields, models


class AccountInvoiceEn16931Generate(models.TransientModel):
    _inherit = "account.invoice.en16931.generate"

    invoice_format = fields.Selection(
        selection_add=[
            ("facturx_old_chorus", "Factur-X compatible with Chorus Pro portal")
        ],
        ondelete={"facturx_old_chorus": "set default"},
    )
