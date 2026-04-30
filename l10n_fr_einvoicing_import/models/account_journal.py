# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models
from odoo.exceptions import UserError

import logging
logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def fr_einvoicing_run_import(self):
        self.ensure_one()
        logger.info('Start to import in_invoice/refunds from AP triggered by button')
        flows = self.company_id.fr_einvoicing_run_import()
        if flows:
            msg = self.env._("%d flows imported from AP.", len(flows))
        else:
            msg = self.env._("AP doesn't have new flows.")
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',  # warning/danger
                'title': self.env._("Sync with AP"),
                'message': msg,
                }}
        return action
#        next_action = self.env["ir.actions.actions"]._for_xml_id(
#            "account.action_move_in_invoice_type"
#        )
#        if len(invoice_ids) > 1:
#            next_action["domain"] = [("id", "in", invoice_ids)]
#            msg = self.env._("%s new vendor bills/refunds imported.", len(invoice_ids))
#        elif len(invoice_ids) == 1:
#            msg = self.env._("1 new vendor bill/refund imported.")
#            views = [view for view in next_action["views"] if view[1] == "form"]
#            next_action.update(
#                {
#                    "view_mode": "form,list,kanban",
#                    "view_id": False,
#                    "views": views,
#                    "res_id": invoice_ids[0],
#                }
#            )
#        else:
#            msg = self.env._("No new vendor bill/refund.")
#            next_action = None
#        action = {
#            "type": "ir.actions.client",
#            "tag": "display_notification",
#            "params": {
#                "type": "success",
#                "title": self.env._("Import Vendor Bills from AP"),
#                "message": msg,
#                "next": next_action,
#            },
#        }
#        return action
