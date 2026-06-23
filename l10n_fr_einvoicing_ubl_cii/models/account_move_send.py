# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64
import logging

from odoo import api, models

logger = logging.getLogger(__name__)


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_default_sending_method(self, move) -> str:
        # EXTENDS 'account'
        preferred_method = move.commercial_partner_id.with_company(
            move.company_id
        ).invoice_sending_method
        if not preferred_method and self._is_applicable_to_move("fr_pa", move):
            return "fr_pa"
        return super()._get_default_sending_method(move)

    # -------------------------------------------------------------------------
    # SENDING METHODS
    # -------------------------------------------------------------------------
    def _is_applicable_to_company(self, method, company):
        # EXTENDS 'account'
        if method == "fr_pa":
            return (
                company.partner_id.with_company(company.id).fr_directory_entity_type
                == "private"
            )
        else:
            return super()._is_applicable_to_company(method, company)

    def _is_applicable_to_move(self, method, move, **move_data):
        # EXTENDS 'account'
        if method == "fr_pa":
            if move_data:
                invoice_edi_format = move_data.get("invoice_edi_format", False)
            else:
                invoice_edi_format = "facturx"
            result = all(
                [
                    self._is_applicable_to_company(method, move.company_id),
                    move.fr_einvoicing_required,
                    invoice_edi_format in ["facturx", "ubl_21_fr"],
                ]
            )
            return result
        else:
            return super()._is_applicable_to_move(method, move, **move_data)

    def _call_web_service_after_invoice_pdf_render(self, invoices_data):
        # EXTENDS 'account'
        res = super()._call_web_service_after_invoice_pdf_render(invoices_data)

        for invoice, invoice_data in invoices_data.items():
            if "fr_pa" in invoice_data["sending_methods"]:
                if not self._is_applicable_to_move("fr_pa", invoice, **invoice_data):
                    continue
                flow = invoice.fr_einvoicing_flow_id
                if flow.state == "created":
                    vals = {}
                    if (
                        flow.syntax == "Factur-X"
                        and invoice_data["pdf_attachment_values"]
                    ):
                        vals = {
                            "state": "generated",
                            "file_bin": base64.b64encode(
                                invoice_data["pdf_attachment_values"]["raw"]
                            ),
                            "filename": invoice_data["pdf_attachment_values"]["name"],
                        }
                    elif (
                        flow.syntax in ["UBL", "CII"]
                        and invoice_data["ubl_cii_xml_attachment_values"]
                    ):
                        vals = {
                            "state": "generated",
                            "file_bin": base64.b64encode(
                                invoice_data["ubl_cii_xml_attachment_values"]["raw"]
                            ),
                            "filename": invoice_data["ubl_cii_xml_attachment_values"][
                                "name"
                            ],
                        }
                    flow.sudo().write(vals)
                if flow.state == "generated":
                    flow.send_button()
        return res
