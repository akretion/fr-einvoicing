# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


import logging

from stdnum import ean

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_round

logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _check_en16931(self, speedy):
        self.ensure_one()
        vat_tax_count = len(self.tax_ids.filtered(lambda x: x.unece_type_code == "VAT"))
        if vat_tax_count > 1:
            raise UserError(
                self.env._(
                    "Invoice line '%(inv_line)s' on invoice '%(inv)s' has %(count)s "
                    "VAT taxes. EN-16931 only allows one VAT tax.",
                    inv_line=self.display_name,
                    inv=self.move_id.display_name,
                    count=vat_tax_count,
                )
            )
        if self.product_uom_id and not self.product_uom_id.unece_code:
            raise UserError(
                self.env._(
                    "UNECE code is not configured on unit of measure '%s'.",
                    self.product_uom_id.display_name,
                )
            )

    def _prepare_bg25_single_line(self, line_number, speedy):
        self.ensure_one()
        self._check_en16931(speedy)
        if self.quantity:  # TODO
            net_price = float_round(
                self.price_subtotal / self.quantity,
                precision_digits=speedy["price_prec"],
            )
        vals = {
            "BT-126": str(line_number),
            "BT-153": self.name or self.env._("No invoice line label"),
            "BT-130": self.product_uom_id and self.product_uom_id.unece_code or "C62",
            "BT-146": "%0.*f" % (speedy["price_prec"], net_price),
            "BT-129": "%0.*f" % (speedy["qty_prec"], self.quantity),
            "BT-131": self.currency_id._en16931_format(self.price_subtotal),  # TODO
        }
        single_vat_tax = self.tax_ids.filtered(lambda x: x.unece_type_code == "VAT")
        if single_vat_tax:
            tax_dict = speedy["tax_speeddict"][single_vat_tax.id]
            vals.update(
                {
                    "BT-151": tax_dict["unece_categ_code"],
                    "BT-152": "%0.*f" % (2, tax_dict["amount"]),
                }
            )

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
                vals["BG-32"] = {
                    attrib_val.product_attribute_value_id.attribute_id.name: attrib_val.product_attribute_value_id.name
                    for attrib_val in product.product_template_attribute_value_ids
                }

        # OCA module account_invoice_start_end_dates
        if (
            hasattr(self, "start_date")
            and hasattr(self, "end_date")
            and self.start_date
            and self.end_date
        ):
            vals["BT-134"] = self.start_date
            vals["BT-135"] = self.end_date
        return vals
