# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import base64
import logging
from io import BytesIO
from pprint import pformat
from urllib.parse import urljoin

import pytz
from pypdf import PdfWriter
from pypdf.generic import NameObject

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare, html2plaintext, is_html_empty
from odoo.tools.misc import format_amount, format_date

logger = logging.getLogger(__name__)

try:
    from facturx import generate_from_file, generate_xml
except (OSError, ImportError) as err:
    logger.debug("Cannot import facturx. Error details below.")
    logger.debug(err)


DIRECT_DEBIT_CODES = ("49", "59")
CREDIT_TRF_CODES = ("30", "31", "42")
INVOICE_TYPE_CODES = (
    "380",
    "389",
    "393",
    "501",
    "386",
    "500",
    "384",
    "471",
    "472",
    "473",
)
REFUND_TYPE_CODES = ("261", "381", "396", "502", "503")
RESERVED_INV_ATTACHMENT_FILENAMES = ("factur-x.xml", "factur-xubl.xml")
INV_ATTACHMENT_ALLOWED_MIMETYPES = (
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    "text/xml",
    "application/xml",
)


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_type_code = fields.Selection(
        [
            ("261", "Self-billed Credit Note"),
            ("380", "Commercial Invoice"),
            ("381", "Credit Note"),
            ("384", "Corrected Invoice"),
            ("386", "Prepayment Invoice"),
            ("389", "Self-billed Invoice"),
            ("393", "Factored Invoice"),
            ("396", "Factored Credit Note"),
            (
                "471",
                "Self-billed Corrective Invoice",
            ),
            ("472", "Factored Corrective Invoice"),
            (
                "473",
                "Self-billed Factored Corrective Invoice",
            ),
            (
                "500",
                "Self-billed Prepayment Invoice",
            ),
            ("501", "Self-billed Factored Invoice"),
            ("502", "Self-billed Factored Credit Note"),
            ("503", "Prepayment Credit Note"),
        ],
        compute="_compute_invoice_type_code",
        store=True,
        tracking=True,
        help="Business Term BT-3 in EN16931",
    )
    # we disallow manual modification for the moment, because we would
    # need to filter depending on invoice vs refund
    # It's useful for out invoice/refund: an inherit of invoice creation
    # could set a specific value
    # It's also useful for in invoice/refund to store the value that was
    # present in the XML of the Vendor bill, so that it can then be used
    # for life cycles (info needed in CDAR XML)
    business_process_type = fields.Selection(
        [], copy=False, tracking=True, help="Business Term BT-23 in EN16931"
    )
    invoice_attachment_ids = fields.Many2many(
        "ir.attachment",
        "account_move_invoice_attachment_rel",
        string="eInvoice Attachments",
        copy=False,
        help="Attachments added to the electronic invoice. In UBL and CII XML, "
        "these attachments are added in the XML (BG-24 / BT-125). In Factur-X, "
        "these attachments are added as additional attachments of the PDF.",
    )

    @api.depends("move_type", "invoice_line_ids")
    def _compute_invoice_type_code(self):
        # sale module
        has_is_downpayment = hasattr(self.env["account.move.line"], "is_downpayment")
        if has_is_downpayment:
            qty_prec = self.env["decimal.precision"].precision_get(
                "Product Unit of Measure"
            )
        for move in self:
            type_code = False
            if move.is_invoice(include_receipts=True):
                if has_is_downpayment:
                    for line in move.invoice_line_ids:
                        if (
                            line.display_type == "product"
                            and line.is_downpayment
                            and float_compare(
                                line.quantity, 0, precision_digits=qty_prec
                            )
                            > 0
                        ):
                            if move.move_type in ("in_refund", "out_refund"):
                                type_code = "503"
                            else:
                                type_code = "386"
                            break
                if not type_code:
                    if move.move_type in ("in_refund", "out_refund"):
                        type_code = "381"
                    else:
                        type_code = "380"

            move.invoice_type_code = type_code

    @api.constrains("invoice_attachment_ids")
    def _check_invoice_attachment_ids(self):
        for move in self:
            filenames = set()
            for attach in move.invoice_attachment_ids:
                if attach.name.lower() in RESERVED_INV_ATTACHMENT_FILENAMES:
                    raise ValidationError(
                        self.env._(
                            "You cannot add an e-invoice attachment with "
                            "filename '%s' because this filename is reserved.",
                            attach.name,
                        )
                    )
                if attach.name in filenames:
                    raise ValidationError(
                        self.env._(
                            "Invoice '%(invoice)s' has 2 e-invoice attachments "
                            "with the same filename '%(filename)s'.",
                            invoice=move.display_name,
                            filename=attach.name,
                        )
                    )
                filenames.add(attach.name)
                if attach.mimetype not in INV_ATTACHMENT_ALLOWED_MIMETYPES:
                    raise ValidationError(
                        self.env._(
                            "You cannot add e-invoice attachment '%(filename)s' "
                            "whose MIME type is '%(mimetype)s'. Allowed MIME types "
                            "for e-invoice attachments are: %(allowed_mimetypes)s.",
                            filename=attach.name,
                            mimetype=attach.mimetype,
                            allowed_mimetypes=", ".join(
                                INV_ATTACHMENT_ALLOWED_MIMETYPES
                            ),
                        )
                    )

    @api.constrains("move_type", "invoice_type_code")
    def _check_invoice_type_code(self):
        type_code2label = dict(
            self._fields["invoice_type_code"]._description_selection(self.env)
        )
        for move in self:
            if move.is_sale_document() and not move.invoice_type_code:
                raise ValidationError(
                    self.env._(
                        "Field 'Invoice Type Code' is required on customer "
                        "invoices/refunds, but it is not set on '%s'.",
                        move.display_name,
                    )
                )
            if (
                move.move_type in ("in_invoice", "out_invoice")
                and move.invoice_type_code in REFUND_TYPE_CODES
            ):
                raise ValidationError(
                    self.env._(
                        "Invoice '%(move)s' has Invoice Type Code "
                        "'%(type_code)s' which is for refunds.",
                        move=move.display_name,
                        type_code=type_code2label.get(move.invoice_type_code),
                    )
                )
            elif (
                move.move_type in ("out_refund", "in_refund")
                and move.invoice_type_code in INVOICE_TYPE_CODES
            ):
                raise ValidationError(
                    self.env._(
                        "Refund '%(move)s' has Invoice Type Code "
                        "'%(type_code)s' which is for invoices.",
                        move=move.display_name,
                        type_code=type_code2label.get(move.invoice_type_code),
                    )
                )

    def _post(self, soft=True):
        for move in self:
            if (
                move.is_sale_document()
                and not config["test_enable"]
                and not self._context.get("skip_en16931_checks_upon_post")
            ):
                move.company_id._en16931_checks()
                errors = []
                if not move.company_id.no_vat_taxes:
                    for line in move.invoice_line_ids.filtered(
                        lambda x: x.display_type == "product"
                    ):
                        line._post_check_en16931_sale_document(errors)
                if move.currency_id.compare_amounts(move.amount_untaxed, 0) < 0:
                    errors.append(
                        self.env._(
                            "Total Untaxed Amount (%(amount_untaxed)s) is negative. "
                            "This is not supported by the EN16931 standard.",
                            amount_untaxed=format_amount(
                                self.env, move.amount_untaxed, move.currency_id
                            ),
                        )
                    )
                if errors:
                    raise UserError(
                        self.env._(
                            "Errors on invoice '%(inv)s' for EN16931 "
                            "e-invoicing:\n%(err_msg)s",
                            inv=move.display_name,
                            err_msg="\n".join([f"- {error}" for error in errors]),
                        )
                    )
        return super()._post(soft=soft)

    def _en16931_checks_upon_invoice_generation(self):
        self.ensure_one()
        self.company_id._en16931_checks()
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

    def _prepare_bt1(self, speedy):
        self.ensure_one()
        if self.is_purchase_document(include_receipts=True):
            if self.state == "posted":
                inv_number = self.ref or self.name
            elif self.state == "draft":
                inv_number = self.ref or self.env._("DRAFT-FOR_TEST_ONLY")
            else:
                raise
        else:
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

    def _prepare_bt6(self, speedy):
        self.ensure_one()
        if self.currency_id != speedy["company_currency"]:
            return speedy["company_currency"].name
        return None

    def _prepare_bt8(self, speedy):
        self.ensure_one()
        if speedy["company_no_vat_taxes"]:
            return None
        # if OCA module l10n_fr_account_vat_return is installed
        elif hasattr(self, "out_vat_on_payment"):
            if self.out_vat_on_payment:
                return "payment"
            else:
                return "invoice"
        else:
            # use VAT tax of first invoice line
            # not a good solution... but how could we do better
            # with the broken native datamodel ?
            vat_tax_first_line = self.invoice_line_ids.filtered(
                lambda x: x.display_type == "product"
            )[:1].tax_ids.filtered(lambda x: x.unece_type_code == "VAT")
            if (
                vat_tax_first_line
                and vat_tax_first_line.tax_exigibility == "on_payment"
            ):
                return "payment"
            else:
                return "invoice"
        return None

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
        if self.business_process_type:
            # [3:] to skip the country prefix
            return self.business_process_type[3:]
        else:
            return None

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

    def _prepare_bt72(self, speedy):
        self.ensure_one()
        if speedy["sale_stock_installed"]:
            sale_orders = self.line_ids.sale_line_ids.order_id
            if sale_orders:
                pickings = sale_orders.picking_ids
                if pickings:
                    delivery_datetimes = [
                        p.date_done
                        for p in pickings
                        if p.state == "done" and p.date_done
                    ]
                    if delivery_datetimes:
                        delivery_datetime_naive_utc = max(delivery_datetimes)
                        delivery_datetime_aware_utc = pytz.utc.localize(
                            delivery_datetime_naive_utc
                        )
                        user_tz = (
                            self.env.user.tz
                            and pytz.timezone(self.env.user.tz)
                            or pytz.utc
                        )
                        delivery_datetime_aware_usertz = (
                            delivery_datetime_aware_utc.astimezone(user_tz)
                        )
                        delivery_date = delivery_datetime_aware_usertz.date()
                        return delivery_date
        # BT-72 is required (or BT-73+BT-74, but we don't have Odoo fields for that),
        # cf rule BR-IC-11. That's why I put this stupid fallback
        return self.invoice_date or fields.Date.context_today(self)

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

    def _prepare_bg23(self, base_lines, speedy):
        self.ensure_one()
        bt110 = bt111 = 0.0
        bg23 = []
        if speedy["company_no_vat_taxes"]:
            vat_dict = speedy["vat_info4company_no_vat_taxes"]
            bg23.append(
                {
                    "BT-118": vat_dict["categ_code"],
                    "BT-117-1": self.currency_id.name,  # for UBL
                    "BT-116-1": self.currency_id.name,  # for UBL
                    "BT-116": self.currency_id._en16931_format(
                        self.amount_total
                    ),  # base
                    "BT-117": self.currency_id._en16931_format(0),  # amount
                    "BT-121": vat_dict["vatex_code"],
                    "BT-120": vat_dict["vatex_label"],
                }
            )
            return bg23, bt110, bt111
        tax_obj = self.env["account.tax"]
        tax_amls = self.line_ids.filtered(lambda x: x.tax_repartition_line_id)
        tax_lines = [self._prepare_tax_line_for_taxes_computation(x) for x in tax_amls]
        tax_obj._round_base_lines_tax_details(
            base_lines, self.company_id, tax_lines=tax_lines
        )

        # from pprint import pprint
        # print('BG23 === base_lines================')
        # pprint(base_lines)
        def grouping_function(base_line, tax_data):
            tax = tax_data["tax"]
            grouping_key = {
                "unece_type_code": tax.unece_type_code,
                "unece_categ_code": tax.unece_categ_code,
                "rate_int": int(round(tax.amount * 1000)),
                "vatex_code": tax.unece_vatex_code,
                "vatex_label": tax.unece_vatex_id.name,
            }
            return grouping_key

        base_lines_aggregated_values = tax_obj._aggregate_base_lines_tax_details(
            base_lines, grouping_function
        )
        values_per_grouping_key = tax_obj._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        for tax_dict, tax_vals in values_per_grouping_key.items():
            if tax_dict["unece_type_code"] == "VAT":
                bt110 += tax_vals.get("target_tax_amount_currency", 0)
                bt111 += tax_vals.get("target_tax_amount", 0)
                bg23.append(
                    {
                        "BT-116": self.currency_id._en16931_format(
                            tax_vals.get("target_base_amount_currency", 0)
                        ),
                        "BT-116-1": self.currency_id.name,
                        "BT-117": self.currency_id._en16931_format(
                            tax_vals.get("target_tax_amount_currency", 0)
                        ),
                        "BT-117-1": self.currency_id.name,
                        "BT-118": tax_dict["unece_categ_code"],
                        "BT-119": "%.2f" % (tax_dict["rate_int"] / 1000),  # rate
                        "BT-120": tax_dict["vatex_label"],
                        "BT-121": tax_dict["vatex_code"],
                    }
                )
        return bg23, bt110, bt111

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

    def _prepare_bg24(self, speedy, pdf_invoice_bin):
        self.ensure_one()
        bg24 = []
        if pdf_invoice_bin:
            filename = self.with_context(bt125_2=True)._prepare_en16931_filename(
                "pdf_none"
            )
            bg24.append(
                {
                    "BT-122": self.state == "posted"
                    and self.name
                    or self.env._("Draft Invoice"),
                    "BT-123": "LISIBLE",
                    "BT-125": base64.encodebytes(pdf_invoice_bin),
                    "BT-125-1": "application/pdf",
                    "BT-125-2": filename,
                }
            )
        for attach in self.invoice_attachment_ids:
            if attach.type == "binary":
                bg24.append(
                    {
                        "BT-122": attach.name,
                        "BT-125": attach.datas,
                        "BT-125-1": attach.mimetype,
                        "BT-125-2": attach.name,
                        # for Factur-X
                        "modification_datetime": attach.write_date,
                        "creation_datetime": attach.create_date,
                    }
                )
        return bg24

    def _prepare_en16931_payment_data(self, speedy):
        self.ensure_one()
        vals = {}
        payment_method_line = self.preferred_payment_method_line_id
        payment_unece_code = (
            payment_method_line
            and payment_method_line.payment_method_id.unece_code
            or False
        )
        # in the schematron, they want to back account even on refunds,
        # so we don't filter the IF below on "out_invoice"
        if payment_unece_code in CREDIT_TRF_CODES:
            if hasattr(payment_method_line, "bank_account_link"):
                # if account_payment_base_oca is installed
                bank_account = (
                    payment_method_line.bank_account_link == "fixed"
                    and payment_method_line.journal_id.bank_account_id
                    or None
                )
            else:
                bank_account = payment_method_line.journal_id.bank_account_id
            if bank_account:
                vals["BT-81"] = payment_unece_code
                vals["BT-84"] = bank_account.sanitized_acc_number
                vals["BT-86"] = bank_account.bank_bic
        elif (
            payment_unece_code in DIRECT_DEBIT_CODES
            and hasattr(self, "mandate_id")
            and self.mandate_id.partner_bank_id
            and self.move_type == "out_invoice"
        ):
            vals["BT-81"] = payment_unece_code
            vals["BT-83"] = (
                self.payment_reference or self.name or speedy["state2label"][self.state]
            )
            vals["BT-89"] = self.mandate_id.unique_mandate_reference
            vals["BT-90"] = self.company_id.sepa_creditor_identifier
            vals["BT-91"] = self.mandate_id.partner_bank_id.sanitized_acc_number
            if hasattr(
                self.mandate_id.partner_bank_id, "acc_number_scrambled"
            ):  # account_payment_base_oca
                vals["BT-91"] = self.mandate_id.partner_bank_id.acc_number_scrambled
        return vals

    def _prepare_en16931_invoice_lines(self, speedy):
        self.ensure_one()
        bg25 = []
        bg20 = []
        base_lines = []
        totals = {
            "BT-106": 0.0,
            "BT-107": 0.0,
            "BT-108": 0.0,
        }
        lnumber = 0
        for line in self.invoice_line_ids:
            if line.display_type == "product":
                price_compare = float_compare(
                    line.price_unit, 0, precision_digits=speedy["price_prec"]
                )
                if price_compare >= 0:
                    lnumber += 1
                    lvals, base_line = line._prepare_bg25_single_line(
                        lnumber, totals, speedy
                    )
                    bg25.append(lvals)
                else:
                    allowance_vals_list, base_line = line._prepare_bg20_single_line(
                        totals, speedy
                    )
                    bg20 += allowance_vals_list
                base_lines.append(base_line)
        return bg25, bg20, totals, base_lines

    def _prepare_en16931_speedy(self):
        self.ensure_one()
        dpo = self.env["decimal.precision"]
        lang = self.partner_id.lang or self.env.user.lang
        self = self.with_context(lang=lang)
        company_currency = self.company_id.currency_id
        no_vat_taxes_vatex_id = self.company_id.no_vat_taxes_vatex_id or self.env.ref(
            "account_tax_unece.tax_vatex_eu_o"
        )
        price_prec = dpo.precision_get("Product Price")
        disc_prec = dpo.precision_get("Discount")
        qty_prec = dpo.precision_get("Product Unit of Measure")
        speedy = {
            "price_prec": price_prec,
            "disc_prec": disc_prec,
            "qty_prec": qty_prec,
            "price_fmt": f"%.{price_prec}f",
            "disc_fmt": f"%.{disc_prec}f",
            "qty_fmt": f"%.{qty_prec}f",
            "tax_rate_fmt": "%.2f",
            "tax_amount_prec": 4,  # precision of the 'amount' field of account.tax
            "lang": lang,
            "company_no_vat_taxes": self.company_id.no_vat_taxes,
            "vat_info4company_no_vat_taxes": {
                "categ_code": "O",  # not E !
                "vatex_code": no_vat_taxes_vatex_id.code,
                "vatex_label": no_vat_taxes_vatex_id.name,
            },
            "state2label": dict(self._fields["state"]._description_selection(self.env)),
            "invoice_line_missing_label": self.env._("Missing invoice line label."),
            "company_currency": company_currency,
            "company_currency_id": company_currency.id,
            "eu_country_ids": self.env.ref("base.europe").country_ids.ids,
            "sale_installed": hasattr(self, "sale_order_count"),
            "sale_stock_installed": hasattr(self.company_id, "security_lead"),
        }
        return speedy

    def _prepare_en16931_filename(self, invoice_format):
        self.ensure_one()
        if self.state == "draft":
            filename = self.env._("draft_invoice")
        else:
            filename = self.name.replace("/", "_")
        if invoice_format:
            if invoice_format.startswith(("facturx", "pdf_")):
                filename += ".pdf"
            elif invoice_format.startswith("ubl"):
                filename += "_ubl.xml"
            elif invoice_format.startswith("cii"):
                filename += "_cii.xml"
        return filename

    def _generate_en16931_dict(self, pdf_invoice_bin=False):
        self.ensure_one()
        speedy = self._prepare_en16931_speedy()
        self = self.with_context(lang=speedy["lang"])
        self._en16931_checks_upon_invoice_generation()
        return self._prepare_en16931_dict(speedy, pdf_invoice_bin=pdf_invoice_bin)

    def _prepare_en16931_dict(self, speedy, pdf_invoice_bin=False):
        self.ensure_one()
        vals = {}
        vals["BT-1"] = self._prepare_bt1(speedy)
        vals["BT-2"] = self._prepare_bt2(speedy)
        vals["BT-3"] = self.invoice_type_code
        vals["BT-5"] = self.currency_id.name
        vals["BT-6"] = self._prepare_bt6(speedy)
        vals["BT-8"] = self._prepare_bt8(speedy)
        vals["BT-9"] = self.invoice_date_due
        if vals["BT-9"] and vals["BT-9"] < vals["BT-2"]:
            logger.warning(
                f"BT-9 ({vals['BT-9']}) cannot be < BT-2 ({vals['BT-2']}): "
                "forcing value to BT-2"
            )
            vals["BT-9"] = vals["BT-2"]
        vals["BT-13"] = self.ref  # buyer order ref
        vals["BT-14"] = self._prepare_bt14(speedy)
        # "BT-16": ref BL
        vals["BT-20"] = self._prepare_bt20(speedy)
        vals["BT-23"] = self._prepare_bt23(speedy)
        # BT-24 is set by the factur-x lib
        # SELLER
        vals["BT-34"], vals["BT-34-1"] = self._prepare_bt34_with_scheme(speedy)
        if not self.partner_id:
            raise UserError(self.env._("Customer is not selected yet."))
        if self.is_purchase_document():
            buyer_partner = self.company_id.partner_id
            seller_partner = self.partner_id
        else:
            seller_partner = self.company_id.partner_id
            buyer_partner = self.partner_id
        buyer_partner_data = buyer_partner._en16931_partner_data()
        seller_partner_data = seller_partner._en16931_partner_data()
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
        vals["BT-72"] = self._prepare_bt72(speedy)
        vals.update(self._prepare_en16931_payment_data(speedy))
        bg25, bg20, totals, base_lines = self._prepare_en16931_invoice_lines(speedy)
        for allowance_total_field in ("BT-107", "BT-108"):
            allowance_total = totals[allowance_total_field]
            if not self.currency_id.is_zero(allowance_total):
                vals[allowance_total_field] = self.currency_id._en16931_format(
                    allowance_total
                )
        vals["BT-106"] = self.currency_id._en16931_format(totals["BT-106"])
        bt109 = totals["BT-106"] - totals["BT-107"] + totals["BT-108"]
        bg23, bt110, bt111 = self._prepare_bg23(base_lines, speedy)
        vals["BT-109"] = self.currency_id._en16931_format(bt109)
        vals["BT-110"] = self.currency_id._en16931_format(bt110)
        vals["BT-110-1"] = self.currency_id.name
        if vals.get("BT-6"):
            vals["BT-111"] = self.currency_id._en16931_format(bt111)
            vals["BT-111-1"] = vals["BT-6"]
        vals["BT-112"] = self.currency_id._en16931_format(self.amount_total)
        vals["BT-113"] = self.currency_id._en16931_format(
            self.amount_total - self.amount_residual
        )
        vals["BT-115"] = self.currency_id._en16931_format(self.amount_residual)
        vals["BG-23"] = bg23
        vals["BG-1"] = self._prepare_bg1(speedy)
        vals["BG-25"] = bg25  # invoice lines with price >= 0
        vals["BG-20"] = bg20  # invoice lines with price < 0 as allowance charge=false
        vals["BG-3"] = self._prepare_bg3(speedy)  # invoice Referenced document
        vals["BG-24"] = self._prepare_bg24(speedy, pdf_invoice_bin)
        return vals

    def generate_en16931_xml(
        self, flavor, level, invoice_format, pdf_invoice_bin=False
    ):
        self.ensure_one()
        assert self.is_sale_document()
        data_dict = self._generate_en16931_dict(pdf_invoice_bin=pdf_invoice_bin)
        check_schematron = "base"
        if (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_company_entity_type == "private"
            and not self.env.context.get("chorus_old_xml_syntax")
        ):
            if self.fr_directory_partner_entity_type == "private":
                check_schematron = "fr-ctc"
            elif self.fr_directory_partner_entity_type == "public":
                check_schematron = "fr-chorus"
        saxon_server_url = self._get_specific_saxon_server_url()
        saxon_server_codedb_dir = self._get_saxon_server_codedb_dir()
        saxon_server_codedb_base_url = self._get_saxon_server_codedb_base_url()
        if saxon_server_codedb_dir:
            saxon_server_codedb_base_url = None
        saxon_server_raise_if_http_error = self._get_saxon_server_raise_if_http_error()
        logger.debug(
            f"Calling generate_xml with "
            f"saxon_server_codedb_dir={saxon_server_codedb_dir} and "
            f"saxon_server_codedb_base_url={saxon_server_codedb_base_url} and "
            f"saxon_server_raise_if_http_error={saxon_server_raise_if_http_error}"
        )
        attachments = {}
        # for Factur-X, we prefer to have attachments in PDF rather than inside XML
        # (and we don't want to have both !)
        if invoice_format.startswith("facturx"):
            for attach in data_dict.get("BG-24", []):
                if attach.get("BT-125") and attach.get("BT-125-2"):
                    vals = {"filedata": base64.decodebytes(attach["BT-125"])}
                    if attach.get("modification_datetime"):
                        vals["modification_datetime"] = attach["modification_datetime"]
                    if attach.get("creation_datetime"):
                        vals["creation_datetime"] = attach["creation_datetime"]
                    attachments[attach["BT-125-2"]] = vals
            data_dict.pop("BG-24")
        try:
            xml_bytes = generate_xml(
                data_dict,
                flavor=flavor,
                level=level,
                check_xsd=True,
                check_schematron=check_schematron,
                saxon_server_url=saxon_server_url,
                saxon_server_codedb_base_url=saxon_server_codedb_base_url,
                saxon_server_codedb_dir=saxon_server_codedb_dir,
                saxon_server_raise_if_http_error=saxon_server_raise_if_http_error,
            )
        except Exception as err:
            logger.warning("data_dict dumped below")
            logger.warning(pformat(data_dict))
            raise UserError(
                self.env._(
                    "Failed to generate the %(flavor)s XML file "
                    "with profile %(level)s. Error: %(err)s",
                    flavor=flavor,
                    level=level,
                    err=str(err),
                )
            ) from err
        if invoice_format == "facturx_ubl":
            try:
                ubl_xml_bytes = generate_xml(
                    data_dict,
                    flavor="ubl-2.1",
                    level="extended-ctc-fr",
                    check_xsd=True,
                    check_schematron=check_schematron,
                    saxon_server_url=saxon_server_url,
                    saxon_server_codedb_base_url=saxon_server_codedb_base_url,
                    saxon_server_codedb_dir=saxon_server_codedb_dir,
                )
            except Exception as err:
                logger.warning("data_dict dumped below")
                logger.warning(pformat(data_dict))
                raise UserError(
                    self.env._(
                        "Failed to generate the UBL-2.1 XML file "
                        "with profile 'extended-ctc-fr'. Error: %(err)s",
                        err=str(err),
                    )
                ) from err
            # Factur-X standard v1.09, end of section 6.4, specifies
            # that, if we add a UBL XML as attachment, filename should be
            # factur-xubl.xml. I don't like this name, but it's the standard !
            attachments["factur-xubl.xml"] = {
                "filedata": ubl_xml_bytes,
            }
        return xml_bytes, attachments

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

    def _get_pdf_invoice_format(self):
        """Returns the invoice_format, but only if it is possible to generate the XML
        Otherwize return False"""
        self.ensure_one()
        invoice_format = self.company_id.en16931_default_pdf_invoice
        # I want to allow embedded XML even on draft invoice
        # So I write here the conditions to be able to generate a valid XML
        if (
            invoice_format
            and invoice_format != "none"
            and self.is_sale_document()
            and self.partner_id
            and self.state != "cancel"
            and self.invoice_line_ids.filtered(lambda x: x.display_type == "product")
        ):
            return invoice_format
        else:
            return False

    def _prepare_ubl_attachment_filename(self):
        self.ensure_one()
        return "UBL-invoice.xml"

    def _regular_pdf_invoice_to_en16931_pdf_invoice(self, pdf_bytesio, invoice_format):
        self.ensure_one()
        assert pdf_bytesio, "Missing pdf_bytesio"
        if invoice_format.startswith("facturx"):
            pdf_metadata = self._prepare_facturx_pdf_metadata()
            lang = (
                self.partner_id.lang and self.partner_id.lang.replace("_", "-") or None
            )
            # Generate a new PDF with XML file as attachment
            xml_bytes, attachments = self.generate_en16931_xml(
                "factur-x", "extended", invoice_format
            )
            generate_from_file(
                pdf_bytesio,
                xml_bytes,
                flavor="factur-x",
                level="extended",
                check_xsd=False,
                check_schematron=False,
                pdf_metadata=pdf_metadata,
                lang=lang,
                attachments=attachments,
            )
            logger.info("Factur-X PDF invoice successfully generated")
        elif invoice_format == "pdf_ubl":
            ubl_xml_bytes = self.generate_en16931_xml(
                "ubl-2.1", "extended-ctc-fr", invoice_format
            )[0]
            pdf_writer = PdfWriter(clone_from=pdf_bytesio)
            embedded_file = pdf_writer.add_attachment(
                filename=self._prepare_ubl_attachment_filename(), data=ubl_xml_bytes
            )
            embedded_file.subtype = NameObject("/text/xml")
            pdf_writer._root_object.update(
                {
                    NameObject("/PageMode"): NameObject("/UseAttachments"),
                }
            )
            pdf_writer.write(pdf_bytesio)

    def _get_pdf_invoice_bin(self):
        """This works with both qweb and py3o"""
        self.ensure_one()
        pdf_invoice_bin, _filetype = (
            self.env["ir.actions.report"]
            .with_context(regular_pdf_invoice=True)
            ._render("account.report_invoice_with_payments", [self.id])
        )
        return pdf_invoice_bin

    def _get_en16931_invoice_bin(self, invoice_format, b64=False):
        self.ensure_one()
        if invoice_format in ("facturx", "facturx_ubl", "pdf_ubl"):
            pdf_invoice_bin = self._get_pdf_invoice_bin()
            with BytesIO(pdf_invoice_bin) as pdf_bytesio:
                self._regular_pdf_invoice_to_en16931_pdf_invoice(
                    pdf_bytesio, invoice_format
                )
                pdf_bytesio.seek(0)
                invoice_bin = pdf_bytesio.read()
        elif invoice_format == "ubl_pdf":
            pdf_invoice_bin = self._get_pdf_invoice_bin()
            invoice_bin = self.generate_en16931_xml(
                "ubl-2.1",
                "extended-ctc-fr",
                invoice_format,
                pdf_invoice_bin=pdf_invoice_bin,
            )[0]
        elif invoice_format == "ubl":
            invoice_bin = self.generate_en16931_xml(
                "ubl-2.1", "extended-ctc-fr", invoice_format
            )[0]
        elif invoice_format == "cii_pdf":
            pdf_invoice_bin = self._get_pdf_invoice_bin()
            invoice_bin = self.generate_en16931_xml(
                "facturx",
                "extended-ctc-fr",
                invoice_format,
                pdf_invoice_bin=pdf_invoice_bin,
            )[0]
        elif invoice_format == "cii":
            invoice_bin = self.generate_en16931_xml(
                "facturx", "extended-ctc-fr", invoice_format
            )[0]
        else:
            raise ValueError("Wrong value for invoice_format arg")
        if b64:
            invoice_bin = base64.encodebytes(invoice_bin)
        return invoice_bin

    @api.model
    def _get_specific_saxon_server_url(self):
        url_config = (
            self.env["ir.config_parameter"].sudo().get_param("en16931.saxon_server_url")
        )
        url = url_config and url_config.strip() or None
        return url

    @api.model
    def _get_saxon_server_codedb_dir(self):
        codedb_dir = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("en16931.saxon_server_codedb_dir")
        )
        return codedb_dir and codedb_dir.strip() or None

    @api.model
    def _get_saxon_server_codedb_base_url(self):
        codedb_base_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("en16931.saxon_server_codedb_base_url")
        )
        if codedb_base_url:
            return codedb_base_url.strip()
        web_base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if web_base_url:
            return urljoin(web_base_url, "en16931/")
        return None

    @api.model
    def _get_saxon_server_raise_if_http_error(self):
        saxon_validation_blocking = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("en16931.saxon_validation_blocking")
        )
        if saxon_validation_blocking and saxon_validation_blocking == "True":
            return True
        return False
