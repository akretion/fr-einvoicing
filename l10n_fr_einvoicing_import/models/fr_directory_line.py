# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class FrDirectoryLine(models.Model):
    _inherit = "fr.directory.line"

    purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Force Purchase Journal",
        copy=False,
        domain="[('company_id', '=', belongs_to_company_id), "
        "('type', '=', 'purchase')]",
    )
    # Field "no_vat_deduction" has been designed for
    # "Association avec secteur lucratif":
    # to speedy-up the processing of their vendor bills, they can create 2 dir lines:
    # - one dedicated to the "secteur lucratif" where they can deduct VAT,
    # - another one dedicated to the "secteur non lucratif" on which they would enable
    #   the option 'no_vat_deduction'.
    no_vat_deduction = fields.Boolean(
        string="No VAT Deduction",
        copy=False,
        help="This option is designed for entities that can deduct VAT on some "
        "vendor bills but not all. If they decide to create a directory line "
        "dedicated to the vendor bills for which they cannot deduct VAT, "
        "they should enable this option on this specific directory line.",
    )
    # in the module l10n_fr_einvoicing, there is a field 'company_id'
    # which is a related of partner_id.company_id, used by the ir.rule
    # Here, we need a field which has a value only if the directory line
    # is attached to the partner of a company. The field name is not very good,
    # but I couldn't find a better one, sorry!
    belongs_to_company_id = fields.Many2one(
        "res.company", compute="_compute_belongs_to_company_id", store=True
    )

    @api.depends("partner_id")
    def _compute_belongs_to_company_id(self):
        company_sr = self.env["res.company"].search_read(
            [("partner_id", "!=", False)], ["partner_id"]
        )
        partner_id2company_id = {c["partner_id"][0]: c["id"] for c in company_sr}
        for line in self:
            line.belongs_to_company_id = partner_id2company_id.get(line.partner_id.id)
