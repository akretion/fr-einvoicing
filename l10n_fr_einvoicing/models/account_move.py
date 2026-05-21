# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
import base64
from markupsafe import Markup
from datetime import timedelta

import logging
logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    fr_directory_company_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type", string="Company Directory Entity Type")
    fr_directory_partner_entity_type = fields.Selection(
        related="commercial_partner_id.fr_directory_entity_type", string="Customer Directory Entity Type")
    fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_fr_directory_line_id", store=True, precompute=True, readonly=False, tracking=True,
        ondelete="restrict",
        string="Directory Line",
        domain="[('partner_id', '=', commercial_partner_id), ('state', '=', 'active')]")
    fr_einvoicing_flow_id = fields.Many2one("fr.einvoicing.flow", readonly=True, string="Flow", copy=False, check_company=True)
    fr_einvoicing_flow_state = fields.Selection(related='fr_einvoicing_flow_id.state', store=True, string="Flow State")
    fr_einvoicing_flow_submitted_at = fields.Datetime(related="fr_einvoicing_flow_id.submitted_at", store=True, string="Flow Sent on")
    fr_einvoicing_event_ids = fields.One2many('fr.einvoicing.event', 'move_id', readonly=True, string="Events")
    fr_einvoicing_last_event_id = fields.Many2one("fr.einvoicing.event", compute='_compute_last_event', store=True, check_company=True, string="Last Event")
    fr_einvoicing_last_event_decoration = fields.Char(related="fr_einvoicing_last_event_id.status_decoration", store=True)

    # TODO unicity constraint : unicity of flow

    @api.depends('fr_einvoicing_event_ids')
    def _compute_last_event(self):
        for move in self:
            last_event_id = move.fr_einvoicing_event_ids and move.fr_einvoicing_event_ids[0].id or False
            move.fr_einvoicing_last_event_id = last_event_id

    @api.depends('company_id', 'partner_id')
    def _compute_fr_directory_line_id(self):
        for move in self:
            fr_directory_line_id = False
            cpartner = move.commercial_partner_id
