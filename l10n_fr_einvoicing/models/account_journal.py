# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def fr_einvoicing_run_import(self):
        self.ensure_one()
        flows = self.company_id.fr_ctc_run_import()
        if flows:
            msg = self.env._("%d flows imported from AP.", len(flows))
        else:
            msg = self.env._("AP doesn't have new flows.")
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Sync with AP"),
                "message": msg,
            },
        }
        return action
