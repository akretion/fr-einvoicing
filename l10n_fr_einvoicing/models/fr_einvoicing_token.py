# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class FrEinvoicingToken(models.Model):
    _name = "fr.einvoicing.token"
    _description = "FR eInvoicing Token"
    # We don't store tokens on res.company to avoid errors
    # "could not serialize access due to concurrent update"
    # due to the fact that we also write on the field
    # fr_ctc_last_flow_import_datetime on res.company

    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True
    )
    refresh_token = fields.Char(readonly=True)
    access_token = fields.Char(readonly=True)
    expires_at = fields.Float(readonly=True)

    _unique_company = models.Constraint(
        "unique(company_id)",
        "This company already exists in the token table",
    )
