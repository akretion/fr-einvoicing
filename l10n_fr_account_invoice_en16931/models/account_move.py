# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import base64
from io import BytesIO

from unidecode import unidecode

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class AccountMove(models.Model):
    _inherit = "account.move"

    fr_einvoicing_internal = fields.Boolean(
        string="Internal Invoice/Refund", copy=False, tracking=True
    )
    # We have a specific strategy for the field 'business_process_type'
    # to correctly handle the fact that the value is different for an invoice already
    # paid or an unpaid invoice. We don't want a computed field that depends
    # on 'payment_state', because we don't want to switch from B1 to B2 (for example)
    # once the invoice is paid. And we want the user to be able to set a value
    # manually, for example S3/S5/S6. So the strategy is the following:
    # 1. the user can set the value manually when the invoice is draft,
    # 2. if no value has been set, odoo auto-computes a value,
    # 3. if no value has been set and the invoice is posted, odoo will write
    # the auto-computed value on the first generation of an EN16931 invoice.
    # That way, after confirmation of a customer invoice that is already paid,
    # if the user first reconciles with the payment and then sends the invoice,
    # the value will be B2 (for example) and not B1.
    # For an unpaid customer invoice, when the user confirms and then sends
    # the invoice, odoo will auto-set the value to B1, and this value
    # will not change when the payment is later received and reconciled.
    business_process_type = fields.Selection(
        selection_add=[
            ("fr_B1", "B1. Dépôt d'une facture de biens"),
            ("fr_S1", "S1. Dépôt d'une facture de prestation de service"),
            (
                "fr_M1",
                "M1. Dépôt d'une facture mixte (livraison de biens et services "
                "qui ne sont pas accessoires l'une de l'autre)",
            ),
            ("fr_B2", "B2. Dépôt d'une facture de biens déjà payée"),
            ("fr_S2", "S2. Dépôt d'une facture de prestation de service déjà payée"),
            ("fr_M2", "M2. Dépôt d'une facture mixte déjà payée"),
            (
                "fr_S3",
                "S3. Dépôt d'une demande de paiement de sous-traitance avec "
                "paiement direct (B2G)",
            ),
            ("fr_B4", "B4. Dépôt d'une facture définitive (après acompte) de biens"),
            ("fr_S4", "S4. Dépôt d'une facture définitive (après acompte) de services"),
            ("fr_M4", "M4. Dépôt d'une facture définitive (après acompte) mixte"),
            (
                "fr_S5",
                "S5. Dépôt par un sous-traitant d'une facture de prestation de "
                "service",
            ),
            (
                "fr_S6",
                "S6. Dépôt par un cotraitant d'une facture de prestation de service",
            ),
            (
                "fr_B7",
                "B7. Dépôt d'une facture de biens ayant fait l'objet d'un e-reporting "
                "(TVA déjà collectée)",
            ),
            (
                "fr_S7",
                "S7. Dépôt d'une facture de prestation de service ayant fait l'objet "
                "d'un e-reporting (TVA déjà collectée)",
            ),
            ("fr_B8", "B8. Dépôt d'une facture multi-vendeurs de biens"),
            ("fr_S8", "S8. Dépôt d'une facture multi-vendeurs de services"),
            (
                "fr_M8",
                "M8. Dépôt d'une facture multi-vendeurs mixte, contenant des "
                "factures unitaires qui ne sont pas toutes Sx ou Bx",
            ),
            ("fr_B9", "B9. Dépôt d'une facture bidirectionnelle de biens"),
            ("fr_S9", "S9. Dépôt d'une facture bidirectionnelle de services"),
            ("fr_M9", "M9. Dépôt d'une facture bidirectionnelle mixte"),
        ],
        ondelete={
            "fr_B1": "set null",
            "fr_S1": "set null",
            "fr_M1": "set null",
            "fr_B2": "set null",
            "fr_S2": "set null",
            "fr_M2": "set null",
            "fr_S3": "set null",
            "fr_B4": "set null",
            "fr_S4": "set null",
            "fr_M4": "set null",
            "fr_S5": "set null",
            "fr_S6": "set null",
            "fr_B7": "set null",
            "fr_S7": "set null",
            "fr_B8": "set null",
            "fr_S8": "set null",
            "fr_M8": "set null",
            "fr_B9": "set null",
            "fr_S9": "set null",
            "fr_M9": "set null",
        },
    )

    @api.constrains("business_process_type", "invoice_type_code")
    def _check_business_process_type(self):
        for move in self:
            if move.is_sale_document():
                # G1.60
                if move.business_process_type in (
                    "fr_B4",
                    "fr_S4",
                    "fr_M4",
                ) and move.invoice_type_code in ("386", "500", "503"):
                    raise ValidationError(
                        _(
                            "When Business Process Type is B4, S4 or M4, "
                            "Invoice Type Code cannot be 386, 500 or 503 "
                            "(rule G1.60)."
                        )
                    )
                # BR-FR-CPRO-23 and BR-FR-CPRO-24 are checked in the
                # module l10n_fr_einvoicing

    def _prepare_bt23(self, speedy):
        self.ensure_one()
        bt23 = super()._prepare_bt23(speedy)
        if bt23:
            return bt23
        if not self.company_id.is_france_country:
            return None
        # OCA module intrastat_base
        has_is_accessory_cost = hasattr(
            self.env["product.template"], "is_accessory_cost"
        )
        # sale module
        has_is_downpayment = hasattr(self.env["account.move.line"], "is_downpayment")
        if has_is_downpayment:
            qty_prec = self.env["decimal.precision"].precision_get(
                "Product Unit of Measure"
            )
        line_types = []
        has_deduct_down_payment = False
        for line in self.invoice_line_ids:
            if line.display_type == "product":
                # If an invoice line has no product, we consider it is a service
                ptype = line.product_id and line.product_id.type or "service"
                is_accessory_cost = (
                    has_is_accessory_cost and line.product_id.is_accessory_cost or False
                )
                if (
                    has_is_downpayment
                    and line.is_downpayment
                    and float_compare(line.quantity, 0, precision_digits=qty_prec) < 0
                ):
                    has_deduct_down_payment = True
                    continue
                line_types.append((ptype, is_accessory_cost))
        service_only = all(
            [ptype == "service" for (ptype, is_accessory_cost) in line_types]
        )
        at_least_one_product = any(
            [ptype in ("consu", "product") for (ptype, is_accessory_cost) in line_types]
        )
        all_products_or_accessory_costs = all(
            [
                ptype in ("consu", "product") or is_accessory_cost
                for (ptype, is_accessory_cost) in line_types
            ]
        )
        paid = self.payment_state == "paid"
        if service_only:
            if has_deduct_down_payment:
                business_process_type = "fr_S4"
            else:
                business_process_type = paid and "fr_S2" or "fr_S1"
        elif at_least_one_product and all_products_or_accessory_costs:
            if has_deduct_down_payment:
                business_process_type = "fr_B4"
            else:
                business_process_type = paid and "fr_B2" or "fr_B1"
        else:
            if has_deduct_down_payment:
                business_process_type = "fr_M4"
            else:
                business_process_type = paid and "fr_M2" or "fr_M1"
        if self.state == "posted":
            self.sudo().write({"business_process_type": business_process_type})
        return business_process_type[3:]

    def _prepare_en16931_dict(self, speedy, pdf_invoice_bin=False):  # noqa: C901
        vals = super()._prepare_en16931_dict(speedy, pdf_invoice_bin=pdf_invoice_bin)
        vals["BT-23"] = self._prepare_bt23(speedy)
        chorus = (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_partner_entity_type == "public"
        )
        # TODO improve filtering
        if self.company_id.is_france_country:
            if self.is_purchase_document():
                buyer_partner = self.company_id.partner_id
                seller_partner = self.commercial_partner_id
            else:
                seller_partner = self.company_id.partner_id
                buyer_partner = self.commercial_partner_id
            # SELLER
            seller_siren = seller_partner._get_siren()
            if seller_siren:
                vals.update(
                    {
                        "BT-30": seller_siren,
                        "BT-30-1": "0002",
                    }
                )
            if chorus:
                seller_siret = seller_partner._get_siret()
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
            buyer_siren = buyer_partner._get_siren()
            if buyer_siren:
                vals.update(
                    {
                        "BT-47": buyer_siren,
                        "BT-47-1": "0002",
                    }
                )
            if chorus:
                buyer_siret = buyer_partner._get_siret()
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
                    if "BT-56" in vals:
                        vals.pop("BT-56")
            if buyer_partner.country_id and not buyer_partner.is_france_country:
                # TODO are you sure about BT-46 ??? Not BT-47 ?
                # TODO same for seller (e-reporting)
                if buyer_partner.country_id.id in speedy["eu_country_ids"]:
                    if buyer_partner.vat:
                        vals["BT-46"]["0223"] = buyer_partner.vat
                else:
                    partner_name = unidecode(
                        buyer_partner.name.replace(" ", "").upper()
                    )
                    country_code = buyer_partner.country_id.code
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
