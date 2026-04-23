# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError


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
        cinvpartner = self.partner_invoice_id.commercial_partner_id
        if self.company_id._fr_ctc_is_vat_registered(raise_if_misconfigured=True) and cinvpartner.fr_directory_entity_type in ('public', 'private'):
            session = self.company_id._fr_ctc_get_session()
            cinvpartner._fr_directory_update_if_old(session)
            if cinvpartner.fr_directory_closed:
                return self.env._("Invoicing partner '%s' is marked as closed in the directory.", cinvpartner.display_name)
            if not self.fr_directory_line_id:
                return self.env._("No directory line selected on '%s'.", self.display_name)
            if self.fr_directory_line_id.state != 'active':
                return self.env._("On '%(order)s', the selected directory line '%(dir_line)s' is not active.", dir_line=self.fr_directory_line_id.display_name, order=self.display_name)
            if self.fr_directory_line_id.commitment_required and not self.client_order_ref:
                return self.env._("On '%(order)s', the selected directory line '%(dir_line)s' requires a commitment reference but the 'Customer Reference' is not set.", order=self.display_name, dir_line=self.fr_directory_line_id.display_name)
        return err_msg
