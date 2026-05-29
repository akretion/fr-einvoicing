# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
from markupsafe import Markup
from odoo.tools.misc import format_date
from datetime import timedelta

import logging
logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    fr_directory_company_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type", string="Company Directory Entity Type")
    fr_directory_partner_invoice_entity_type = fields.Selection(
        related="partner_invoice_id.commercial_partner_id.fr_directory_entity_type", string="Invoicing Partner Directory Entity Type")
    fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_fr_directory_line_id", store=True, precompute=True, readonly=False, tracking=True,
        string="Directory Line", ondelete="restrict",
        domain="[('partner_id', '=', commercial_partner_invoice_id), ('state', '=', 'active')]")

    @api.depends('partner_invoice_id', 'company_id')
    def _compute_fr_directory_line_id(self):
        for sale in self:
            fr_directory_line_id = False
            ipartner = sale.partner_invoice_id
            if sale.company_id._fr_ctc_is_vat_registered() and ipartner.commercial_partner_id.fr_directory_entity_type in ('private', 'public'):
                if ipartner.default_fr_directory_line_id:
                    fr_directory_line_id = ipartner.default_fr_directory_line_id.id
                elif ipartner.commercial_partner_id.default_fr_directory_line_id:
                    fr_directory_line_id = ipartner.commercial_partner_id.default_fr_directory_line_id.id
                if not fr_directory_line_id:
                    dir_lines = self.env['fr.directory.line'].search([('partner_id', '=', sale.commercial_partner_id.id), ('state', '=', 'active')])
                    if len(dir_lines) == 1:
                        fr_directory_line_id = dir_lines.id
            sale.fr_directory_line_id = fr_directory_line_id

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.fr_directory_line_id:
            vals['fr_directory_line_id'] = self.fr_directory_line_id.id
        return vals

    def _get_invoice_grouping_keys(self):
        group_keys = super()._get_invoice_grouping_keys()
        group_keys.append('fr_directory_line_id')
        return group_keys

    def _confirmation_error_message(self):
        self.ensure_one()
        err_msg = super()._confirmation_error_message()
        if self.company_id._fr_ctc_is_vat_registered(raise_if_misconfigured=True):
            err_msg = self._fr_ctc_confirmation_error_message()
        return err_msg

    def _fr_ctc_confirmation_error_message(self):
        self.ensure_one()
        # If we don't open a new cursor, we can end up in the following situation:
        # the user has a specific error message, but, if he goes to check the info
        # on the partner form view, he will get different information because
        # the error has been rollbacked by the directory sync
        cinvpartner = self.partner_invoice_id.commercial_partner_id
        company = self.company_id
        dir_sync_done = False  # just to avoid double message in chatter
        if (not cinvpartner.fr_directory_entity_type or cinvpartner.fr_directory_entity_type == 'private_inactive') and cinvpartner.is_company and cinvpartner.is_france_country and cinvpartner._get_siren():
            try:
                cinvpartner._fr_directory_sync_logs(company, self.name)
                self._compute_fr_directory_line_id()
                self.message_post(body=Markup(self.env._("Successful directory sync of the french entity <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> that didn't have any directory status. New directory status: <strong>%(new_entity_type)s</strong>.", partner_id=cinvpartner.id, partner_name=cinvpartner.display_name, new_entity_type=dict(cinvpartner._fields['fr_directory_entity_type']._description_selection(self.env)).get(cinvpartner.fr_directory_entity_type))))
                dir_sync_done = True
            except Exception as err:
                logger.warning('Failed to update partner (triggered from SO %s): %s', self.name, err)
                self.message_post(body=Markup(self.env._("Directory sync of the french entity <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> that didn't have any directory status <strong>failed</strong>.<br/>Error: %(err)s.", partner_id=cinvpartner.id, partner_name=cinvpartner.display_name, err=str(err))))
        if cinvpartner.fr_directory_entity_type in ('public', 'private'):
            if company.fr_ctc_directory_sync_on_sale_order_confirm in ('blocking', 'not_blocking') and not dir_sync_done:
                days = company.fr_ctc_directory_sync_on_sale_order_confirm_days
                trigger_date = fields.Date.context_today(self) - timedelta(days)
                if cinvpartner.fr_directory_last_sync_date > trigger_date:
                    self.message_post(body=Markup(self.env._("No query to the directory because the last directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> was on %(last_sync_date)s, which is less than %(days)s days ago.", partner_id=cinvpartner.id, partner_name=cinvpartner.display_name, last_sync_date=format_date(self.env, cinvpartner.fr_directory_last_sync_date), days=days)))
                else:
                    try:
                        cinvpartner._fr_directory_sync_logs(company, self.name)
                        self.message_post(body=Markup(self.env._("Successful directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> upon confirmation.", partner_id=cinvpartner.id, partner_name=cinvpartner.display_name)))
                    except Exception as err:
                        if company.fr_ctc_directory_sync_on_sale_order_confirm == "blocking":
                            return self.env._("Failed to query the directory for partner '%(partner)s'. Error: %(err)s", partner=cinvpartner.display_name, err=err)
                        else:
                            logger.warning("Failed to update the directory for partner %s ID %s. Error: %s", cinvpartner.display_name, cinvpartner.id, err)
                            self.message_post(body=Markup(self.env._("Directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> <strong>failed</strong>.<br/>Error: %(err)s.", partner_id=cinvpartner.id, partner_name=cinvpartner.display_name, err=str(err))))
            if cinvpartner.fr_directory_closed:
                return self.env._("Invoicing partner '%s' is marked as closed in the directory.", cinvpartner.display_name)
            if not self.fr_directory_line_id:
                return self.env._("No directory line selected on '%s'.", self.display_name)
            if self.fr_directory_line_id.state != 'active':
                return self.env._("On '%(order)s', the selected directory line '%(dir_line)s' is not active.", dir_line=self.fr_directory_line_id.display_name, order=self.display_name)
            if self.fr_directory_line_id.commitment_required and not self.client_order_ref:
                return self.env._("On '%(order)s', the selected directory line '%(dir_line)s' requires a commitment reference but the 'Customer Reference' is not set.", order=self.display_name, dir_line=self.fr_directory_line_id.display_name)
        return None
