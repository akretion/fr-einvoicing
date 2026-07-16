# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    en16931_default_pdf_invoice = fields.Selection(
        [
            ("facturx", "Factur-X"),
            ("facturx_ubl", "Factur-X with additional UBL XML attachment"),
            ("pdf_ubl", "PDF invoice with UBL XML attachment"),
            ("none", "Regular PDF invoice"),
        ],
        default="facturx",
        string="Default PDF Invoice Generation",
    )
    no_vat_taxes = fields.Boolean(
        compute="_compute_no_vat_taxes", string="Company has no VAT Taxes"
    )
    no_vat_taxes_vatex_id = fields.Many2one(
        "unece.code.list",
        string="Company VAT Exemption Reason",
        domain=[("type", "=", "tax_vatex")],
        ondelete="restrict",
    )
    # TODO add field to choose between Factur-X and UBL

    def _compute_no_vat_taxes(self):
        # On 16.0, read_group() returns dicts and the count is exposed as
        # <groupby>_count: the 18.0 signature (groupby=, aggregates=) and its
        # recordset results do not exist yet.
        rg_res = self.env["account.tax"].read_group(
            [("company_id", "in", self.ids), ("unece_type_code", "=", "VAT")],
            ["company_id"],
            ["company_id"],
        )
        mapped_data = {
            x["company_id"][0]: x["company_id_count"] for x in rg_res if x["company_id"]
        }
        for company in self:
            company.no_vat_taxes = not bool(mapped_data.get(company.id, 0))

    def _en16931_checks(self):
        sale_taxes = self.env["account.tax"].search(
            [("company_id", "=", self.id), ("type_tax_use", "=", "sale")]
        )
        errors = []
        for tax in sale_taxes:
            errors += tax._en16931_check_sale_tax()
        dpo = self.env["decimal.precision"]
        price_prec = dpo.precision_get("Product Price")
        # Source : AFNOR XP Z12-012 PDF, section 4.4.1 Types de données
        # "Il n'y a pas de règle de nombre de décimales, mais l'usage et surtout la
        # révision de la norme EN16931 limitent les prix unitaires à 4 décimales"
        if price_prec > 4:
            errors.append(
                _(
                    "Price decimal precision is %s. For EN16931, "
                    "the maximum value is 4."
                )
                % price_prec
            )
        qty_prec = dpo.precision_get("Product Unit of Measure")
        if qty_prec > 4:
            errors.append(
                _(
                    "Product Unit of Measure decimal precision is %s. For EN16931, "
                    "the maximum value is 4."
                )
                % qty_prec
            )
        disc_prec = dpo.precision_get("Discount")
        if disc_prec > 2:
            errors.append(
                _(
                    "Discount decimal precision is %s. For EN16931, the maximum "
                    "value is 2."
                )
                % disc_prec
            )
        if errors:
            raise UserError(
                _(
                    "The following errors have been detected in company %(company)s "
                    "that block EN16931 e-invoicing:\n%(err_msg)s"
                )
                % {
                    "company": self.display_name,
                    "err_msg": "\n".join([f"- {error}" for error in errors]),
                }
            )
