# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import logging
from collections import defaultdict
from datetime import timedelta
from pprint import pformat

from dateutil.relativedelta import relativedelta
from markupsafe import Markup
from unidecode import unidecode

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_amount, format_date, formatLang

logger = logging.getLogger(__name__)


try:
    from pyfrctc import generate_ereporting_payments, generate_ereporting_transactions
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc")
    logger.debug(err)

TRANSMISSION_TYPE_CODE = {
    "initial": "IN",
    "corrective": "CO",
}


class FrEreporting(models.Model):
    _name = "fr.ereporting"
    _description = "eReporting for France"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "end_date desc, id desc"

    start_date = fields.Date(
        required=True,
        tracking=True,
        compute="_compute_start_date",
        store=True,
        readonly=False,
    )
    end_date = fields.Date(tracking=True, compute="_compute_end_date", store=True)
    deadline_date = fields.Date(
        compute="_compute_end_date", store=True, string="Deadline"
    )
    identifier = fields.Char(readonly=True)
    type = fields.Selection(
        [
            ("out_transaction", "Sale Transactions"),
            ("in_transaction", "Purchase Transactions"),
            ("payment", "Payments"),
        ],
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    vat_periodicity = fields.Selection(
        "_vat_periodicity_selection",
        compute="_compute_vat_periodicity",
        store=True,
        string="VAT Periodicity",
    )
    flow_id = fields.Many2one(
        "fr.einvoicing.flow", readonly=True, copy=False, tracking=True
    )
    flow_state = fields.Selection(
        related="flow_id.state", store=True, string="Flow State"
    )
    move_ids = fields.One2many(
        "account.move", "fr_ereporting_id", string="Invoices", readonly=True
    )
    transaction_ids = fields.One2many(
        "fr.ereporting.transaction",
        "fr_ereporting_id",
        string="Transactions",
        readonly=True,
    )
    payment_ids = fields.One2many(
        "fr.ereporting.payment", "fr_ereporting_id", string="Payments", readonly=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Sent"),
        ],
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    generated = fields.Boolean(readonly=True, copy=False)
    transmission_type = fields.Selection(
        [
            ("initial", "Initial"),  # IN
            ("corrective", "Corrective"),  # RE # Rectificatif in French
            # Not used for PPF, but still allowed between company and AP ?
            # ('CO', 'Complementary'),
            # ('MO', 'Modification'),
        ],
        required=True,
        default="initial",
        copy=False,
        tracking=True,
    )
    # TT-4 Transmission Type Code
    sent_datetime = fields.Datetime(
        string="Sent Date", related="flow_id.submitted_at", store=True
    )
    vat_on_payment_option = fields.Selection(
        [
            ("native", "Native Odoo"),
            ("non_native", "Non-native (recommended)"),
        ],
        compute="_compute_vat_on_payment_option",
        store=True,
        string="VAT on Payment Option",
    )
    warning = fields.Html(readonly=True, copy=False)

    _sql_constraints = [
        (
            "identifier_company_uniq",
            "unique(identifier, company_id)",
            "An eReporting with the same identifier already exists!",
        ),
        (
            "start_type_company_uniq",
            "unique(start_date, type, company_id)",
            "An eReporting with the same type and same start date already "
            "exists in this company.",
        ),
    ]

    @api.model
    def _vat_periodicity_selection(self):
        return self.env["res.company"]._fr_vat_periodicity_selection()

    @api.depends("company_id")
    def _compute_vat_periodicity(self):
        for rec in self:
            rec.vat_periodicity = rec.company_id.fr_vat_periodicity or False

    @api.depends("company_id", "type")
    def _compute_start_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            start_date = False
            if rec.company_id and rec.type:
                vat_periodicity = rec.company_id.fr_vat_periodicity or False
                last_ereporting = self.search(
                    [("company_id", "=", rec.company_id.id), ("type", "=", rec.type)],
                    limit=1,
                    order="start_date desc",
                )
                if last_ereporting:
                    start_date = last_ereporting.end_date + timedelta(1)
                else:
                    if vat_periodicity == "1":
                        if rec.type == "payment":
                            start_date = today + relativedelta(months=-1, day=1)
                        else:
                            if today.day <= 10:
                                start_date = today + relativedelta(months=-1, day=21)
                            elif today.day <= 20:
                                start_date = today + relativedelta(day=1)
                            else:
                                start_date = today + relativedelta(day=11)
                    elif vat_periodicity in ("3", "12"):
                        start_date = today + relativedelta(months=-1, day=1)
                    elif not vat_periodicity:
                        if today.month % 2 == 0:  # feb, april
                            delta_months = -3
                        else:  # january, march
                            delta_months = -2
                        start_date = today + relativedelta(months=delta_months, day=1)
            rec.start_date = start_date

    @api.depends("start_date", "company_id", "type")
    def _compute_end_date(self):
        for rec in self:
            end_date = False
            deadline = False
            start_date = rec.start_date
            if start_date and rec.type and rec.company_id:
                vat_periodicity = rec.company_id.fr_vat_periodicity or False
                if vat_periodicity == "1":
                    if rec.type == "payment":
                        end_date = start_date + relativedelta(day=31)
                        deadline = start_date + relativedelta(months=1, day=10)
                    else:
                        if start_date.day == 1:
                            end_date = start_date + relativedelta(day=10)
                            deadline = start_date + relativedelta(day=20)
                        elif start_date.day == 11:
                            end_date = start_date + relativedelta(day=20)
                            deadline = start_date + relativedelta(day=31)
                        elif start_date.day == 21:
                            end_date = start_date + relativedelta(day=31)
                            deadline = start_date + relativedelta(months=1, day=10)
                elif vat_periodicity == "3":
                    end_date = start_date + relativedelta(day=31)
                    deadline = start_date + relativedelta(months=1, day=10)
                elif vat_periodicity == "12":
                    end_date = start_date + relativedelta(day=31)
                    deadline = start_date + relativedelta(months=1, day=31)
                elif not vat_periodicity:
                    end_date = start_date + relativedelta(months=1, day=31)
                    deadline = start_date + relativedelta(months=2, day=31)
            rec.end_date = end_date
            rec.deadline_date = deadline

    @api.depends("company_id")
    def _compute_vat_on_payment_option(self):
        for rec in self:
            option = "non_native"
            if rec.company_id.tax_exigibility:
                option = "native"
            rec.vat_on_payment_option = option

    @api.depends("start_date", "end_date", "type")
    def _compute_display_name(self):
        type2label = dict(self._fields["type"]._description_selection(self.env))
        transmission_type2label = dict(
            self._fields["transmission_type"]._description_selection(self.env)
        )
        for rec in self:
            name = ""
            if rec.type and rec.start_date and rec.end_date:
                name = (
                    f"{type2label[rec.type]} "
                    f"{format_date(self.env, rec.start_date)} → "
                    f"{format_date(self.env, rec.end_date)}"
                )
            if rec.transmission_type == "corrective":
                name += f" ({transmission_type2label['corrective']}"
            rec.display_name = name

    @api.constrains("start_date", "type", "company_id")
    def _check_start_date(self):
        for rec in self:
            if rec.type and rec.company_id and rec.start_date:
                vat_periodicity = rec.company_id.fr_vat_periodicity or False
                start_day = rec.start_date.day
                start_month = rec.start_date.month
                if vat_periodicity == "1":
                    if rec.type == "payment":
                        if start_day != 1:
                            raise ValidationError(
                                self.env._(
                                    "When VAT Periodicity is Monthly, the start date "
                                    "of a Payments e-Reporting must be the "
                                    "first day of a month."
                                )
                            )
                    else:
                        if start_day not in (1, 11, 21):
                            raise ValidationError(
                                self.env._(
                                    "When VAT Periodicity is Monthly, the start date "
                                    "of a Transactions e-Reporting must be the "
                                    "first day of a month, the 11th or the 21st."
                                )
                            )
                elif vat_periodicity in ("3", "12"):
                    if start_day != 1:
                        raise ValidationError(
                            self.env._(
                                "When VAT Periodicity is Quarterly or Yearly, "
                                "the start date must be the first day of a month."
                            )
                        )
                elif not vat_periodicity:
                    if start_day != 1 or start_month % 2 == 0:
                        raise ValidationError(
                            self.env._(
                                "When VAT Periodicity has no value, "
                                "the start date must January 1st, March 1st, "
                                "May 1st, July 1st, September 1st or November 1st "
                                "(first day of a two-month period)."
                            )
                        )

    @api.constrains("start_date", "type", "transmission_type", "company_id")
    def _check_ereporting(self):
        for rec in self:
            if rec.transmission_type == "initial":
                if self.search_count(
                    [
                        ("start_date", "=", rec.start_date),
                        ("type", "=", rec.type),
                        ("transmission_type", "=", "initial"),
                        ("company_id", "=", rec.company_id.id),
                        ("id", "!=", rec.id),
                    ]
                ):
                    raise ValidationError(
                        self.env._(
                            "This declaration already exists. But you can create a "
                            "corrective declaration to replace it."
                        )
                    )
            elif rec.transmission_type == "corrective":
                if not self.search_count(
                    [
                        ("start_date", "=", rec.start_date),
                        ("type", "=", rec.type),
                        ("transmission_type", "=", "initial"),
                        ("company_id", "=", rec.company_id.id),
                        ("id", "!=", rec.id),
                    ]
                ):
                    raise ValidationError(
                        self.env._(
                            "You are creating a corrective declaration, but there "
                            "is no initial declaration of the same type "
                            "on the same period."
                        )
                    )

    def unlink(self):
        for rec in self:
            if rec.state == "sent":
                raise UserError(
                    self.env._(
                        "Cannot delete %s because it has already been sent.",
                        rec.display_name,
                    )
                )
        return super().unlink()

    def _prepare_speedy(self):
        self.ensure_one()
        company = self.company_id
        vat_return_obj = self.env["l10n.fr.account.vat.return"]
        last_vat_return = vat_return_obj.search(
            [("company_id", "=", company.id), ("state", "!=", "manual")],
            order="start_date desc",
        )
        if not last_vat_return:
            raise UserError(
                self.env._(
                    "You are not using the OCA VAT return module for France "
                    "in company '%s'. The community e-reporting module for France "
                    "implies that you use the OCA VAT return module for France.",
                    company.display_name,
                )
            )
        speedy = last_vat_return._prepare_speedy()
        income_untaxed_accounts = speedy["aa_obj"]
        sale_account_types = ["income", "income_other", "liability_current"]
        # TODO move to l10n_fr_account_vat_return
        for fposition in speedy["afp_obj"].search(
            [("company_id", "=", company.id), ("fr_vat_type", "=", "france_exo")]
        ):
            revenue_account_mappings = fposition.account_ids.filtered(
                lambda x: x.account_src_id.account_type in sale_account_types
                and x.account_dest_id.account_type in sale_account_types
            )
            for mapping in revenue_account_mappings:
                income_untaxed_accounts |= mapping.account_dest_id
        speedy["income_untaxed_accounts"] = income_untaxed_accounts
        move_action_id = self.env.ref("account.action_move_journal_line").id
        speedy["move_path_prefix"] = f"/odoo/action-{move_action_id}"
        return speedy

    def generate_button(self):
        self.ensure_one()
        company = self.company_id
        self.message_post(body=self.env._("Generating e-Reporting."))
        if company.currency_id.name != "EUR":
            raise UserError(
                self.env._(
                    "The currency of company '%s' is not euro.", company.display_name
                )
            )
        if not company.fr_ctc_accredited_platform:
            raise UserError(
                self.env._(
                    "No accredited platform selected for company '%s'.",
                    company.display_name,
                )
            )
        if not company._fr_ctc_is_vat_registered(raise_if_misconfigured=True):
            raise UserError(
                self.env._(
                    "Company '%s' is not a VAT registered company.",
                    company.display_name,
                )
            )
        self.transaction_ids.unlink()
        self.payment_ids.unlink()
        self.move_ids.write({"fr_ereporting_id": False})
        # if it's "corrective", we must remove links with previous reports
        speedy = self._prepare_speedy()
        if self.type in ("in_transaction", "out_transaction"):
            self._generate_transaction(speedy)
        elif self.type == "payment":
            self._generate_payment(speedy)

    def _prepare_out_b2c_transactions(self, speedy):  # noqa: C901
        self.ensure_one()
        company = self.company_id
        company_cur = company.currency_id
        #        logger.debug(pformat(speedy['france_due_vat_account2rate']))
        france_tax2rate = {}
        regular_due_vat_taxes = speedy["at_obj"].search(
            speedy["sale_regular_vat_tax_domain"]
        )
        for tax in regular_due_vat_taxes:
            rate_int = int(round(tax.amount * 100))
            france_tax2rate[tax] = rate_int
        ml_domain = [
            ("company_id", "=", company.id),
            ("date", ">=", self.start_date),
            ("date", "<=", self.end_date),
            ("parent_state", "=", "posted"),
            ("move_id.fr_einvoicing_flow_id", "=", False),
            ("move_id.fr_ereporting_id", "=", False),
            ("journal_id.type", "=", "sale"),
        ]
        trans2rate2vals = {}  # key = (date, categ, currency ID, vat_exigibility)
        # value = {vat_rate_int: vat_amount}
        _option = self.vat_on_payment_option
        pct_digits = 2
        # TODO implement option = "native"
        for vat_account, vat_rate_int in speedy["france_due_vat_account2rate"].items():
            mlines = speedy["aml_obj"].search(
                ml_domain + [("account_id", "=", vat_account.id)]
            )
            for mline in mlines:
                move = mline.move_id
                if move.out_vat_on_payment:
                    vat_exigibility = "payment"
                else:
                    vat_exigibility = "invoice"
                total = 0.0
                product_subtotal = 0.0
                if move.is_invoice:
                    other_lines = move.invoice_line_ids.filtered(
                        lambda x: x.display_type == "product"
                    )
                else:
                    other_lines = speedy["aml_obj"]
                    for oline in move.line_ids:
                        if (
                            oline.id != mline.id
                            and oline.account_id.account_type.startswith(
                                ("expense", "income")
                            )
                        ):
                            other_lines |= oline
                for oline in other_lines:
                    for tax in oline.tax_ids:
                        if (
                            tax in france_tax2rate
                            and france_tax2rate[tax] == vat_rate_int
                        ):
                            total += oline.balance
                            product_or_service = oline._fr_is_product_or_service()
                            if product_or_service == "product":
                                product_subtotal += oline.balance
                            break
                vat_amount = company_cur.round(mline.balance * -1)
                vat_amount_fmt = format_amount(self.env, vat_amount, company_cur)
                ml_path = f"/odoo/fr-ereporting-journal-item/{mline.id}"
                mline_url = f"""<a href="{ml_path}">{mline.display_name}</a>"""
                product_srv_split = []
                if not product_subtotal:
                    note = self.env._(
                        "%(mline_url)s VAT Amount %(vat_amount_fmt)s ; 100%% services",
                        mline_url=mline_url,
                        vat_amount_fmt=vat_amount_fmt,
                    )
                    product_srv_split.append(("TPS1", vat_amount, note))
                elif not company_cur.compare_amounts(total, product_subtotal):
                    note = self.env._(
                        "%(mline_url)s VAT Amount %(vat_amount_fmt)s ; 100%% goods",
                        mline_url=mline_url,
                        vat_amount_fmt=vat_amount_fmt,
                    )
                    product_srv_split.append(("TLB1", vat_amount, note))
                else:
                    product_pct = 100 * product_subtotal / total
                    product_pct_fmt = formatLang(
                        self.env, product_pct, digits=pct_digits
                    )
                    product_vat_amount = company_cur.round(
                        vat_amount * product_subtotal / total
                    )
                    product_vat_amount_fmt = format_amount(
                        self.env, product_vat_amount, company_cur
                    )
                    product_note = self.env._(
                        "%(mline_url)s Total VAT Amount %(vat_amount_fmt)s ; "
                        "%(product_pct_fmt)s%% goods → VAT Amount "
                        "%(product_vat_amount_fmt)s",
                        mline_url=mline_url,
                        vat_amount_fmt=vat_amount_fmt,
                        product_pct_fmt=product_pct_fmt,
                        product_vat_amount_fmt=product_vat_amount_fmt,
                    )
                    product_srv_split.append(("TLB1", product_vat_amount, product_note))
                    service_vat_amount = vat_amount - product_vat_amount
                    service_pct = 100 - product_pct
                    service_pct_fmt = formatLang(
                        self.env, service_pct, digits=pct_digits
                    )
                    service_vat_amount_fmt = format_amount(
                        self.env, service_vat_amount, company_cur
                    )
                    srv_note = self.env._(
                        "%(mline_url)s Total VAT Amount %(vat_amount_fmt)s ; "
                        "%(service_pct_fmt)s%% services → VAT Amount "
                        "%(service_vat_amount_fmt)s",
                        mline_url=mline_url,
                        vat_amount_fmt=vat_amount_fmt,
                        service_pct_fmt=service_pct_fmt,
                        service_vat_amount_fmt=service_vat_amount_fmt,
                    )
                    product_srv_split.append(("TPS1", service_vat_amount, srv_note))

                currency_id = move.currency_id.id
                for category, vat_amount, note in product_srv_split:
                    key = (mline.date, category, currency_id, vat_exigibility)
                    if key not in trans2rate2vals:
                        trans2rate2vals[key] = {}
                    if vat_rate_int not in trans2rate2vals[key]:
                        trans2rate2vals[key][vat_rate_int] = {
                            "vat_amount": 0.0,
                            "notes": [],
                        }
                    trans2rate2vals[key][vat_rate_int]["vat_amount"] += vat_amount
                    trans2rate2vals[key][vat_rate_int]["notes"].append(note)
        # VAT 0%
        vat_rate_int = 0
        mlines = speedy["aml_obj"].search(
            ml_domain + [("account_id", "in", speedy["income_untaxed_accounts"].ids)]
        )
        for mline in mlines:
            move = mline.move_id
            if move.out_vat_on_payment:
                vat_exigibility = "payment"
            else:
                vat_exigibility = "invoice"
            currency_id = move.currency_id.id
            product_or_service = mline._fr_is_product_or_service()
            if product_or_service == "product":
                category = "TLB1"
                category_fmt = self.env._("Goods")
            else:
                category = "TPS1"
                category_fmt = self.env._("Services")
            key = (mline.date, category, currency_id, vat_exigibility)
            if key not in trans2rate2vals:
                trans2rate2vals[key] = {}
            if vat_rate_int not in trans2rate2vals[key]:
                trans2rate2vals[key][vat_rate_int] = {
                    "base_amount": 0.0,
                    "notes": [],
                }
            base_amount = company_cur.round(mline.balance * -1)
            trans2rate2vals[key][vat_rate_int]["base_amount"] += base_amount
            ml_path = f"/odoo/fr-ereporting-journal-item/{mline.id}"
            mline_url = f"""<a href="{ml_path}">{mline.display_name}</a>"""
            base_amount_fmt = format_amount(self.env, base_amount, company_cur)
            note = self.env._(
                "%(mline_url)s Base Amount %(base_amount_fmt)s ; %(category_fmt)s",
                mline_url=mline_url,
                base_amount_fmt=base_amount_fmt,
                category_fmt=category_fmt,
            )
            trans2rate2vals[key][vat_rate_int]["notes"].append(note)
        return trans2rate2vals

    def _generate_transaction(self, speedy):
        self.ensure_one()
        company = self.company_id
        company_cur = company.currency_id
        move_domain = [
            ("company_id", "=", company.id),
            ("date", ">=", self.start_date),
            ("date", "<=", self.end_date),
            ("state", "=", "posted"),
            ("fr_einvoicing_flow_id", "=", False),
            ("fiscal_position_fr_vat_type", "in", ("intracom_b2b", "extracom")),
        ]
        if self.type == "in_transaction":
            move_domain.append(("move_type", "in", ("in_invoice", "in_refund")))
        elif self.type == "out_transaction":
            move_domain.append(("move_type", "in", ("out_invoice", "out_refund")))
        invoices = self.env["account.move"].search(move_domain)
        invoices.write({"fr_ereporting_id": self.id})
        wvals = {"generated": True, "transaction_ids": []}
        # generate "transaction" object
        if self.type == "out_transaction":
            trans2rate2vals = self._prepare_out_b2c_transactions(speedy)
            for (
                date,
                category,
                currency_id,
                vat_exigibility,
            ), rate2amounts in trans2rate2vals.items():
                tvals = {
                    "date": date,
                    "category": category,
                    "currency_id": currency_id,
                    "vat_exigibility": vat_exigibility,
                    "vat_amount": 0.0,
                    "base_amount": 0.0,  # company currency
                    "rate_ids": [],
                }
                for vat_rate_int, amounts in rate2amounts.items():
                    if vat_rate_int:
                        vat_amount = amounts["vat_amount"]
                        base_amount = company_cur.round(
                            vat_amount * 10000 / vat_rate_int
                        )
                        base_amount_fmt = format_amount(
                            self.env, base_amount, company_cur
                        )
                        vat_amount_fmt = format_amount(
                            self.env, vat_amount, company_cur
                        )
                        vat_rate_fmt = formatLang(
                            self.env, vat_rate_int / 100, digits=1
                        )
                        amounts["notes"].append(
                            self.env._(
                                "<strong>Base Amount</strong> = "
                                "VAT Amount %(vat_amount_fmt)s / VAT Rate "
                                "%(vat_rate_fmt)s%% = %(base_amount_fmt)s",
                                base_amount_fmt=base_amount_fmt,
                                vat_amount_fmt=vat_amount_fmt,
                                vat_rate_fmt=vat_rate_fmt,
                            )
                        )
                    else:
                        base_amount = amounts["base_amount"]
                        vat_amount = 0
                    tvals["rate_ids"].append(
                        Command.create(
                            {
                                "vat_amount": vat_amount,
                                "base_amount": base_amount,
                                "vat_rate": vat_rate_int / 100,
                                "note": Markup("<br>".join(amounts["notes"])),
                            }
                        )
                    )
                    tvals["vat_amount"] += vat_amount
                    tvals["base_amount"] += base_amount
                wvals["transaction_ids"].append(Command.create(tvals))
        self.write(wvals)

    def _generate_payment(self, speedy):
        self.ensure_one()
        assert self.type == "payment"
        company = self.company_id
        mline_obj = self.env["account.move.line"]
        # 1. get move lines in bank account linked to default_account_id
        default_accounts = self.env["account.account"]
        # I don't put 'credit' because it is not for
        # receiving money from the outside TODO confirm
        journals = self.env["account.journal"].search(
            [
                ("default_account_id", "!=", False),
                ("company_id", "=", company.id),
                ("type", "in", ("cash", "bank")),
            ]
        )
        if not journals:
            raise UserError(
                self.env._(
                    "In company '%s', there is no cash journal nor bank journal.",
                    company.display_name,
                )
            )
        for journal in journals:
            default_account = journal.default_account_id.with_company(company.id)
            if default_account in default_accounts:
                raise UserError(
                    self.env._(
                        "On journal '%(journal)s', the account %(default_account)s "
                        "is also used on another bank or cash journal.",
                        journal=journal.display_name,
                        default_account=default_account.display_name,
                    )
                )
            if (
                default_account.account_type == "asset_cash"
                and not default_account.reconcile
            ):
                default_accounts |= default_account
        logger.info(
            f"Entry point accounts for payment e-reporting: "
            f"{', '.join([acc.code for acc in default_accounts])}"
        )

        mline_domain = [
            ("company_id", "=", company.id),
            ("date", ">=", self.start_date),
            ("date", "<=", self.end_date),
            ("parent_state", "=", "posted"),
            ("journal_id", "in", journals.ids),
            ("balance", "!=", 0.0),
            ("account_id", "in", default_accounts.ids),
        ]
        receivable_account_ids = list(
            self.env["account.account"]._search(
                [
                    ("company_ids", "in", company.id),
                    ("account_type", "=", "asset_receivable"),
                ]
            )
        )
        passthrough_account_ids = list(
            self.env["account.account"]._search(
                [
                    ("company_ids", "in", company.id),
                    ("account_type", "=", "asset_current"),
                    ("reconcile", "=", True),
                ]
            )
        )
        logger.debug(f"passthrough_account_ids={passthrough_account_ids}")
        passthrough_journal_ids = list(
            self.env["account.journal"]._search(
                [
                    ("company_id", "=", company.id),
                    ("type", "in", ("credit", "bank", "cash", "general")),
                ]
            )
        )
        sale_journal_ids = list(
            self.env["account.journal"]._search(
                [("company_id", "=", company.id), ("type", "=", "sale")]
            )
        )
        vat_tax_id2rate = {}
        france_country_id = self.env.ref("base.fr").id
        fr_sale_tax_domain = [
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "sale"),
            ("unece_type_code", "=", "VAT"),
            ("country_id", "=", france_country_id),
            ("amount_type", "=", "percent"),
        ]
        fr_sale_taxes = (
            self.env["account.tax"]
            .with_context(active_test=False)
            .search_read(fr_sale_tax_domain, ["amount"])
        )
        for tax in fr_sale_taxes:
            vat_tax_id2rate[tax["id"]] = int(round(tax["amount"] * 100))
        speedy.update(
            {
                "receivable_account_ids": receivable_account_ids,
                "passthrough_account_ids": passthrough_account_ids,
                "passthrough_journal_ids": passthrough_journal_ids,
                "sale_journal_ids": sale_journal_ids,
                "france_vat_tax_id2rate": vat_tax_id2rate,
            }
        )

        bank_mlines = mline_obj.search(mline_domain)
        wdict = {}  # key = entry point bank move line ID
        sale_move2rate = {}
        # key = sale move record, value = {2000: weight1, 550: weight2}
        for bank_mline in bank_mlines:
            date = bank_mline.date
            wdict[bank_mline.id] = {
                "date": date,
                "payments": {},
                # key = receivable move line ; value: cf _get_related_receivable_lines()
                "parsed_moves": [],
                "ini_notes": [],
            }
            pdict = wdict[bank_mline.id]
            self._get_related_receivable_lines(bank_mline, pdict, speedy)
            first_move, *propag_moves = pdict["parsed_moves"]
            first_move_path = f"{speedy['move_path_prefix']}/{first_move.id}"
            pdict["ini_notes"].append(
                f"""Bank/Cash entry point: """
                f"""<a href="{first_move_path}">{first_move.display_name}</a> """
                f"dated {format_date(self.env, first_move.date)} (→ Payment Date)"
            )
            if propag_moves:
                propag_moves_html = []
                for propag_move in propag_moves:
                    propag_move_path = f"{speedy['move_path_prefix']}/{propag_move.id}"
                    propag_moves_html.append(
                        f'<a href="{propag_move_path}">{propag_move.display_name}</a>'
                    )
                pdict["ini_notes"].append(
                    f"Additional journal entries scanned for Customer Payments: "
                    f"{', '.join(propag_moves_html)}"
                )
            for receivable_mline, rdict in wdict[bank_mline.id]["payments"].items():
                self._payment_split_by_sale(
                    receivable_mline, rdict, sale_move2rate, speedy
                )
        for sale_move, rate_dict in sale_move2rate.items():
            sale_move._fr_ctc_split_by_vat_rate(rate_dict, speedy)
        agg, warning_list = self._aggregate_payment_lines(wdict, sale_move2rate, speedy)
        wvals = self._prepare_payment_lines(agg, warning_list)
        self.write(wvals)

    @api.model
    def _get_related_receivable_lines(self, entry_mline, pdict, speedy):
        move = entry_mline.move_id
        if move in pdict["parsed_moves"]:
            return
        pdict["parsed_moves"].append(move)
        for counterpart_mline in move.line_ids:
            if (
                counterpart_mline == entry_mline
                or counterpart_mline.display_type in ("line_section", "line_note")
                or speedy["currency"].is_zero(entry_mline.balance)
            ):
                continue
            if counterpart_mline.account_id.id in speedy["receivable_account_ids"]:
                #                sign = counterpart_mline.balance < 0 and -1 or 1
                pdict["payments"][counterpart_mline] = {
                    #                    'sign': sign,
                    "amount": counterpart_mline.balance * -1,
                    "split_by_sale": {},  # key = sale move ; value = weight
                    "partner_id": counterpart_mline.partner_id.id or False,
                    "partner_name": counterpart_mline.partner_id
                    and counterpart_mline.partner_id.display_name
                    or False,
                    "reconcile_type": None,
                }
            elif (
                counterpart_mline.account_id.id in speedy["passthrough_account_ids"]
                and counterpart_mline.full_reconcile_id
            ):
                for (
                    rec_mline
                ) in counterpart_mline.full_reconcile_id.reconciled_line_ids:
                    if (
                        rec_mline != counterpart_mline
                        and rec_mline.journal_id.id in speedy["passthrough_journal_ids"]
                        and not speedy["currency"].is_zero(rec_mline.balance)
                    ):
                        self._get_related_receivable_lines(rec_mline, pdict, speedy)

    @api.model
    def _payment_split_by_sale(self, receivable_mline, rdict, sale_move2rate, speedy):
        if receivable_mline.full_reconcile_id:
            for (
                counterpart_mline
            ) in receivable_mline.full_reconcile_id.reconciled_line_ids:
                if (
                    counterpart_mline != receivable_mline
                    and counterpart_mline.journal_id.id in speedy["sale_journal_ids"]
                    and not speedy["currency"].is_zero(counterpart_mline.balance)
                ):
                    sale_move = counterpart_mline.move_id
                    rdict["split_by_sale"][sale_move] = counterpart_mline.balance
                    rdict["reconcile_type"] = "full"
                    sale_move2rate[sale_move] = defaultdict(float)
        else:
            for prec in receivable_mline.matched_debit_ids:
                if (
                    prec.debit_move_id
                    and prec.debit_move_id.journal_id.id in speedy["sale_journal_ids"]
                    and not speedy["currency"].is_zero(prec.amount)
                ):
                    sale_move = prec.debit_move_id.move_id
                    rdict["split_by_sale"][sale_move] = prec.amount
                    rdict["reconcile_type"] = "partial"
                    sale_move2rate[sale_move] = defaultdict(float)
            for prec in receivable_mline.matched_credit_ids:
                if (
                    prec.credit_move_id
                    and prec.credit_move_id.journal_id.id in speedy["sale_journal_ids"]
                    and not speedy["currency"].is_zero(prec.amount)
                ):
                    sale_move = prec.credit_move_id.move_id
                    rdict["split_by_sale"][sale_move] = prec.amount
                    rdict["reconcile_type"] = "partial"
                    sale_move2rate[sale_move] = defaultdict(float)

    def _aggregate_payment_lines(self, wdict, sale_move2rate, speedy):
        def aggregate_payment(agg, date, move_id, notes, rate2amount):
            if (date, move_id) not in agg:
                agg[(date, move_id)] = {
                    "notes": [],
                    "rate2amount": defaultdict(float),
                }
            agg[(date, move_id)]["notes"] += notes
            for rate_int, amount in rate2amount.items():
                agg[(date, move_id)]["rate2amount"][rate_int] += amount

        def split_by_rate(pay_amount, rate_dict):
            rate2amount = {}
            if not rate_dict:
                rate2amount[0] = pay_amount
            else:
                total_prorata_amount = 0.0
                total_weight = sum(rate_dict.values())
                *rate_dict_prorata, (last_rate_int, _last_weight) = rate_dict.items()
                for rate_int, weight in rate_dict_prorata:
                    amount = speedy["currency"].round(
                        pay_amount * weight / total_weight
                    )
                    total_prorata_amount += amount
                    rate2amount[rate_int] = amount
                rate2amount[last_rate_int] = pay_amount - total_prorata_amount
            return rate2amount

        def prepare_sale_note(sale_move, sale_weight, sale_move2rate, rdict, speedy):
            rate_dict = sale_move2rate[sale_move]
            sale_move_path = f"{speedy['move_path_prefix']}/{sale_move.id}"
            sale_move_link = (
                f"""<a href="{sale_move_path}">{sale_move.display_name}</a>"""
            )
            rate_list = [
                f"VAT {formatLang(self.env, round(rate_int/100, 1), digits=1)}% "
                f"weight {format_amount(self.env, weight, speedy['currency'])}"
                for rate_int, weight in rate_dict.items()
            ]
            split_rate_note = f"Its VAT rate composition is: {', '.join(rate_list)}"
            sale_move_type_note = (
                sale_move.is_invoice()
                and "Customer Invoice/Refund"
                or "Sale Journal Entry"
            )
            sale_note = (
                f"{rdict['reconcile_type'] == 'full' and 'Fully' or 'Partially'} "
                f"reconciled with {sale_move_type_note} {sale_move_link} weight "
                f"{format_amount(self.env, sale_weight, speedy['currency'])}. "
                f"{split_rate_note}"
            )
            return sale_note

        warning_list = []
        # Here, I must aggregate all payments of the same day that are not linked to
        # an invoice
        agg = {}
        # key = (date, sale_move)
        # value = {
        # 'notes': ['comment1', 'comment2'],
        # 'byrate': {20000: 330.00, 55000: 12.42}}

        for _bank_mline_id, pdict in wdict.items():
            date = pdict["date"]
            for pay_mline, rdict in pdict["payments"].items():
                total_amount = rdict["amount"]
                total_prorata_amount = 0.0
                total_weight = sum(rdict["split_by_sale"].values())
                if not rdict["split_by_sale"]:
                    if rdict["partner_name"]:
                        partner = self.env._(
                            "of partner <em>%(partner)s</em>",
                            partner=rdict["partner_name"],
                        )
                    else:
                        partner = self.env._("(no partner)")

                    warning_list.append(
                        self.env._(
                            "Customer payment of %(amount)s dated %(date)s "
                            "%(partner)s is skipped because it is not reconciled "
                            "with a sale journal entry, so we can't know the "
                            "VAT rate(s).",
                            amount=format_amount(
                                self.env, total_amount, speedy["currency"]
                            ),
                            date=format_date(self.env, date),
                            partner=partner,
                        )
                    )
                    continue
                pay_ml_path = f"/odoo/fr-ereporting-journal-item/{pay_mline.id}"
                pay_mline_url = (
                    f"""<a href="{pay_ml_path}">{pay_mline.display_name}</a>"""
                )
                if pay_mline.partner_id:
                    partner_note = f"partner {pay_mline.partner_id.display_name}"
                else:
                    partner_note = "(no partner)"
                pay_mline_note = (
                    f"Payment Journal Item: {pay_mline_url} dated "
                    f"{format_date(self.env, pay_mline.date)} amount "
                    f"{format_amount(self.env, total_amount, speedy['currency'])} "
                    f"{partner_note}"
                )
                *sale_dict_prorata, (last_sale_move, last_weight) = rdict[
                    "split_by_sale"
                ].items()
                for sale_move, weight in sale_dict_prorata:
                    pay_amount = speedy["currency"].round(
                        total_amount * weight / total_weight
                    )
                    total_prorata_amount += pay_amount
                    move_id = sale_move.is_invoice() and sale_move.id or False
                    rate2amount = split_by_rate(pay_amount, sale_move2rate[sale_move])
                    sale_note = prepare_sale_note(
                        sale_move, weight, sale_move2rate, rdict, speedy
                    )
                    notes = pdict["ini_notes"] + [pay_mline_note, sale_note]
                    aggregate_payment(agg, date, move_id, notes, rate2amount)
                # process last sale
                pay_amount = total_amount - total_prorata_amount

                move_id = last_sale_move.is_invoice() and last_sale_move.id or False
                rate2amount = split_by_rate(pay_amount, sale_move2rate[last_sale_move])
                sale_note = prepare_sale_note(
                    last_sale_move, last_weight, sale_move2rate, rdict, speedy
                )
                notes = pdict["ini_notes"] + [pay_mline_note, sale_note]
                aggregate_payment(agg, date, move_id, notes, rate2amount)
        return agg, warning_list

    def _prepare_payment_lines(self, agg, warning_list):
        wvals = {"payment_ids": [], "generated": True, "warning": False}
        for (date, move_id), vdict in agg.items():
            rate_ids = []
            rate_str_list = []
            total_amount = 0.0
            for rate_int, amount in vdict["rate2amount"].items():
                total_amount += amount
                rate = round(rate_int / 100, 2)
                if rate == int(rate):
                    digits = 0
                else:
                    digits = 1
                rate_str = formatLang(self.env, rate, digits=digits)
                rate_str_list.append(f"{rate_str}%")
                rate_ids.append(
                    Command.create(
                        {
                            "vat_rate": rate,
                            "amount": amount,
                        }
                    )
                )
            wvals["payment_ids"].append(
                Command.create(
                    {
                        "date": date,
                        "move_id": move_id,
                        "amount": total_amount,
                        "rate_ids": rate_ids,
                        "rate_label": ", ".join(rate_str_list),
                        "note": "<br>".join(vdict["notes"]),
                    }
                )
            )
        if warning_list:
            wvals["warning"] = Markup(
                f"<ul>{''.join([f'<li>{warn}</li>' for warn in warning_list])}</ul>"
            )
        return wvals

    def _prepare_identifier(self):
        self.ensure_one()
        date_format = "%Y%m%d"
        start_date = self.start_date.strftime(date_format)
        end_date = self.end_date.strftime(date_format)
        trans_type = TRANSMISSION_TYPE_CODE[self.transmission_type]
        suffix = ""
        if self.transmission_type == "corrective":
            corrective_count = self.search_count(
                [
                    ("start_date", "=", self.start_date),
                    ("type", "=", self.type),
                    ("company_id", "=", self.company_id.id),
                    ("state", "=", "sent"),
                    ("id", "!=", self.id),
                    ("transmission_type", "=", "corrective"),
                ]
            )
            suffix = f"-{corrective_count + 1}"

        identifier = f"{self.type}-{start_date}_{end_date}-{trans_type}{suffix}"
        return identifier

    def send_button(self):
        self.ensure_one()
        if not self.generated:
            raise UserError(self.env._("The eReporting hasn't been generated yet!"))
        identifier = self._prepare_identifier()
        if self.type in ("in_transaction", "out_transaction"):
            data_dict = self._prepare_transaction_data_dict(identifier)
            logger.debug("data_dict used to generate transaction FRR XML:")
            logger.debug(pformat(data_dict))
            xml_bytes = generate_ereporting_transactions(data_dict, check_xsd=True)
        elif self.type == "payment":
            data_dict = self._prepare_payment_data_dict(identifier)
            logger.debug("data_dict used to generate payment FRR XML:")
            logger.info(pformat(data_dict))
            xml_bytes = generate_ereporting_payments(data_dict, check_xsd=True)
        flow_vals = self._prepare_flow_vals(identifier, xml_bytes)
        flow = self.env["fr.einvoicing.flow"].sudo().create(flow_vals)
        self.write({"state": "sent", "flow_id": flow.id, "identifier": identifier})
        if self.company_id.fr_ctc_ereporting_update_lock_dates:
            if self.type == "out_transaction" and (
                not self.company_id.sale_lock_date
                or self.company_id.sale_lock_date < self.end_date
            ):
                self.sudo().company_id.write({"sale_lock_date": self.end_date})
                self.message_post(
                    body=self.env._(
                        "Sale Lock Date updated to %s.",
                        format_date(self.env, self.end_date),
                    )
                )
            elif self.type == "in_transaction" and (
                not self.company_id.purchase_lock_date
                or self.company_id.purchase_lock_date < self.end_date
            ):
                self.sudo().company_id.write({"purchase_lock_date": self.end_date})
                self.message_post(
                    body=self.env._(
                        "Purchase Lock Date updated to %s.",
                        format_date(self.env, self.end_date),
                    )
                )

    def _minimize_en16931_dict(self, data_dict):
        to_remove = ["BG-1"]
        for key_to_remove in to_remove:
            if key_to_remove in data_dict:
                data_dict.pop(key_to_remove)

    def _prepare_common_data_dict(self, identifier):
        self.ensure_one()
        company = self.company_id
        ap_key2name = dict(
            self.env["res.company"]
            ._fields["fr_ctc_accredited_platform"]
            ._description_selection(self.env)
        )
        data_dict = {
            "TT-1": identifier,
            "TT-2": f"{company.name} : {self.display_name}",
            "TT-3": fields.Datetime.now(),
            "TT-4": TRANSMISSION_TYPE_CODE[self.transmission_type],
            "TT-8": "PA_MATRICULE",  # will be regenerated by PA
            "TT-7": "0238",
            "TT-9": ap_key2name[self.company_id.fr_ctc_accredited_platform],
            "TT-10": "WK",
            # In the specs, we think we have to put an einvoicing address,
            # but in the example, their write an email...
            "TT-11": "support@superpdp.tech",
            "TT-13": company.partner_id._get_siren(raise_if_none=True),
            "TT-12": "0002",
            "TT-14": company.name,
            "TT-15": self.type == "in_transaction" and "BY" or "SE",
            "TT-16": company.email,
        }
        if self.transmission_type == "corrective":
            previous_domain = [
                ("start_date", "=", self.start_date),
                ("type", "=", self.type),
                ("company_id", "=", company.id),
                ("state", "=", "sent"),
                ("flow_state", "in", ("sent", "done")),
                ("sent_datetime", "!=", False),
                ("id", "!=", self.id),
            ]
            previous = self.search(
                previous_domain + [("transmission_type", "=", "corrective")],
                order="sent_datetime desc",
                limit=1,
            )
            if not previous:
                previous = self.search(
                    previous_domain + [("transmission_type", "=", "initial")], limit=1
                )
            if previous:
                data_dict.update(
                    {
                        "TT-5": previous.identifier,
                        "TT-6": TRANSMISSION_TYPE_CODE[previous.transmission_type],
                    }
                )
        return data_dict

    def _prepare_transaction_data_dict(self, identifier):
        self.ensure_one()
        assert self.type in ("in_transaction", "out_transaction")
        company = self.company_id
        data_dict = self._prepare_common_data_dict(identifier)
        minimize = company.fr_ctc_ereporting_minimize
        data_dict.update(
            {
                "TT-17": self.start_date,
                "TT-18": self.end_date,
                "TG-8": [],  # Invoice transactions B2Bi
                "TG-31": [],  # B2C transactions
            }
        )
        for move in self.move_ids:
            speedy = move._prepare_en16931_speedy()
            inv_dict = move._prepare_en16931_dict(speedy)
            if self.type == "in_transaction":
                # BT-47 and BT-47-1 must be OK because it has the company SIREN
                if move.fiscal_position_fr_vat_type == "intracom_b2b":
                    inv_dict["BT-30"] = inv_dict["BT-31"]  # BT-31 = Seller VAT
                    inv_dict["BT-30-1"] = "0223"
                elif move.fiscal_position_fr_vat_type == "extracom":
                    country_code = inv_dict["BT-40"]
                    seller_name_for_id = unidecode(
                        "".join(x for x in inv_dict["BT-27"] if not x.isspace())
                    ).upper()
                    inv_dict["BT-30"] = f"{country_code}{seller_name_for_id[:16]}"
                    inv_dict["BT-30-1"] = "0227"
            elif self.type == "out_transaction":
                # BT-30 and BT-30-1 must be OK because it has the company SIREN
                if move.fiscal_position_fr_vat_type == "intracom_b2b":
                    inv_dict["BT-47"] = inv_dict["BT-48"]  # BT-48 = Buyer VAT
                    inv_dict["BT-47-1"] = "0223"
                elif move.fiscal_position_fr_vat_type == "extracom":
                    country_code = inv_dict["BT-55"]
                    buyer_name_for_id = unidecode(
                        "".join(x for x in inv_dict["BT-44"] if not x.isspace())
                    ).upper()
                    inv_dict["BT-47"] = f"{country_code}{buyer_name_for_id[:16]}"
                    inv_dict["BT-47-1"] = "0227"
            if minimize:
                self._minimize_en16931_dict(inv_dict)
            data_dict["TG-8"].append(inv_dict)

        if self.type == "out_transaction":
            for trans in self.transaction_ids:
                tg32 = []
                for trans_rate in trans.rate_ids:
                    tg32.append(
                        {
                            "TT-86": f"{trans_rate.vat_rate:.2f}",
                            "TT-87": f"{trans_rate.base_amount:.2f}",
                            "TT-88": f"{trans_rate.vat_amount:.2f}",
                        }
                    )

                data_dict["TG-31"].append(
                    {
                        "TT-77": trans.date,
                        "TT-78": trans.currency_id.name,
                        "TT-80": trans.vat_exigibility,
                        "TT-81": trans.category,
                        "TT-82": f"{trans.base_amount:.2f}",
                        "TT-83": f"{trans.vat_amount:.2f}",
                        "TG-32": tg32,
                    }
                )
        return data_dict

    def _prepare_payment_data_dict(self, identifier):
        self.ensure_one()
        assert self.type in ("payment")
        data_dict = self._prepare_common_data_dict(identifier)
        data_dict.update(
            {
                "TT-89": self.start_date,
                "TT-90": self.end_date,
                "TG-34": [],  # Invoice-related payments
                "TG-37": [],  # payments not linked to an invoice
            }
        )
        for payment in self.payment_ids:
            if payment.move_id:
                tg36 = []
                for pay_rate in payment.rate_ids:
                    tg36.append(
                        {
                            "TT-93": f"{pay_rate.vat_rate:.2f}",
                            "TT-94": "EUR",
                            "TT-95": f"{pay_rate.amount:.2f}",
                        }
                    )
                data_dict["TG-34"].append(
                    {
                        "TT-91": payment.move_id.name,
                        "TT-102": payment.move_id.invoice_date,
                        "TT-92": payment.date,
                        "TG-36": tg36,
                    }
                )
            else:
                tg39 = []
                for pay_rate in payment.rate_ids:
                    tg39.append(
                        {
                            "TT-97": f"{pay_rate.vat_rate:.2f}",
                            "TT-98": "EUR",
                            "TT-99": f"{pay_rate.amount:.2f}",
                        }
                    )
                data_dict["TG-37"].append(
                    {
                        "TT-96": payment.date,
                        "TG-39": tg39,
                    }
                )
        return data_dict

    def _prepare_flow_vals(self, identifier, xml_bytes):
        self.ensure_one()
        if self.type == "out_transaction":
            flow_type = "MultiFlowReport"
        elif self.type == "in_transaction":
            flow_type = "UnitarySupplierTransactionReport"
        elif self.type == "payment":
            flow_type = "UnitaryCustomerPaymentReport"
        vals = {
            "direction": "out",
            "syntax": "FRR",
            "processing_rule": "NotApplicable",  # TODO confirm
            "type": flow_type,
            "company_id": self.company_id.id,
            "file_bin": base64.encodebytes(xml_bytes),
            "filename": f"{identifier}.xml",
            "state": "generated",
        }
        return vals

    def backtodraft_button(self):
        self.ensure_one()
        assert self.state == "sent"
        if self.flow_id.state in ("sent", "done"):
            raise UserError(
                self.env._(
                    "You cannot go back to draft because the flow '%s' "
                    "has already been sent.",
                    self.flow_id.display_name,
                )
            )
        self.sudo().flow_id.unlink()
        self.write(
            {
                "identifier": False,
                "state": "draft",
            }
        )


