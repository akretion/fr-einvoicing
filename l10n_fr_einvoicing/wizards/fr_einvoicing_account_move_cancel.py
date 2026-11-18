# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Benoit Guillot <benoit.guillot@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import api, fields, models


class FrEinvoicingAccountMoveCancel(models.TransientModel):
    _name = "fr.einvoicing.account.move.cancel"
    _description = "Confirm generation of rejection event upon vendor bill cancellation"

    move_id = fields.Many2one(
        "account.move", readonly=True, string="Vendor Bill/Refund", required=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        assert self._context.get("active_model") == "account.move"
        move = self.env["account.move"].browse(self._context.get("active_id"))
        assert move.is_purchase_document()
        res["move_id"] = move.id
        return res

    def cancel_with_event(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_fr_einvoicing.fr_einvoicing_event_manual_action"
        )
        action["context"] = {
            "active_model": self._context.get("active_model"),
            "active_id": self.move_id.id,
            "active_ids": [self.move_id.id],
            "default_status_purchase": "refused",
            "default_status_readonly": True,
        }
        return action

    def cancel_without_event(self):
        self.move_id.with_context(by_pass_refusal_event_wizard=True).button_cancel()
