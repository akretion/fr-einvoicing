# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import logging

from stdnum import ean

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import (
    float_compare,
    float_is_zero,
    float_round,
    html2plaintext,
    is_html_empty,
)

logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _check_en16931(self, speedy):
        self.ensure_one()
        vat_tax = self.tax_ids.filtered(lambda x: x.unece_type_code == "VAT")
        if speedy["company_no_vat_taxes"]:
            assert not vat_tax
            vat_dict = speedy["vat_info4company_no_vat_taxes"]
        else:
            # already checked upon invoice validation, but we control a second time
            # for invoices that have been validated before the installation of
            # this module
            if len(vat_tax) != 1:
                raise UserError(
                    self.env._(
                        "On invoice '%(inv)s', invoice line '%(inv_line)s' should "
                        "have exactly one VAT tax and not %(count)s.",
                        inv=self.move_id.display_name,
                        inv_line=self.display_name,
                        count=len(vat_tax),
                    )
                )
            assert vat_tax.unece_categ_code
            vat_dict = {"categ_code": vat_tax.unece_categ_code}
            # BT-152 is required on the line for every VAT category but O:
            # BR-S-05 wants the rate, BR-Z-05, BR-E-05, BR-AE-05, BR-G-05 and
            # BR-IC-05 all want an explicit 0, and only BR-O-05 wants it left
            # out. Restricting this to S/K/G dropped BT-152 on exempt lines,
            # which BR-E-05 rejects and which then breaks BR-FXEXT-E-08: the
            # schematron sums no line at all against the E breakdown.
            if vat_tax.unece_categ_code != "O":
                vat_dict["vat_rate"] = vat_tax.amount
            if vat_tax.unece_categ_code not in ("S", "Z"):
                assert vat_tax.unece_vatex_code
                vat_dict["vatex_code"] = vat_tax.unece_vatex_code
                vat_dict["vatex_label"] = vat_tax.unece_vatex_id.name

        base_line = self.move_id._prepare_product_base_line_for_taxes_computation(self)
        self.env["account.tax"]._add_tax_details_in_base_lines(
            [base_line], self.company_id
        )
        # print('ILine base_line ===================')
        # from pprint import pprint
        # pprint(base_line)
        non_vat_taxes = []
        if base_line.get("tax_details", {}).get("taxes_data"):
            for tax_data in base_line["tax_details"]["taxes_data"]:
                non_vat_tax = tax_data["tax"]
                if non_vat_tax.unece_type_code != "VAT":
                    tax_label = (
                        not is_html_empty(non_vat_tax.description)
                        and html2plaintext(non_vat_tax.description)
                        or non_vat_tax.name
                    )
                    tax_rate = None
                    if non_vat_tax.amount_type == "percent":
                        tax_rate = non_vat_tax.amount
                    non_vat_taxes.append(
                        {
                            "tax_amount": tax_data["raw_tax_amount_currency"],
                            "base_amount": tax_data["raw_base_amount_currency"],
                            "tax_rate": tax_rate,
                            "tax_label": tax_label,
                            "tax_unece_type_code": non_vat_tax.unece_type_code,
                        }
                    )

        if self.product_uom_id and not self.product_uom_id.unece_code:
            raise UserError(
                self.env._(
                    "UNECE code is not configured on unit of measure '%s'.",
                    self.product_uom_id.display_name,
                )
            )
        return vat_dict, non_vat_taxes, base_line

    def _prepare_bg25_single_line(self, line_number, totals, speedy):
        self.ensure_one()
        vat_dict, non_vat_taxes, base_line = self._check_en16931(speedy)
        # convert price that may be tax-include to tax-exclude price
        gross_price_base_line = self.env[
            "account.tax"
        ]._prepare_base_line_for_taxes_computation(
            None,
            currency_id=self.currency_id,
            tax_ids=self.tax_ids,
            price_unit=self.price_unit,
            quantity=1,
        )
        self.tax_ids._add_tax_details_in_base_line(
            gross_price_base_line, self.company_id
        )
        gross_price = float_round(
            gross_price_base_line["tax_details"]["raw_total_excluded_currency"],
            precision_digits=speedy["price_prec"],
        )
        if float_is_zero(self.quantity, precision_digits=speedy["qty_prec"]):
            net_price = gross_price * (1 - self.discount / 100.0)
        else:
            net_price = self.price_subtotal / self.quantity
        net_price_rounded = float_round(
            net_price, precision_digits=speedy["price_prec"]
        )
        bg28 = []
        for non_vat_tax in non_vat_taxes:
            bg28.append(
                {
                    "BT-141": self.currency_id._en16931_format(
                        non_vat_tax["tax_amount"]
                    ),
                    "BT-142": self.currency_id._en16931_format(
                        non_vat_tax["base_amount"]
                    ),
                    "BT-143": non_vat_tax["tax_rate"]
                    and speedy["tax_rate_fmt"] % non_vat_tax["tax_rate"],
                    "BT-144": non_vat_tax["tax_label"],
                    "BT-193": non_vat_tax["tax_unece_type_code"],
                }
            )
        line_total = self.price_subtotal + sum([x["tax_amount"] for x in non_vat_taxes])
        vat_rate = (
            isinstance(vat_dict.get("vat_rate"), int | float)
            and speedy["tax_rate_fmt"] % vat_dict["vat_rate"]
            or None
        )
        vals = {
            "BT-126": str(line_number),
            "BT-153": self.name or speedy["invoice_line_missing_label"],
            "BT-130": self.product_uom_id and self.product_uom_id.unece_code or "C62",
            "BT-146": speedy["price_fmt"] % net_price_rounded,
            "BT-148": speedy["price_fmt"] % gross_price,
            "BT-129": speedy["qty_fmt"] % self.quantity,
            "BT-131": self.currency_id._en16931_format(line_total),
            "BT-151": vat_dict["categ_code"],
            "BT-152": vat_rate,
            "EXT-FR-FE-178": vat_dict.get("vatex_label"),
            "EXT-FR-FE-179": vat_dict.get("vatex_code"),
            "BG-28": bg28,
        }
        totals["BT-106"] += line_total
        discount_fcompare = float_compare(
            self.discount, 0, precision_digits=speedy["disc_prec"]
        )
        if discount_fcompare > 0:
            diff_price = float_round(
                gross_price - net_price, precision_digits=speedy["price_prec"]
            )
            vals["BT-147"] = speedy["price_fmt"] % diff_price
        product = self.product_id
        if product:
            # OCA module product_harmonized_system
            if hasattr(product, "origin_country_id") and product.origin_country_id:
                vals["BT-159"] = product.origin_country_id.code
            if product.barcode and ean.is_valid(product.barcode):
                vals.update(
                    {
                        "BT-157": product.barcode,
                        "BT-157-1": "0160",
                    }
                )
            if product.default_code:
                vals["BT-155"] = product.default_code
            if product.product_template_attribute_value_ids:
                vals["BG-32"] = {}
                for attrib_val in product.product_template_attribute_value_ids:
                    attrib_name = (
                        attrib_val.product_attribute_value_id.attribute_id.name
                    )
                    value_name = attrib_val.product_attribute_value_id.name
                    vals["BG-32"][attrib_name] = value_name

        # OCA module account_invoice_start_end_dates
        if (
            hasattr(self, "start_date")
            and hasattr(self, "end_date")
            and self.start_date
            and self.end_date
        ):
            vals["BT-134"] = self.start_date
            vals["BT-135"] = self.end_date
        return vals, base_line

    def _prepare_bg20_single_line(self, totals, speedy):
        """Invoice line with price unit < 0"""
        self.ensure_one()
        res = []
        vat_dict, non_vat_taxes, base_line = self._check_en16931(speedy)
        bt92 = self.price_subtotal * -1
        vat_rate = (
            isinstance(vat_dict.get("vat_rate"), int | float)
            and speedy["tax_rate_fmt"] % vat_dict["vat_rate"]
            or None
        )
        vals = {
            "BT-92": self.currency_id._en16931_format(bt92),
            "BT-97": self.name or speedy["invoice_line_missing_label"],
            "BT-95": vat_dict["categ_code"],
            "BT-96": vat_rate,
            "BT-174": vat_dict.get("vatex_code"),
            "BT-173": vat_dict.get("vatex_label"),
        }
        res.append(vals)
        totals["BT-107"] += bt92
        for non_vat_tax in non_vat_taxes:
            bt92 = non_vat_tax["tax_amount"] * -1
            non_vat_tax_vals = dict(vals)
            label = self.env._(
                "%(tax_label)s on %(inv_line)s",
                tax_label=non_vat_tax["tax_label"],
                inv_line=vals["BT-97"],
            )
            non_vat_tax_vals.update(
                {
                    "BT-92": self.currency_id._en16931_format(bt92),
                    "BT-97": label,
                }
            )
            res.append(non_vat_tax_vals)
            totals["BT-107"] += bt92
        return res, base_line
