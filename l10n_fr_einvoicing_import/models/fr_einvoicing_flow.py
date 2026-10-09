# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import logging

from odoo import models

logger = logging.getLogger(__name__)


try:
    from facturx import get_data_dict_copy_for_logs
except (OSError, ImportError) as err:
    logger.debug("Cannot import facturx. Error details below.")
    logger.debug(err)


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    def _import_supplier_invoice(self, result):
        invoice, data_dict = super()._import_supplier_invoice(result)
        if not invoice:
            import_config = {
                "company": self.company_id,
                "origin": self.identifier,
                "invoice_extra_vals": {"fr_einvoicing_flow_id": self.id},
            }
            inv_import_obj = self.env["account.invoice.import"]
            data_dict = inv_import_obj.parse_invoice(
                base64.b64decode(self.file_bin), self.filename, import_config
            )
            self.sudo().write({"data_dict": data_dict})
            invoice = inv_import_obj.create_invoice(data_dict, import_config)
            msg = f"Invoice {invoice.display_name} ID {invoice.id} successfully created"
            self.env["fr.einvoicing.log"]._info_log(result, msg)
            data_dict_for_log = get_data_dict_copy_for_logs(data_dict)
        return invoice, data_dict_for_log
