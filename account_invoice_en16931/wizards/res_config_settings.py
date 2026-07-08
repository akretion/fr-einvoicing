# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    no_vat_taxes = fields.Boolean(related="company_id.no_vat_taxes")
    no_vat_taxes_vatex_id = fields.Many2one(
        related="company_id.no_vat_taxes_vatex_id", readonly=False
    )
    saxon_server_url = fields.Char(
        string="Specific Saxon Server URL", config_parameter="en16931.saxon_server_url"
    )
    saxon_server_codedb_dir = fields.Char(
        string="Saxon Server CodeDB Directory",
        config_parameter="en16931.saxon_server_codedb_dir",
    )
