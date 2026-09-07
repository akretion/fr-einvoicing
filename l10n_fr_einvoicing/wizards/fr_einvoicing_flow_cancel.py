# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class FrEinvoicingFlowCancel(models.TransientModel):
    _name = "fr.einvoicing.flow.cancel"
    _description = "Cancel an eInvoicing Flow"

    flow_id = fields.Many2one(
        "fr.einvoicing.flow", string="Flow to Cancel", required=True, readonly=True
    )
    cancel_comment = fields.Text(string="Justification", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "fr.einvoicing.flow":
            res["flow_id"] = self.env.context.get("active_id")
        return res

    def cancel_button(self):
        self.ensure_one()
        if not self.cancel_comment:
            raise UserError(
                self.env._("You must write a justification to cancel a flow.")
            )
        self.flow_id.sudo().write(
            {
                "state": "cancel",
                "cancel_comment": self.cancel_comment,
            }
        )
