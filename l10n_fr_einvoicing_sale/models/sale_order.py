# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools.misc import format_date

logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    fr_directory_company_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type",
        string="Company Directory Entity Type",
    )
    fr_directory_partner_invoice_entity_type = fields.Selection(
        related="partner_invoice_id.commercial_partner_id.fr_directory_entity_type",
        string="Invoicing Partner Directory Entity Type",
    )
    # sale_commercial_partner dropped commercial_partner_invoice_id in 19.0, but
    # the directory line domain still needs the invoicing partner's entity.
    fr_directory_partner_invoice_id = fields.Many2one(
        related="partner_invoice_id.commercial_partner_id",
        string="Invoicing Partner Entity",
    )
    fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_fr_directory_line_id",
        store=True,
        precompute=True,
        readonly=False,
        tracking=True,
        string="Directory Line",
        ondelete="restrict",
        domain="[('partner_id', '=', fr_directory_partner_invoice_id), "
        "('state', '=', 'active')]",
    )

    @api.depends("partner_invoice_id", "company_id")
    def _compute_fr_directory_line_id(self):
        for sale in self:
            fr_directory_line_id = False
            ipartner = sale.partner_invoice_id
            if (
                sale.company_id._fr_ctc_is_vat_registered()
                and ipartner.commercial_partner_id.fr_directory_entity_type
                in ("private", "public")
            ):
                if ipartner.default_fr_directory_line_id:
                    fr_directory_line_id = ipartner.default_fr_directory_line_id.id
                elif ipartner.commercial_partner_id.default_fr_directory_line_id:
                    fr_directory_line_id = (
                        ipartner.commercial_partner_id.default_fr_directory_line_id.id
                    )
                if not fr_directory_line_id:
                    dir_lines = self.env["fr.directory.line"].search(
                        [
                            ("partner_id", "=", sale.commercial_partner_id.id),
                            ("state", "=", "active"),
                        ]
                    )
                    if len(dir_lines) == 1:
                        fr_directory_line_id = dir_lines.id
            sale.fr_directory_line_id = fr_directory_line_id

    @api.model
    def _fr_directory_sync_action_server(self):
        """Used by ir.actions.server called by RedirectWarning()"""
        action = {}
        if self.env.context.get("fr_directory_sync_order_id"):
            order = self.browse(self.env.context["fr_directory_sync_order_id"])
            cinvpartner = order.partner_invoice_id.commercial_partner_id
            try:
                cinvpartner._fr_directory_sync_logs(
                    order.company_id, f"Redirect Warning {self.name}"
                )
                order.message_post(
                    body=Markup(
                        self.env._(
                            "Directory sync of <a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a>.",
                            partner_id=cinvpartner.id,
                            partner_name=cinvpartner.display_name,
                        )
                    )
                )
            except Exception as err:
                logger.warning(
                    "Failed to sync directory for partner %s. Error: %s",
                    cinvpartner.display_name,
                    err,
                )
                order.message_post(
                    body=Markup(
                        self.env._(
                            "Failed to sync directory for partner "
                            "<a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a>."
                            "<br/>Error: %(err)s",
                            partner_id=cinvpartner.id,
                            partner_name=cinvpartner.display_name,
                            err=str(err),
                        )
                    )
                )
            action = self.env["ir.actions.actions"]._for_xml_id("sale.action_orders")
            action.update(
                {
                    "views": False,
                    "view_id": False,
                    "res_id": order.id,
                    "view_mode": "form,list",
                    "domain": False,
                }
            )
        else:
            logger.error("Missing key fr_directory_sync_order_id in context")
        return action

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.fr_directory_line_id:
            vals["fr_directory_line_id"] = self.fr_directory_line_id.id
        return vals

    def _get_invoice_grouping_keys(self):
        group_keys = super()._get_invoice_grouping_keys()
        group_keys.append("fr_directory_line_id")
        return group_keys

    def _action_confirm(self):
        for order in self:
            if order.company_id._fr_ctc_is_vat_registered(raise_if_misconfigured=True):
                order._fr_ctc_confirm_checks()
        return super()._action_confirm()

    def _fr_ctc_confirm_checks(self):
        self.ensure_one()
        cinvpartner = self.partner_invoice_id.commercial_partner_id
        company = self.company_id
        dir_sync_done = False  # just to avoid double message in chatter
        if cinvpartner._fr_directory_should_sync_upon_confirmation():
            try:
                cinvpartner._fr_directory_sync_logs(company, self.name)
                self._compute_fr_directory_line_id()
                dir_sync_done = True
                self.message_post(
                    body=Markup(
                        self.env._(
                            "Successful directory sync of the french entity "
                            "<a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                            "that didn't have any directory status. "
                            "New directory status: "
                            "<strong>%(new_entity_type)s</strong>.",
                            partner_id=cinvpartner.id,
                            partner_name=cinvpartner.display_name,
                            new_entity_type=dict(
                                cinvpartner._fields[
                                    "fr_directory_entity_type"
                                ]._description_selection(self.env)
                            ).get(cinvpartner.fr_directory_entity_type),
                        )
                    )
                )
            except Exception as err:
                logger.warning(
                    "Failed to update partner (triggered from SO %s): %s",
                    self.name,
                    err,
                )
                self.message_post(
                    body=Markup(
                        self.env._(
                            "Directory sync of the french entity "
                            "<a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                            "that didn't have any directory status "
                            "<strong>failed</strong>.<br/>Error: %(err)s.",
                            partner_id=cinvpartner.id,
                            partner_name=cinvpartner.display_name,
                            err=str(err),
                        )
                    )
                )
        if cinvpartner.fr_directory_entity_type in ("public", "private"):
            if (
                company.fr_ctc_directory_sync_on_sale_order_confirm
                in ("blocking", "not_blocking")
                and not dir_sync_done
            ):
                days = company.fr_ctc_directory_sync_on_sale_order_confirm_days
                trigger_date = fields.Date.context_today(self) - timedelta(days)
                if cinvpartner.fr_directory_last_sync_date > trigger_date:
                    self.message_post(
                        body=Markup(
                            self.env._(
                                "No query to the directory because the last "
                                "directory sync of "
                                "<a href=# data-oe-model=res.partner "
                                "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                                "was on %(last_sync_date)s, which is less "
                                "than %(days)s days ago.",
                                partner_id=cinvpartner.id,
                                partner_name=cinvpartner.display_name,
                                last_sync_date=format_date(
                                    self.env, cinvpartner.fr_directory_last_sync_date
                                ),
                                days=days,
                            )
                        )
                    )
                else:
                    try:
                        cinvpartner._fr_directory_sync_logs(company, self.name)
                        dir_sync_done = True
                        self.message_post(
                            body=Markup(
                                self.env._(
                                    "Successful directory sync of "
                                    "<a href=# data-oe-model=res.partner "
                                    "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                                    "upon confirmation.",
                                    partner_id=cinvpartner.id,
                                    partner_name=cinvpartner.display_name,
                                )
                            )
                        )
                    except Exception as err:
                        if (
                            company.fr_ctc_directory_sync_on_sale_order_confirm
                            == "blocking"
                        ):
                            return self.env._(
                                "Failed to query the directory for partner "
                                "'%(partner)s'. Error: %(err)s",
                                partner=cinvpartner.display_name,
                                err=err,
                            )
                        else:
                            logger.warning(
                                "Failed to update the directory for partner "
                                "%s ID %s. Error: %s",
                                cinvpartner.display_name,
                                cinvpartner.id,
                                err,
                            )
                            self.message_post(
                                body=Markup(
                                    self.env._(
                                        "Directory sync of "
                                        "<a href=# data-oe-model=res.partner "
                                        "data-oe-id=%(partner_id)s>%(partner_name)s"
                                        "</a> <strong>failed</strong>."
                                        "<br/>Error: %(err)s.",
                                        partner_id=cinvpartner.id,
                                        partner_name=cinvpartner.display_name,
                                        err=str(err),
                                    )
                                )
                            )
            err_msg = cinvpartner._fr_directory_confirm_common_checks()
            if err_msg:
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
            if not self.fr_directory_line_id:
                err_msg = self.env._(
                    "No directory line selected on '%s'.", self.display_name
                )
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
            err_msg = self.fr_directory_line_id._confirm_common_checks(
                self.client_order_ref, self.name
            )
            if err_msg:
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
        return None

    def _fr_ctc_raise_error(self, err_msg, dir_sync_done):
        self.ensure_one()
        if dir_sync_done:
            action = self.env.ref(
                "l10n_fr_einvoicing_sale.fr_directory_sync_sale_order_redirect_warning"
            )
            raise RedirectWarning(
                err_msg,
                action.id,
                self.env._("Sync Invoicing Partner Directory Now"),
                additional_context={"fr_directory_sync_order_id": self.id},
            )
        else:
            raise UserError(err_msg)
