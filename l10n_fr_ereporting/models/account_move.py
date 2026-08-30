# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    fr_ereporting_id = fields.Many2one(
        "fr.ereporting", string="e-Reporting", readonly=True, copy=False
    )

    def unlink(self):
        for move in self:
            if move.fr_ereporting_id:
                raise UserError(
                    self.env._(
                        "You cannot delete '%(move)s' because it is used in "
                        "e-reporting '%(reporting)s'.",
                        move=move.display_name,
                        reporting=move.fr_ereporting_id.display_name,
                    )
                )
        return super().unlink()

    def _post(self, soft=True):
        for move in self:
            if (
                move.is_invoice()
                and move.fiscal_position_id
                and move.fiscal_position_id.fr_vat_type == "intracom_b2b"
                and (
                    not move.commercial_partner_id.vat
                    or move.commercial_partner_id.vat == "/"
                )
            ):
                raise UserError(
                    self.env._(
                        "You are trying to confirm the invoice '%(move)s' that has "
                        "an Intra-EU B2B fiscal position and "
                        "this type of fiscal position require the customer/supplier "
                        "to have a VAT number. But the partner '%(partner)s' "
                        "doesn't have a VAT number in Odoo. Please add the VAT number "
                        "of this partner in Odoo and try again.",
                        move=move.display_name,
                        partner=move.commercial_partner_id.display_name,
                    )
                )
        return super()._post(soft=soft)

    def _fr_ctc_split_by_vat_rate(self, rate_dict, speedy):
        # TODO when there is no taxes (auto-entrep)
        self.ensure_one()
        vat_tax_id2rate = speedy["france_vat_tax_id2rate"]
        account2rate = speedy["france_due_vat_account2rate"]
        assert self.journal_id
        if self.move_type in ("out_invoice", "out_refund"):
            # the module account_invoice_en16931 ensures that
            # there is exactly 1 VAT tax per invoice line
            for iline in self.invoice_line_ids:
                if iline.display_type == "product":
                    for tax in iline.tax_ids:
                        if tax.id in vat_tax_id2rate:
                            rate_int = vat_tax_id2rate[tax.id]
                            base_line = (
                                self._prepare_product_base_line_for_taxes_computation(
                                    iline
                                )
                            )
                            speedy["at_obj"]._add_tax_details_in_base_line(
                                base_line, self.company_id
                            )
                            rate_dict[rate_int] += base_line["tax_details"][
                                "raw_total_included_currency"
                            ]
                            break
        else:
            for line in self.line_ids:
                if line.account_id in account2rate:
                    rate_int = account2rate[line.account_id]
                    base_tax_incl = -1 * line.balance * (10000 / rate_int + 1)
                    rate_dict[rate_int] += base_tax_incl
                if line.account_id in speedy["income_untaxed_accounts"]:
                    rate_dict[0] += line.balance * -1
