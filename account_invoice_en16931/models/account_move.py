# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import logging

from facturx import generate_from_file, generate_xml

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, is_html_empty
from odoo.tools.misc import format_date

logger = logging.getLogger(__name__)

DIRECT_DEBIT_CODES = ("49", "59")
CREDIT_TRF_CODES = ("30", "31", "42")


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_type_code = fields.Selection(
        [
#            ("71", "Request for payment"),
#            ("80", "Debit note related to goods or services"),
#            ("81", "Credit note related to goods or services"),
#            ("82", "Metered services invoice"),
#            ("83", "Credit note related to financial adjustments"),
#            ("84", "Debit note related to financial adjustments"),
#            ("102", "Tax notification"),
#            ("130", "Invoicing data sheet"),
#            ("202", "Direct payment valuation"),
#            ("203", "Provisional payment valuation"),
#            ("204", "Payment valuation"),
#            ("211", "Interim application for payment"),
#            ("218", "Final payment request based on completion of work"),
#            ("219", "Payment request for completed units"),
            ("261", "Self billed credit note"),
#            ("262", "Consolidated credit note - goods and services"),
#            ("295", "Price variation invoice"),
#            ("296", "Credit note for price variation"),
#            ("308", "Delcredere credit note"),
#            ("325", "Proforma invoice"),
#            ("326", "Partial invoice"),
#            ("331", "Commercial invoice which includes a packing list"),
            ("380", "Commercial invoice"),
            ("381", "Credit note"),
#            ("382", "Commission note"),
#            ("383", "Debit note"),
            ("384", "Corrected invoice"),
#            ("385", "Consolidated invoice"),
            ("386", "Prepayment invoice"),
#            ("387", "Hire invoice"),
#            ("388", "Tax invoice"),
            ("389", "Self-billed invoice"),
#            ("390", "Delcredere invoice"),
            ("393", "Factored invoice"),
#            ("394", "Lease invoice"),
#            ("395", "Consignment invoice"),
            ("396", "Factored credit note"),
#            ("420", "Optical Character Reading (OCR) payment credit note"),
#            ("456", "Debit advice"),
#            ("457", "Reversal of debit"),
#            ("458", "Reversal of credit"),
            ("471", "Self-billed corrective invoice, invoice type, Corrected"),
            ("472", "Factored Corrective Invoice, invoice type, Corrected"),
            ("473", "Self billed Factored corrective invoice, invoice type, Corrected"),
            ("500", "Self Prepayment invoice, invoice type, Original"),
            ("501", "Self billed factored invoice, invoice type, Original"),
            ("502", "Self billet factored Credit Note, Credit note type, Corrected"),
            ("503", "Prepayment credit note, credit note type, Corrected"),
#            ("527", "Self billed debit note"),
#            ("532", "Forwarder's credit note"),
#            ("553", "Forwarder's invoice discrepancy report"),
#            ("575", "Insurer's invoice"),
#            ("623", "Forwarder's invoice"),
#            ("633", "Port charges documents"),
#            ("751", "Invoice information for accounting purposes"),
#            ("780", "Freight invoice"),
#            ("817", "Claim notification"),
#            ("870", "Consular invoice"),
#            ("875", "Partial construction invoice"),
#            ("876", "Partial final construction invoice"),
#            ("877", "Final construction invoice"),
#            ("935", "Customs invoice"),
        ],
        compute="_compute_invoice_type_code",
        store=True,
    )
    # we disallow manual modification for the moment, because we would
    # need to filter depending on invoice vs refund
    # It's useful for out invoice/refund: an inherit of invoice creation
    # could set a specific value
    # It's also useful for in invoice/refund to store the value that was
    # present in the XML of the Vendor bill, so that it can then be used
    # for life cycles (info needed in CDAR XML)

    @api.depends("move_type")
    def _compute_invoice_type_code(self):
        for move in self:
            type_code = False
            if move.is_invoice(include_receipts=True):
                if move.move_type in ("in_refund", "out_refund"):
                    type_code = "381"
                else:
                    type_code = "380"
            move.invoice_type_code = type_code

    def _check_en16931(self, speedy):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(
                self.env._(
                    "EN16931 generation is only for customer invoices and refunds. "
                    "It is not the case of '%s'.",
                    self.display_name,
                )
            )
        if self.state not in ("draft", "posted"):
            raise UserError(
                self.env._(
                    "EN16931 generation is only for draft and posted invoices. "
                    "It is not the case of '%s'.",
                    self.display_name,
                )
            )
        # Source : AFNOR XP Z12-012 PDF, section 4.4.1 Types de données
        # "Il n'y a pas de règle de nombre de décimales, mais l'usage et surtout la
        # révision de la norme EN16931 limitent les prix unitaires à 4 décimales"
        if speedy["price_prec"] > 4:
            raise UserError(
                self.env._(
                    "Price precision is %s. For EN16931, the maximum value " "is 4.",
                    speedy["price_prec"],
                )
            )
        if speedy["qty_prec"] > 4:
            raise UserError(
                self.env._(
                    "Product Unif of Measure precision is %s. For EN16931, "
                    "the maximum value is 4.",
                    speedy["qty_prec"],
                )
            )
        if speedy["disc_prec"] > 2:
            raise UserError(
                self.env._(
                    "Discount precision is %s. For EN16931, " "the maximum value is 2.",
                    speedy["disc_prec"],
                )
            )

    def _prepare_bt1(self, speedy):
        self.ensure_one()
        if self.state == "posted":
            inv_number = self.name
        elif self.state == "draft":
            inv_number = self.env._("DRAFT-FOR_TEST_ONLY")
        else:
            raise
        return inv_number

    def _prepare_bt2(self, speedy):
        self.ensure_one()
        if self.state == "posted":
            inv_date = self.invoice_date
        elif self.state == "draft":
            inv_date = self.invoice_date or fields.Date.context_today(self)
        else:
            raise
        return inv_date

    def _prepare_bt14(self, speedy):
        self.ensure_one()
        res = None
        if "sale.order" in self.env:  # if module "sale" is installed
            sales = self.invoice_line_ids.sale_line_ids.order_id
            if len(sales) == 1:
                res = sales.name
        return res

    def _prepare_bt20(self, speedy):
        self.ensure_one()
        res = None
        if self.invoice_payment_term_id and not is_html_empty(
            self.invoice_payment_term_id.note
        ):
            res = html2plaintext(self.invoice_payment_term_id.note)
        # TODO: test UBL without payment terms (AFNOR spec seems to say that
        # it is required)
        return res

    def _prepare_bt23(self, speedy):
        self.ensure_one()
        # OCA module intrastat_base
        has_is_accessory_cost = hasattr(
            self.env["product.template"], "is_accessory_cost"
        )
        # If an invoice line has no product, we consider it is a service
        line_types = [
            (
                line.product_id and line.product_id.type or "service",
                has_is_accessory_cost and line.product_id.is_accessory_cost or False,
            )
            for line in self.invoice_line_ids
            if line.display_type == "product"
        ]
        service_only = all(
            [ptype == "service" for (ptype, is_accessory_cost) in line_types]
        )
        at_least_one_product = any(
            [ptype == "consu" for (ptype, is_accessory_cost) in line_types]
        )
        all_products_or_accessory_costs = all(
            [
                ptype == "consu" or is_accessory_cost
                for (ptype, is_accessory_cost) in line_types
            ]
        )
        paid = self.payment_state == "paid"
        if service_only:
            business_process_type = paid and "S2" or "S1"
        elif at_least_one_product and all_products_or_accessory_costs:
            business_process_type = paid and "B2" or "B1"
        else:
            business_process_type = paid and "M2" or "M1"
        return business_process_type

    def _prepare_bt34_with_scheme(self, speedy):
        self.ensure_one()
        if (
            hasattr(self, "company_fr_directory_line_id")
            and self.company_fr_directory_line_id
        ):
            return (self.company_fr_directory_line_id.identifier, "0225")
        return (False, False)

    def _prepare_bt49_with_scheme(self, speedy):
        self.ensure_one()
        # module l10n_fr_einvoicing
        if hasattr(self, "fr_directory_line_id") and self.fr_directory_line_id:
            return (self.fr_directory_line_id.identifier, "0225")
        return (False, False)

    def _prepare_bg1(self, speedy):
        self.ensure_one()
        res = []
        if not is_html_empty(self.narration):
            res.append(
                {
                    "BT-21": "AAI",
                    "BT-22": html2plaintext(self.narration),
                }
            )
        return res

    def _prepare_bg23(self, speedy):
        self.ensure_one()
        tax_obj = self.env["account.tax"]
        base_move_lines = self.line_ids.filtered(lambda x: x.display_type == "product")
        base_lines = [
            self._prepare_product_base_line_for_taxes_computation(mline)
            for mline in base_move_lines
        ]
        tax_amls = self.line_ids.filtered(lambda x: x.tax_repartition_line_id)
        tax_lines = [self._prepare_tax_line_for_taxes_computation(x) for x in tax_amls]
        tax_obj._add_tax_details_in_base_lines(base_lines, self.company_id)
        tax_obj._round_base_lines_tax_details(
            base_lines, self.company_id, tax_lines=tax_lines
        )
        exemption_reason = False
        if self.fiscal_position_id:
            exemption_reason = speedy["fp_speeddict"][self.fiscal_position_id.id][
                "note"
            ]

        def grouping_function(base_line, tax_data):
            if not tax_data:
                grouping_key = {
                    "unece_type_code": "VAT",
                    "unece_categ_code": "E",
                    "amount": 0,
                    "exemption_reason": exemption_reason,
                }
            else:
                tax = tax_data["tax"]
                tax_dict = speedy["tax_speeddict"][tax.id]
                if tax.unece_type_code == "VAT":
                    grouping_key = {
                        "unece_type_code": tax_dict["unece_type_code"],
                        "unece_categ_code": tax_dict["unece_categ_code"],
                        "unece_due_date_code": self._get_unece_due_date_type_code()
                        or tax_dict.get("unece_due_date_code"),
                        "amount": tax_dict["amount"],
                        "exemption_reason": exemption_reason,
                    }
                else:
                    grouping_key = {
                        "tax": tax,  # no grouping
                        "unece_type_code": tax_dict["unece_type_code"],
                    }
            return grouping_key

        base_lines_aggregated_values = tax_obj._aggregate_base_lines_tax_details(
            base_lines, grouping_function
        )
        values_per_grouping_key = tax_obj._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        res = []
        for tax_dict, tax_vals in values_per_grouping_key.items():
            if tax_dict["unece_type_code"] == "VAT":
                res.append(
                    {
                        "BT-118": tax_dict["unece_categ_code"],
                        "BT-119": "%0.*f" % (2, tax_dict["amount"]),
                        "BT-117-1": self.currency_id.name,  # TODO
                        "BT-116-1": self.currency_id.name,
                        "BT-116": self.currency_id._en16931_format(
                            tax_vals.get("target_base_amount_currency", 0)
                        ),
                        "BT-117": self.currency_id._en16931_format(
                            tax_vals.get("target_tax_amount_currency", 0)
                        ),
                    }
                )
        return res

    def _prepare_bg3(self, speedy):
        self.ensure_one()
        res = []
        if self.reversed_entry_id and self.reversed_entry_id.state == "posted":
            res.append(
                {
                    "BT-25": self.reversed_entry_id.name,
                    "EXT-FR-FE-02": self.reversed_entry_id.invoice_type_code,
                    "BT-26": self.reversed_entry_id.invoice_date,
                }
            )
        return res

    def _prepare_bg25(self, speedy):
        self.ensure_one()
        res = []
        lnumber = 0
        for line in self.invoice_line_ids:
            if line.display_type == "product":
                lnumber += 1
                res.append(line._prepare_bg25_single_line(lnumber, speedy))
        return res

    def _prepare_en16931_speedy(self, config_dict):
        self.ensure_one()
        dpo = self.env["decimal.precision"]
        lang = self.partner_id.lang or self.env.user.lang
        self = self.with_context(lang=lang)
        tax_speeddict = self.company_id._get_tax_unece_speeddict()
        vat_tax_speeddict = {
            tax_id: tax_vals
            for (tax_id, tax_vals) in tax_speeddict.items()
            if tax_vals["unece_type_code"] == "VAT"
        }
        fp_speeddict = self.company_id._get_fiscal_position_speeddict(lang=lang)

        speedy = {
            "config": config_dict,
            "price_prec": dpo.precision_get("Product Price"),
            "disc_prec": dpo.precision_get("Discount"),
            "qty_prec": dpo.precision_get("Product Unit of Measure"),
            "lang": lang,
            "tax_speeddict": tax_speeddict,
            "vat_tax_speeddict": vat_tax_speeddict,
            "fp_speeddict": fp_speeddict,
            "state2label": dict(self._fields["state"]._description_selection(self.env)),
        }
        return speedy

    def _generate_en16931_dict(self, config_dict):
        self.ensure_one()
        speedy = self._prepare_en16931_speedy(config_dict)
        self = self.with_context(lang=speedy["lang"])
        self._check_en16931(speedy)
        return self._prepare_en16931_dict(speedy)

    def _prepare_en16931_dict(self, speedy):
        self.ensure_one()
        vals = {
            "BT-1": self._prepare_bt1(speedy),
            "BT-2": self._prepare_bt2(speedy),
            "BT-3": self.invoice_type_code,
            "BT-5": self.currency_id.name,
            "BT-9": self.invoice_date_due,
            "BT-13": self.ref,  # buyer order ref
            "BT-14": self._prepare_bt14(speedy),
            #            "BT-16": ref BL
            "BT-20": self._prepare_bt20(speedy),
            "BT-23": self._prepare_bt23(speedy),
            # BT-24 is set by the factur-x lib
        }
        # SELLER
        vals["BT-34"], vals["BT-34-1"] = self._prepare_bt34_with_scheme(speedy)
        if not self.partner_id:
            raise UserError(self.env._("Customer is not selected yet."))
        buyer_partner_data = self.partner_id._en16931_partner_data()
        seller_partner_data = self.company_id.partner_id._en16931_partner_data()
        if self.user_id:
            vals["BT-41"] = self.user_id.name
            phone = self.user_id.partner_id.mobile or self.user_id.partner_id.phone
            if phone:
                vals["BT-42"] = phone
            vals["BT-43"] = self.user_id.partner_id.email
        vals["BT-27"] = seller_partner_data["name"]
        vals["BT-29"] = {}  # populated by country-specific modules
        vals["BT-35"] = seller_partner_data["street"]
        vals["BT-36"] = seller_partner_data["street2"]
        vals["BT-162"] = seller_partner_data.get("street3")
        vals["BT-38"] = seller_partner_data["zip"]
        vals["BT-37"] = seller_partner_data["city"]
        vals["BT-39"] = seller_partner_data.get("state_name")
        vals["BT-40"] = seller_partner_data["country_code"]
        vals["BT-31"] = seller_partner_data["vat"]
        # BUYER
        vals["BT-49"], vals["BT-49-1"] = self._prepare_bt49_with_scheme(speedy)
        vals["BT-46"] = {}  # populated by country-specific modules
        vals["BT-44"] = buyer_partner_data["name"]
        vals["BT-56"] = buyer_partner_data.get("contact_name")
        vals["BT-57"] = buyer_partner_data["phone"]
        vals["BT-58"] = buyer_partner_data["email"]
        vals["BT-50"] = buyer_partner_data["street"]
        vals["BT-51"] = buyer_partner_data["street2"]
        vals["BT-163"] = buyer_partner_data.get("street3")
        vals["BT-53"] = buyer_partner_data["zip"]
        vals["BT-52"] = buyer_partner_data["city"]
        vals["BT-54"] = buyer_partner_data.get("state_name")
        vals["BT-55"] = buyer_partner_data["country_code"]
        vals["BT-48"] = buyer_partner_data["vat"]
        if self.invoice_incoterm_id:
            vals["EXT-FR-FE-185"] = self.invoice_incoterm_id.code
            if self.incoterm_location:
                vals["EXT-FR-FE-186"] = self.incoterm_location
        if self.partner_shipping_id:
            ship_partner_data = self.partner_shipping_id._en16931_partner_data()
            vals["BT-70"] = ship_partner_data["name"]
            vals["BT-75"] = ship_partner_data["street"]
            vals["BT-76"] = ship_partner_data["street2"]
            vals["BT-77"] = ship_partner_data["city"]
            vals["BT-78"] = ship_partner_data["zip"]
            vals["BT-165"] = ship_partner_data.get("street3")
            vals["BT-79"] = ship_partner_data.get("state_name")
            vals["BT-80"] = ship_partner_data["country_code"]
        payment_unece_code = (
            self.preferred_payment_method_line_id
            and self.preferred_payment_method_line_id.payment_method_id.unece_code
        )
        if payment_unece_code:
            vals["BT-81"] = payment_unece_code
            bank_account = (
                self.preferred_payment_method_line_id.journal_id.bank_account_id
            )
            if (
                payment_unece_code in CREDIT_TRF_CODES
                and bank_account
                and self.move_type == "out_invoice"
            ):
                vals["BT-84"] = bank_account.sanitized_acc_number
                vals["BT-86"] = bank_account.bank_bic
            elif (
                payment_unece_code in DIRECT_DEBIT_CODES
                and hasattr(self, "mandate_id")
                and self.mandate_id.partner_bank_id
                and self.move_type == "out_invoice"
            ):
                vals["BT-83"] = (
                    self.payment_reference
                    or self.name
                    or speedy["state2label"][self.state]
                )
                vals["BT-89"] = self.mandate_id.unique_mandate_reference
                vals["BT-90"] = self.company_id.sepa_creditor_identifier
                vals["BT-91"] = self.mandate_id.partner_bank_id.sanitized_acc_number
                if hasattr(
                    self.mandate_id.partner_bank_id, "acc_number_scrambled"
                ):  # account_payment_base_oca
                    vals["BT-91"] = self.mandate_id.partner_bank_id.acc_number_scrambled
        #            and self.mandate_id.partner_bank_id.acc_type == "iban"
        else:
            logger.warning("No payment UNECE code... fallback to 30 (wire transfer)")
            vals["BT-81"] = "30"
        # TODO temp
        vals["BT-106"] = self.currency_id._en16931_format(self.amount_untaxed)
        vals["BT-109"] = self.currency_id._en16931_format(self.amount_untaxed)
        vals["BT-111"] = self.currency_id._en16931_format(self.amount_tax)
        vals["BT-111-1"] = self.currency_id.name
        vals["BT-112"] = self.currency_id._en16931_format(self.amount_total)
        vals["BT-115"] = self.currency_id._en16931_format(self.amount_residual)
        vals["BG-23"] = self._prepare_bg23(speedy)
        vals["BG-1"] = self._prepare_bg1(speedy)
        vals["BG-25"] = self._prepare_bg25(speedy)  # invoice lines
        vals["BG-3"] = self._prepare_bg3(speedy)  # invoice Referenced document
        return vals

    def generate_facturx_xml(self):
        self.ensure_one()
        assert self.is_sale_document()
        config_dict = {
            "xml_format": "factur-x",
        }
        data_dict = self._generate_en16931_dict(config_dict)
        check_schematron = "base"
        if hasattr(
            self, "fr_directory_partner_entity_type"
        ) and self.fr_directory_company_entity_type in ("private", "private_inactive"):
            if self.fr_directory_partner_entity_type in ("private", "private_inactive"):
                check_schematron = "fr-ctc"
            elif self.fr_directory_partner_entity_type == "public":
                check_schematron = "fr-chorus"
        saxon_server_url = self._get_saxon_server_url()
        xml_bytes = generate_xml(
            data_dict,
            flavor="factur-x",
            level="extended",
            check_xsd=True,
            check_schematron=check_schematron,
            saxon_server_url=saxon_server_url,
        )
        return xml_bytes

    def _prepare_facturx_pdf_metadata(self):
        self.ensure_one()
        inv_type = (
            self.move_type == "out_refund"
            and self.env._("Refund")
            or self.env._("Invoice")
        )
        if self.invoice_date:
            invoice_date = format_date(
                self.env, self.invoice_date, lang_code=self.partner_id.lang
            )
        else:
            invoice_date = self.env._("(no date)")
        if self.state == "posted":
            invoice_number = self.name
        else:
            invoice_number = self._fields["state"].convert_to_export(self.state, self)
        format_vals = {
            "company_name": self.company_id.name,
            "invoice_type": inv_type,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
        }
        pdf_metadata = {
            "author": format_vals["company_name"],
            "keywords": ", ".join([inv_type, self.env._("Factur-X")]),
            "title": self.env._(
                "{company_name}: {invoice_type} {invoice_number} dated {invoice_date}"
            ).format(**format_vals),
            "subject": self.env._(
                "Factur-X {invoice_type} {invoice_number} dated {invoice_date} "
                "issued by {company_name}"
            ).format(**format_vals),
        }
        return pdf_metadata

    def _prepare_facturx_attachments(self):
        # This method is designed to be inherited in other modules
        self.ensure_one()
        return {}

    def _regular_pdf_invoice_to_facturx_invoice(self, pdf_bytesio):
        self.ensure_one()
        assert pdf_bytesio, "Missing pdf_bytesio"
        # TODO remove self.commercial_partner_id.is_france_country once impl is final AND what is after
        if self.is_sale_document() and self.commercial_partner_id.is_france_country and hasattr(self.company_id.partner_id, 'fr_directory_entity_type') and self.company_id.partner_id.fr_directory_entity_type == 'private':
            facturx_xml_bytes = self.generate_facturx_xml()
            pdf_metadata = self._prepare_facturx_pdf_metadata()
            lang = (
                self.partner_id.lang and self.partner_id.lang.replace("_", "-") or None
            )
            # Generate a new PDF with XML file as attachment
            attachments = self._prepare_facturx_attachments()
            generate_from_file(
                pdf_bytesio,
                facturx_xml_bytes,
                flavor="factur-x",
                level="extended",
                check_xsd=False,
                check_schematron=False,
                pdf_metadata=pdf_metadata,
                lang=lang,
                attachments=attachments,
            )
            logger.info("Factur-X PDF invoice successfully generated")

    @api.model
    def _get_saxon_server_url(self):
        url_config = (
            self.env["ir.config_parameter"].sudo().get_param("en16931.saxon_server_url")
        )
        url = url_config and url_config.strip() or None
        return url
