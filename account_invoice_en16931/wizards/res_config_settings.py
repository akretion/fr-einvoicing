# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    en16931_default_pdf_invoice = fields.Selection(
        related="company_id.en16931_default_pdf_invoice", readonly=False
    )
    en16931_issuer = fields.Boolean(related="company_id.en16931_issuer", readonly=False)
    no_vat_taxes = fields.Boolean(related="company_id.no_vat_taxes")
    no_vat_taxes_vatex_id = fields.Many2one(
        related="company_id.no_vat_taxes_vatex_id", readonly=False
    )
    saxon_server_url = fields.Char(
        string="Specific Saxon Server URL", config_parameter="en16931.saxon_server_url"
    )

    def button_en16931_checks(self):
        """Run the EN16931 configuration checks of the current company on demand.

        _en16931_checks() raises a UserError listing what is wrong, so reaching
        the end means the company is properly configured.
        """
        self.ensure_one()
        self.company_id._en16931_checks()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("The EN16931 configuration of company %s is valid.")
                % self.company_id.display_name,
            },
        }
