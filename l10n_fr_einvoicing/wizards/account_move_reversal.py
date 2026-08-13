# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountMoveReversal(models.TransientModel):
    _inherit = "account.move.reversal"

    fr_einvoicing_internal = fields.Boolean(string="Internal Refund")
    show_fr_einvoicing_internal = fields.Boolean()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        assert self.env.context.get("active_model") == "account.move"
        amo = self.env["account.move"]
        moves = amo.browse(self.env.context["active_ids"])
        if (
            len(moves) == 1
            and moves.is_sale_document()
            and not moves.reversal_move_ids
            and moves.fr_einvoicing_event_ids.filtered(
                lambda x: x.status in ("rejected", "refused")
            )
        ):
            res["fr_einvoicing_internal"] = True
            res["show_fr_einvoicing_internal"] = True
        return res

    def _prepare_default_reversal(self, move):
        vals = super()._prepare_default_reversal(move)
        if len(self.move_ids) == 1 and self.fr_einvoicing_internal:
            vals["fr_einvoicing_internal"] = True
        elif (
            len(self.move_ids) > 1
            and move.is_sale_document()
            and not move.reversal_move_ids
            and move.fr_einvoicing_event_ids.filtered(
                lambda x: x.status in ("rejected", "refused")
            )
        ):
            vals["fr_einvoicing_internal"] = True
        return vals
