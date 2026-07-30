# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import base64
from io import BytesIO

from unidecode import unidecode

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    fr_einvoicing_internal = fields.Boolean(
        string="Internal Invoice/Refund", copy=False, tracking=True
    )

    def _prepare_en16931_dict(self, speedy, pdf_invoice_bin=False):
        vals = super()._prepare_en16931_dict(speedy, pdf_invoice_bin=pdf_invoice_bin)
        chorus = (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_partner_entity_type == "public"
        )
        # TODO improve filtering
        if self.company_id.is_france_country:
            # SELLER
            seller_siren = self.company_id.partner_id._get_siren()
            if seller_siren:
                vals.update(
                    {
                        "BT-30": seller_siren,
                        "BT-30-1": "0002",
                    }
                )
            if chorus:
                seller_siret = self.company_id.partner_id._get_siret()
                if seller_siret:
                    vals["BT-29"]["0009"] = seller_siret
                    if self.env.context.get("chorus_old_xml_syntax"):
                        vals.update(
                            {
                                "BT-30": seller_siret,
                                "BT-30-1": "0009",
                            }
                        )
                        if self.payment_state == "paid":
                            vals["BT-23"] = "A2"
                        else:
                            vals["BT-23"] = "A1"

            # BUYER
            buyer_siren = self.partner_id._get_siren()
            if buyer_siren:
                vals.update(
                    {
                        "BT-47": buyer_siren,
                        "BT-47-1": "0002",
                    }
                )
            if chorus:
                buyer_siret = self.commercial_partner_id._get_siret()
                if buyer_siret:
                    vals["BT-46"]["0009"] = buyer_siret
                    if self.env.context.get("chorus_old_xml_syntax"):
                        vals.update(
                            {
                                "BT-47": buyer_siret,
                                "BT-47-1": "0009",
                            }
                        )
                if (
                    self.fr_directory_line_id.type == "routing_code"
                    and self.fr_directory_line_id.routing_code
                ):
                    vals["BT-46"]["0240"] = self.fr_directory_line_id.routing_code
                    if self.env.context.get("chorus_old_xml_syntax"):
                        vals["BT-10"] = self.fr_directory_line_id.routing_code
                    vals["BT-56-0"] = (
                        self.fr_directory_line_id.routing_code_name
                    )  # UBL ?
            if (
                self.commercial_partner_id.country_id
                and not self.commercial_partner_id.is_france_country
            ):
                if self.commercial_partner_id.country_id.id in speedy["eu_country_ids"]:
                    if self.commercial_partner_id.vat:
                        vals["BT-46"]["0223"] = self.commercial_partner_id.vat
                else:
                    partner_name = unidecode(
                        self.commercial_partner_id.name.replace(" ", "").upper()
                    )
                    country_code = self.commercial_partner_id.country_id.code
                    out_ue_id = f"{country_code}{partner_name[:16]}"
                    vals["BT-46"]["0227"] = out_ue_id

        return vals

    def _prepare_bg1(self, speedy):
        res = super()._prepare_bg1(speedy)
        # TODO translate ? fields ?
        res += [
            {
                "BT-21": "PMT",
                "BT-22": "Indemnité forfaitaire pour frais de recouvrement "
                "en cas de retard de paiement : 40 €.",
            },
            {
                "BT-21": "PMD",
                "BT-22": "Tout retard de paiement engendre une pénalité "
                "exigible à compter de la date d'échéance, "
                "calculée sur la base de trois fois le taux d'intérêt légal.",
            },
            {
                "BT-21": "AAB",
                "BT-22": "Les réglements reçus avant la date d'échéance "
                "ne donneront pas lieu à escompte.",
            },
        ]
        if (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_partner_entity_type == "public"
        ):
            res.append({"BT-21": "ADN", "BT-22": "B2G"})

        if self.fr_einvoicing_internal:
            res.append({"BT-21": "BAR", "BT-22": "ARCHIVEONLY"})
        return res

    def _get_en16931_invoice_bin(self, invoice_format, b64=False):
        self.ensure_one()
        if invoice_format == "facturx_old_chorus":
            pdf_invoice_bin = self._get_pdf_invoice_bin()
            with BytesIO(pdf_invoice_bin) as pdf_bytesio:
                self.with_context(
                    chorus_old_xml_syntax=True
                )._regular_pdf_invoice_to_en16931_pdf_invoice(
                    pdf_bytesio, invoice_format
                )
                pdf_bytesio.seek(0)
                invoice_bin = pdf_bytesio.read()
            if b64:
                invoice_bin = base64.encodebytes(invoice_bin)
            return invoice_bin
        return super()._get_en16931_invoice_bin(invoice_format, b64=b64)