#            if move.is_sale_document() and move.company_id._fr_ctc_is_vat_registered() and cpartner.fr_directory_entity_type in ('private', 'public'):
            # TODO temp hack to auto-select dir line on purchase. Just for demo 7/05
            if move.company_id._fr_ctc_is_vat_registered() and cpartner.fr_directory_entity_type in ('private', 'public'):
                if move.partner_id.default_fr_directory_line_id:
                    fr_directory_line_id = move.partner_id.default_fr_directory_line_id.id
                elif cpartner.default_fr_directory_line_id:
                    fr_directory_line_id = cpartner.default_fr_directory_line_id.id
                if not fr_directory_line_id:
                    dir_lines = self.env['fr.directory.line'].search([('partner_id', '=', cpartner.id), ('state', '=', 'active')])
                    if len(dir_lines) == 1:
                        fr_directory_line_id = dir_lines.id
            move.fr_directory_line_id = fr_directory_line_id

    # TODO update dir line
    def _post(self, soft=True):
        for move in self:
            cpartner = move.commercial_partner_id
            if move.is_sale_document() and move.company_id._fr_ctc_is_vat_registered(raise_if_misconfigured=True) and cpartner.fr_directory_entity_type in ('public', 'private'):
                if cpartner.fr_directory_closed:
                    raise UserError(self.env._("Partner '%s' is marked as closed in the directory.", cpartner.display_name))
                if not move.fr_directory_line_id:
                    raise UserError(self.env._("No directory line selected on invoice '%s'.", move.display_name))
                if move.fr_directory_line_id.state != 'active':
                    raise UserError(self.env._("On '%(invoice)s', the selected directory line '%(dir_line)s' is not active.", dir_line=move.fr_directory_line_id.display_name, invoice=move.display_name))
                if move.fr_directory_line_id.commitment_required and not move.ref:
                    raise UserError(self.env._("On '%(invoice)s', the selected directory line '%(dir_line)s' requires a commitment reference but the 'Customer Reference' is not set.", dir_line=move.fr_directory_line_id.display_name, invoice=move.display_name))
            if move.is_purchase_document() and move.fr_einvoicing_flow_id and move.company_id.fr_ctc_event_auto_send_approved and not move.fr_einvoicing_event_ids.filtered(lambda ev: ev.status == 'approved'):
                move._fr_ctc_create_simple_event('approved')
        return super()._post(soft=soft)

    def button_cancel(self):
        if len(self) == 1 and self.fr_einvoicing_flow_id and not self.env.context.get('by_pass_refusal_event_wizard') and not self.fr_einvoicing_event_ids.filtered(lambda x: x.status == "refused"):
            action = self.env["ir.actions.actions"]._for_xml_id("l10n_fr_einvoicing.fr_einvoicing_event_manual_action")
            action['context'] = {'default_status': 'refused', 'default_status_readonly': True}
            return action
        return super().button_cancel()

    def _check_draftable(self):
        for move in self:
            if move.fr_einvoicing_flow_id and not self.env.context.get("sudo_draftable_fr_einvoicing_flow"):
                raise UserError(self.env._("You cannot reset to draft '%s' because it is linked to an eInvoicing flow.", move.display_name))
        return super()._check_draftable()

    def _fr_ctc_send_invoice_prepare_flow(self):
        self.ensure_one()
        filename = f"{self.name}.pdf"
        file_bin, filetype = self.env["ir.actions.report"]._render(
            "account.report_invoice_with_payments", [self.id]
            )
        assert filetype == "pdf", "wrong filetype"
        print('type(file_bin', type(file_bin))
        file_bin_b64 = base64.b64encode(file_bin)
        vals = {
            "syntax": "Factur-X",
            "filename": filename,
            "processing_rule": "B2B",
            "type": "CustomerInvoice",
            # "profile": ,
            "direction": "out",
            "file_bin": file_bin_b64,
            "company_id": self.company_id.id,
            }
        return vals

    def _fr_ctc_send_invoice(self, send_now=False):
        self.ensure_one()
        assert self.fr_directory_company_entity_type == 'private'
        assert self.fr_directory_partner_entity_type in ('private', 'public')
        assert self.state == 'posted'
        flow_vals = self._fr_ctc_send_invoice_prepare_flow()
        flow = self.env['fr.einvoicing.flow'].sudo().create(flow_vals)
        if send_now:
            flow.send()
        logger.info('Flow ID %s created to send invoice %s ID %d', flow.id, self.display_name, self.id)
        self.write({
            'fr_einvoicing_flow_id': flow.id,
            'is_move_sent': True,
            })

    def _fr_ctc_prepare_simple_event(self, status):
        self.ensure_one()
        vals = {
            'move_id': self.id,
            'company_id': self.company_id.id,
            'status': status,
            'direction': 'out',
            }
        return vals

    def _fr_ctc_create_simple_event(self, status, post_message=True):
        self.ensure_one()
        event_vals = self._fr_ctc_prepare_simple_event(status)
        event = self.env['fr.einvoicing.event'].sudo().create(event_vals)
        if post_message:
            self.message_post(body=Markup(self.env._("Event <a href=# data-oe-model=fr.einvoicing.event data-oe-id=%(event_id)s>%(event)s</a> created automatically by Odoo.", event=event.display_name, event_id=event.id)))
        return event

    def _fr_ctc_activity_warning_event_users(self, event):
        """Get users that will get a mail.activity when an event is received
        on an invoice. This method also fixes the conditions for the activity to be sent"""
        self.ensure_one()
        users = False
        if self.is_sale_document() and event.status_decoration in ('danger', 'warning'):
            company = self.company_id
            users = company.fr_ctc_activity_warning_event_user_ids
            if company.fr_ctc_activity_warning_event_invoice_creator:
                users |= self.create_uid
            if company.fr_ctc_activity_warning_event_salesman and self.user_id:
                users |= self.user_id
        return users

    def _fr_ctc_prepare_activity_warning_event(self, event):
        today = fields.Date.context_today(self)
        # Field user_id is added later in the code, to avoid calling this method too many times
        mail_activity_vals = {
            'res_id': self.id,
            'res_model_id': self.env.ref('account.model_account_move').id,
            'activity_type_id': self.env.ref('l10n_fr_einvoicing.warning_invoice_event_mail_activity_type').id,
            'summary': self.env._("Event %(event)s received on %(invoice)s", event=event.display_name, invoice=self.with_context(input_full_display_name=True).display_name),
            'note': event.infos,
            'automated': True,
            }
        return mail_activity_vals
