# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    # Odoo does not index this column. Resolving a partner's directory status
    # walks its invoices, so the directory import runs one such lookup per
    # company: without an index each one is a sequential scan of the whole
    # account_move table (877k rows on the FPV database, tens of seconds each),
    # and the import gets killed by the server time limit long before finishing.
    # Indexing it also benefits every partner-centric accounting screen.
    commercial_partner_id = fields.Many2one(index=True)
