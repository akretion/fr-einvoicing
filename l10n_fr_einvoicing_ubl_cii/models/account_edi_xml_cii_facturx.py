# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models

from odoo.addons.account_edi_ubl_cii.models.account_edi_xml_cii_facturx import (
    CII_NAMESPACES,
)


class AccountEdiXmlCII(models.AbstractModel):
    _inherit = "account.edi.xml.cii"

    def _export_invoice_vals(self, invoice):
        # Extend `account_edi_xml_cii` to use SIREN as identifier iso siret
        template_vals = super()._export_invoice_vals(invoice)
        seller_siren = invoice.company_id.partner_id._get_siren()
        buyer_siren = invoice.commercial_partner_id._get_siren()
        template_vals.update(
            {
                "seller_specified_legal_organization": seller_siren,
                "buyer_specified_legal_organization": buyer_siren,
            }
        )
        return template_vals

    def _import_pdp_retrieve_partner_enpoint(self, tree, role):
        peppol_vals = {}
        partner_nodes = tree.xpath(
            f".//ram:{role}/ram:URIUniversalCommunication/"
            "ram:URIID[string-length(text()) > 8]",
            namespaces=CII_NAMESPACES,
        )
        if partner_nodes:
            peppol_vals["peppol_endpoint"] = partner_nodes[0].text
            peppol_vals["peppol_eas"] = partner_nodes[0].attrib.get("schemeID")
        return peppol_vals

    def _import_retrieve_partner_vals(self, tree, role):
        vals = super()._import_retrieve_partner_vals(tree, role)
        vals.update(self._import_pdp_retrieve_partner_enpoint(tree, role))
        return vals

    def _import_fill_invoice(self, invoice, tree, qty_factor):
        res = super()._import_fill_invoice(invoice, tree, qty_factor)
        role = (
            "SellerTradeParty"
            if invoice.journal_id.type == "purchase"
            else "BuyerTradeParty"
        )
        partner_vals = self._import_pdp_retrieve_partner_enpoint(tree, role)

        if partner_vals["peppol_endpoint"] and partner_vals["peppol_eas"] == "0225":
            invoice.fr_directory_line_identifier = partner_vals["peppol_endpoint"]
        return res
