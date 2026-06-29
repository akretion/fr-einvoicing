# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    company_partner_id = fields.Many2one(
        related="company_id.partner_id", string="Company Partner"
    )
    fr_directory_company_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type",
        string="Company Directory Entity Type",
    )
    company_fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_company_fr_directory_line_id",
        store=True,
        precompute=True,
        readonly=False,
        ondelete="restrict",
        string="Company Directory Line",
        domain="[('partner_id', '=', company_partner_id), ('state', '=', 'active')]",
    )

    @api.depends("company_id")
    def _compute_company_fr_directory_line_id(self):
        for purchase in self:
            company_fr_directory_line_id = False
            if purchase.company_id and purchase.company_id._fr_ctc_is_vat_registered():
                comp_partner = purchase.company_id.partner_id
                if comp_partner.default_fr_directory_line_id:
                    company_fr_directory_line_id = (
                        comp_partner.default_fr_directory_line_id
                    )
                elif comp_partner.fr_directory_line_ids:
                    company_fr_directory_line_id = (
                        comp_partner.fr_directory_line_ids.filtered(
                            lambda x: x.state == "active"
                        )[:1]
                    )
            purchase.company_fr_directory_line_id = company_fr_directory_line_id
