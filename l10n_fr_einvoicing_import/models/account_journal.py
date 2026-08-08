# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    fr_directory_line_ids = fields.One2many(
        "fr.directory.line",
        "purchase_journal_id",
        string="Company Directory Lines",
        domain="[('partner_id', '=', company_partner_id), ('state', '=', 'active')]",
        help="If you select directory lines, the invoices sent to those directory "
        "lines will be imported in this purchase journal.",
    )