class FrEreportingTransaction(models.Model):
    _name = "fr.ereporting.transaction"
    _description = "eReporting Transaction for France"
    _order = "fr_ereporting_id, date desc"

    fr_ereporting_id = fields.Many2one(
        "fr.ereporting", ondelete="cascade", index=True, required=True, readonly=True
    )
    company_id = fields.Many2one(related="fr_ereporting_id.company_id", store=True)
    date = fields.Date(required=True, readonly=True)
    category = fields.Selection(
        [
            ("TLB1", "Goods subject to VAT"),
            ("TPS1", "Services subject to VAT"),
            (
                "TNT1",
                "Goods and services not subject to VAT",
            ),
            # TNT1 : Livraisons de biens et prestations de services non soumises
            # à la taxe sur la valeur ajoutée en France dont les ventes
            # à distance intracommunautaires mentionnées au 1° du I de
            # l’article 258 A et à l’article 259 B du code général des impôts
            (
                "TMA1",
                "VAT on margin",
            ),
        ],
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one("res.currency", string="Transaction Currency")
    company_currency_id = fields.Many2one(
        related="fr_ereporting_id.company_id.currency_id", string="Company Currency"
    )
    vat_exigibility = fields.Selection(
        [
            ("invoice", "Based on invoice"),
            ("payment", "Based on payment"),
        ],
        string="VAT Exigibility",
        readonly=True,
    )
    base_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    vat_amount = fields.Monetary(
        currency_field="company_currency_id", string="VAT Amount", readonly=True
    )
    rate_ids = fields.One2many(
        "fr.ereporting.transaction.rate", "fr_ereporting_transaction_id", readonly=True
    )


class FrEreportingTransactionRate(models.Model):
    _name = "fr.ereporting.transaction.rate"
    _description = "Per-VAT rate eReporting Transaction for France"
    _order = "fr_ereporting_transaction_id, vat_rate desc"

    fr_ereporting_transaction_id = fields.Many2one(
        "fr.ereporting.transaction",
        ondelete="cascade",
        required=True,
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related="fr_ereporting_transaction_id.fr_ereporting_id.company_id", store=True
    )
    date = fields.Date(related="fr_ereporting_transaction_id.date")
    category = fields.Selection(related="fr_ereporting_transaction_id.category")
    vat_exigibility = fields.Selection(
        related="fr_ereporting_transaction_id.vat_exigibility"
    )
    vat_rate = fields.Float(string="VAT Rate", digits=(3, 2), readonly=True)
    base_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    vat_amount = fields.Monetary(
        string="VAT Amount", currency_field="company_currency_id", readonly=True
    )
    company_currency_id = fields.Many2one(
        related="fr_ereporting_transaction_id.fr_ereporting_id.company_id.currency_id",
        string="Company Currency",
    )
    currency_id = fields.Many2one(
        related="fr_ereporting_transaction_id.currency_id",
        string="Transaction Currency",
    )
    note = fields.Html(readonly=True)


class FrEreportingPayment(models.Model):
    _name = "fr.ereporting.payment"
    _description = "Payment for eReporting for France"
    _order = "fr_ereporting_id, date desc"

    fr_ereporting_id = fields.Many2one(
        "fr.ereporting", ondelete="cascade", index=True, required=True, readonly=True
    )
    company_id = fields.Many2one(related="fr_ereporting_id.company_id", store=True)
    date = fields.Date(required=True, readonly=True, string="Payment Date")
    move_id = fields.Many2one("account.move", string="Invoice", readonly=True)
    move_invoice_date = fields.Date(
        related="move_id.invoice_date", string="Invoice Date"
    )
    move_commercial_partner_id = fields.Many2one(
        related="move_id.commercial_partner_id", store=True, string="Customer"
    )
    # Field below is just for user info:
    # the field used in XML is the one on fr.ereporting.payment.rate
    amount = fields.Monetary(currency_field="company_currency_id", readonly=True)
    company_currency_id = fields.Many2one(
        related="fr_ereporting_id.company_id.currency_id", string="Company Currency"
    )
    rate_ids = fields.One2many(
        "fr.ereporting.payment.rate",
        "fr_ereporting_payment_id",
        readonly=True,
        string="Amounts by VAT Rate",
    )
    rate_label = fields.Char(string="VAT Rates", readonly=True)
    note = fields.Html(readonly=True)


class FrEreportingPaymentRate(models.Model):
    _name = "fr.ereporting.payment.rate"
    _description = "Per-VAT rate Payment for eReporting for France"
    _order = "fr_ereporting_payment_id, vat_rate desc"

    fr_ereporting_payment_id = fields.Many2one(
        "fr.ereporting.payment",
        ondelete="cascade",
        required=True,
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related="fr_ereporting_payment_id.fr_ereporting_id.company_id", store=True
    )
    date = fields.Date(related="fr_ereporting_payment_id.date")
    vat_rate = fields.Float(string="VAT Rate", digits=(3, 2), readonly=True)
    company_currency_id = fields.Many2one(
        related="fr_ereporting_payment_id.fr_ereporting_id.company_id.currency_id",
        string="Company Currency",
    )
    amount = fields.Monetary(
        currency_field="company_currency_id", readonly=True
    )  # rule G6.27 says it must be in EUR
