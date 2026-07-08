# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models
from odoo.tools import float_compare
from odoo.tools.misc import formatLang


class AccountTax(models.Model):
    _inherit = "account.tax"

    def _en16931_check_sale_tax(self):
        self.ensure_one()
        errors = []
        amount_fc = float_compare(self.amount, 0, precision_digits=4)
        if not self.unece_type_id:
            errors.append(
                self.env._("Tax '%s' has no UNECE Tax Type.", self.display_name)
            )
        elif self.unece_type_code == "VAT":
            if self.amount_type != "percent":
                errors.append(
                    self.env._(
                        "VAT tax '%(tax)s' has Tax Computation set to "
                        "'%(amount_type)s', but all VAT taxes should have "
                        "Tax Computation set to 'Percentage'.",
                        tax=self.display_name,
                        amount_type=dict(
                            self._fields["amount_type"]._description_selection(self.env)
                        ).get(self.amount_type),
                    )
                )
            if self.amount > 30:
                # the maxium known VAT rate in the world is 27%
                errors.append(
                    self.env._(
                        "VAT tax '%(tax)s' has a rate of %(rate)s %%, which is above "
                        "the known maximum VAT rate in the world. There is certainly "
                        "a mistake in the rate.",
                        tax=self.display_name,
                        rate=formatLang(self.env, self.amount, digits=4),
                    )
                )
            if not self.unece_categ_id:
                errors.append(
                    self.env._(
                        "VAT tax '%s' has no UNECE Tax Category.", self.display_name
                    )
                )
            elif self.unece_categ_code == "S":
                if amount_fc <= 0:
                    errors.append(
                        self.env._(
                            "VAT tax '%(tax)s' has UNECE Tax Category '%(categ)s' "
                            "so it's rate (%(rate)s) should be strictly positive.",
                            tax=self.display_name,
                            categ=self.unece_categ_id.display_name,
                            rate=formatLang(self.env, self.amount, digits=4),
                        )
                    )
                if self.unece_vatex_id:
                    errors.append(
                        self.env._(
                            "VAT tax '%(tax)s' has UNECE Tax Category '%(categ)s' "
                            "so it should not have a VAT Exemption Reason.",
                            tax=self.display_name,
                            categ=self.unece_categ_id.display_name,
                        )
                    )
            elif self.unece_categ_code not in ("S", "Z"):
                if amount_fc:
                    errors.append(
                        self.env._(
                            "VAT tax '%(tax)s' has UNECE Tax Category '%(categ)s' "
                            "so it's rate (%(rate)s) should be null.",
                            tax=self.display_name,
                            categ=self.unece_categ_id.display_name,
                            rate=formatLang(self.env, self.amount, digits=4),
                        )
                    )
                if not self.unece_vatex_id:
                    errors.append(
                        self.env._(
                            "VAT tax '%(tax)s' has UNECE Tax Category '%(categ)s' "
                            "so it should have a VAT Exemption Reason.",
                            tax=self.display_name,
                            categ=self.unece_categ_id.display_name,
                        )
                    )
        else:
            if amount_fc < 0:
                errors.append(
                    self.env._(
                        "Tax '%(tax)s' has a negative rate (%(rate)s). "
                        "This is not supported by the community implementation of "
                        "EN16931 for the moment.",
                        tax=self.display_name,
                        rate=formatLang(self.env, self.amount, digits=4),
                    )
                )
            if not self.include_base_amount:
                errors.append(
                    self.env._(
                        "Tax '%(tax)s' is not a VAT tax and is "
                        "not configured with the option 'Affect Base of "
                        "Subsequent Taxes'. This is not supported by the community "
                        "implementation of EN16931 for the moment.",
                        tax=self.display_name,
                    )
                )
        return errors
