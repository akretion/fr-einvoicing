# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    def _import_supplier_invoice(self, result):
        invoice_id = super()._import_supplier_invoice(result)
        if not invoice_id:
            invoice_id = self.env["account.invoice.import"].create_invoice_webservice(
                self.file_bin, self.filename, self.company_id.id, self.identifier
            )
            # TODO find a way in account.invoice.import to avoid the
            # additionnal write below
            invoice = self.env["account.move"].browse(invoice_id)
            msg = f"Invoice ID {invoice_id} successfully created"
            self.env["fr.einvoicing.log"]._info_log(result, msg)
            invoice.write({"fr_einvoicing_flow_id": self.id})
        return invoice_id
