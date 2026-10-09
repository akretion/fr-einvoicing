# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, models

logger = logging.getLogger(__name__)


class AccountInvoiceImport(models.TransientModel):
    _inherit = "account.invoice.import"

    @api.model
    def _prepare_create_invoice_vals(self, parsed_inv, import_config):
        company_fr_dir_line = False
        company_dict = self._get_company_dict(parsed_inv, import_config)
        if company_dict.get("einvoicing_addr"):
            company_fr_dir_line_ident = company_dict["einvoicing_addr"]
            company = import_config["company"]
            company_fr_dir_line = self.env["fr.directory.line"].search(
                [
                    ("partner_id", "=", company.partner_id.id),
                    ("identifier", "=", company_fr_dir_line_ident),
                ],
                limit=1,
            )
            # if company_fr_dir_line and company_fr_dir_line.no_vat_deduction:
            # TODO restore feature no_vat_deduction
            # self._pre_process_parsed_inv_taxes(
            #    parsed_inv, company, force_no_vat_deduction=True
            # )
        vals = super()._prepare_create_invoice_vals(parsed_inv, import_config)
        partner_dict = self._get_partner_dict(parsed_inv, import_config)
        if partner_dict.get("einvoicing_addr"):
            vals["fr_directory_line_identifier"] = partner_dict["einvoicing_addr"]
        if company_fr_dir_line:
            vals["company_fr_directory_line_id"] = company_fr_dir_line.id
            if company_fr_dir_line.state != "active":
                msg = (
                    f"Company directory line state is {company_fr_dir_line.state} "
                    "(should be active)"
                )
                self._warning_log(import_config, msg)
            if company_fr_dir_line.purchase_journal_id:
                msg = (
                    f"Import import forced to journal "
                    f"{company_fr_dir_line.purchase_journal_id.display_name} because "
                    "the destination einvoice address is configured on it."
                )
                vals["journal_id"] = company_fr_dir_line.purchase_journal_id.id
        if parsed_inv.get("BT-23") and company_dict.get("country_code") == "FR":
            vals["business_process_type"] = f"fr_{parsed_inv['BT-23']}"
        return vals
