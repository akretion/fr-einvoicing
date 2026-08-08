# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from odoo import fields, models, tools

logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # Odoo does not index this column. Resolving a partner's directory status
    # walks its invoices, so the directory import runs one such lookup per
    # company: without an index each one is a sequential scan of the whole
    # account_move table (877k rows on the FPV database, tens of seconds each),
    # and the import gets killed by the server time limit long before finishing.
    # Indexing it also benefits every partner-centric accounting screen.
    commercial_partner_id = fields.Many2one(index=True)

    def init(self):
        # `index=True` above is enough on a clean database, but the field is
        # inherited: any module redefining it without `index` would drop the
        # index again. Creating it here as well makes the module self-healing —
        # `create_index` is a no-op when the index already exists.
        res = super().init()
        tools.create_index(
            self._cr,
            "account_move_commercial_partner_id_index",
            self._table,
            ["commercial_partner_id"],
        )
        logger.info(
            "account_move.commercial_partner_id index ensured "
            "(directory import performance)"
        )
        return res
