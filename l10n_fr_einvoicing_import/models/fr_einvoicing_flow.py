# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models, Command
# import logging
# from pprint import pprint
# logger = logging.getLogger(__name__)


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    def _in_process_single(self):
        res = super()._in_process_single()
        if self.state == "downloaded" and self.type == "SupplierInvoice":
            invoice_id = self.env['account.invoice.import'].create_invoice_webservice(
                self.file_bin, self.filename, self.company_id.id, self.identifier)
            if invoice_id:
                self.sudo().write({
                    'state': 'done',
                    'move_ids': [Command.link(invoice_id)],
                    })
        return res
