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
        if parsed_inv.get("company", {}).get("einvoice_address"):
            company_fr_dir_line_ident = parsed_inv["company"]["einvoice_address"]
            company = import_config["company"]
            company_fr_dir_line = self.env["fr.directory.line"].search(
                [
                    ("partner_id", "=", company.partner_id.id),
                    ("identifier", "=", company_fr_dir_line_ident),
                ],
                limit=1,
            )
            if company_fr_dir_line and company_fr_dir_line.no_vat_deduction:
                self._pre_process_parsed_inv_taxes(
                    parsed_inv, company, force_no_vat_deduction=True
                )
        vals = super()._prepare_create_invoice_vals(parsed_inv, import_config)
        if parsed_inv.get("partner", {}).get("einvoice_address"):
            vals["fr_directory_line_identifier"] = parsed_inv["partner"][
                "einvoice_address"
            ]
        if company_fr_dir_line:
            vals["company_fr_directory_line_id"] = company_fr_dir_line.id
            if company_fr_dir_line.state != "active":
                logger.warning(
                    f"Company directory line state is {company_fr_dir_line.state} "
                    "(should be active)"
                )
            if company_fr_dir_line.purchase_journal_id:
                logger.info(
                    "Import import forced to journal %s because the destination "
                    "einvoice address is configured on it.",
                    company_fr_dir_line.purchase_journal_id.display_name,
                )
                vals["journal_id"] = company_fr_dir_line.purchase_journal_id.id
        return vals
