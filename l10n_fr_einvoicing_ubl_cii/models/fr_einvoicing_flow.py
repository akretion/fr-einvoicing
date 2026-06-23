# Copyright 2026 Le Filament (https://le-filament.com/)

# For _match_partner function copied from l10n_fr_business_document_import:
# Copyright 2015-2021 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>

# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import base64
import logging

from stdnum.fr.siren import is_valid as siren_is_valid
from stdnum.fr.siret import is_valid as siret_is_valid

from odoo import models

logger = logging.getLogger(__name__)


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    def _generate_invoice_file(self):
        # Replace same function from l10n_fr_einvoicing to use account_edi_ubl_cii
        # iso OCA modules for generating invoice Factur-x / UBL
        self.ensure_one()
        # If PDF and XML have not yet been generated, we force generation
        if not self.move_id.invoice_pdf_report_id or not self.move_id.ubl_cii_xml_id:
            self.env["account.move.send"]._generate_and_send_invoices(self.move_id)
        if self.syntax == "Factur-X" and self.move_id.invoice_pdf_report_id:
            extension = "pdf"
            file_b64 = self.move_id.invoice_pdf_report_id.datas
        elif self.syntax == "UBL" and self.move_id.ubl_cii_xml_id:
            extension = "xml"
            file_b64 = self.move_id.ubl_cii_xml_id.datas
        if extension and file_b64:
            return file_b64, extension
        else:
            return super()._generate_invoice_file()

    def _import_supplier_invoice(self, result):
        # extends from l10n_fr_einvoicing
        invoice_id = super()._import_supplier_invoice(result)
        if not invoice_id:
            attachment = self.env["ir.attachment"].create(
                {
                    "name": self.filename,
                    "raw": base64.b64decode(self.file_bin),
                    "type": "binary",
                }
            )
            journal = self.env.ref(f"account.{self.env.company.id}_purchase")
            move_type = "in_invoice"
            invoice = self.env["account.move"].create(
                {
                    "journal_id": journal.id,
                    "move_type": move_type,
                    "fr_einvoicing_flow_id": self.id,
                }
            )
            invoice._extend_with_attachments(attachment, new=True)
            msg = "Invoice ID {invoice.id} successfully created"
            self.env["fr.einvoicing.log"]._info_log(result, msg)
        return invoice.id

    def _match_partner(self, partner_dict, chatter_msg):
        # Replace same method from l10n_fr_einvoicing to not depend
        # on base.document.import
        # Copy method from l10n_fr_business_document_import
        # Since here partner_dict contains only SIREN or SIRET
        if partner_dict.get("siret"):
            siret = partner_dict["siret"].replace(" ", "")
            if siret_is_valid(siret):
                partner = self.env["res.partner"].search(
                    [("siret", "=", siret)], limit=1
                )
                if partner:
                    return partner
                # fallback on siren search
                elif not partner_dict.get("siren"):
                    partner_dict["siren"] = siret[:9]
        if partner_dict.get("siren"):
            # when partner_dict comes from invoice2data, siren may be an int
            if isinstance(partner_dict["siren"], int):
                siren = str(partner_dict["siren"])
            else:
                siren = partner_dict["siren"].replace(" ", "")
            if siren_is_valid(siren):
                partner = self.env["res.partner"].search(
                    [
                        ("parent_id", "=", False),
                        ("siren", "=", siren),
                    ],
                    limit=1,
                )
                if partner:
                    return partner
        return False
