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

try:
    from pyfrctc import get_flow
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)

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
    fr_einvoicing_show_readable_invoice_button = fields.Boolean(compute="_compute_fr_einvoicing_show_readable_invoice_button", store=True, readonly=False)
    fr_einvoicing_required = fields.Boolean(compute="_compute_einvoicing_required", store=True)

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

    @api.depends("fr_directory_company_entity_type", "fr_directory_partner_entity_type", "move_type", "company_id.fr_ctc_disable_private_invoice_sending")
    def _compute_einvoicing_required(self):
        for move in self:
            fr_einvoicing_required = False
            if move.move_type in ('out_invoice', 'out_refund') and move.fr_directory_company_entity_type == 'private' and (move.fr_directory_partner_entity_type == 'public' or (move.fr_directory_partner_entity_type == 'private' and not move.company_id.fr_ctc_disable_private_invoice_sending)):
                fr_einvoicing_required = True
            move.fr_einvoicing_required = fr_einvoicing_required

    # TODO update dir line
    def _post(self, soft=True):
        for move in self:
            company = move.company_id
            if move.is_sale_document() and company._fr_ctc_is_vat_registered(raise_if_misconfigured=True):
                move._fr_ctc_sale_document_post_checks()
            if move.is_purchase_document() and move.fr_einvoicing_flow_id and company.fr_ctc_event_auto_send_approved and not move.fr_einvoicing_event_ids.filtered(lambda ev: ev.status == 'approved'):
                move._fr_ctc_create_simple_event('approved')
        return super()._post(soft=soft)

    def _fr_ctc_sale_document_post_checks(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        cpartner = self.commercial_partner_id
        company = self.company_id
        dir_sync_done = False  # just to avoid double message in chatter
        if (not cpartner.fr_directory_entity_type or cpartner.fr_directory_entity_type == 'private_inactive') and cpartner.is_company and cpartner.is_france_country and cpartner._get_siren():
            try:
                cpartner._fr_directory_sync_logs(company, self.display_name)
                self._compute_fr_directory_line_id()
                self.message_post(body=Markup(self.env._("Successful directory sync of the french entity <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> that didn't have any directory status. New directory status: <strong>%(new_entity_type)s</strong>.", partner_id=cpartner.id, partner_name=cpartner.display_name, new_entity_type=dict(cpartner._fields['fr_directory_entity_type']._description_selection(self.env)).get(cpartner.fr_directory_entity_type))))
                dir_sync_done = True
            except Exception as err:
                logger.warning("Failed to update partner (triggered from customer invoice/refund %s): %s", self.display_name, err)
                self.message_post(body=Markup(self.env._("Directory sync of the french entity <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> that didn't have any directory status <strong>failed</strong>.<br/>Error: %(err)s.", partner_id=cpartner.id, partner_name=cpartner.display_name, err=str(err))))
        if cpartner.fr_directory_entity_type in ('public', 'private'):
            if company.fr_ctc_directory_sync_on_invoice_post in ('blocking', 'not_blocking') and not dir_sync_done:
                if cpartner.fr_directory_last_sync_date >= today:
                    self.message_post(body=Markup(self.env._("No query to the directory because the last directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> was today.", partner_id=cpartner.id, partner_name=cpartner.display_name)))
                else:
                    try:
                        cpartner._fr_directory_sync_logs(company, self.display_name)
                        self.message_post(body=Markup(self.env._("Successful directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> upon confirmation.", partner_id=cpartner.id, partner_name=cpartner.display_name)))
                    except Exception as err:
                        if company.fr_ctc_directory_sync_on_invoice_post == "blocking":
                            raise UserError(self.env._("Failed to query the directory for partner '%(partner)s'. Error: %(err)s", partner=cpartner.display_name, err=err)) from err
                        else:
                            logger.warning("Failed to update the directory for partner %s ID %s. Error: %s", cpartner.display_name, cpartner.id, err)
                            self.message_post(body=Markup(self.env._("Directory sync of <a href=# data-oe-model=res.partner data-oe-id=%(partner_id)s>%(partner_name)s</a> <strong>failed</strong>.<br/>Error: %(err)s.", partner_id=cpartner.id, partner_name=cpartner.display_name, err=str(err))))
            if cpartner.fr_directory_closed:
                raise UserError(self.env._("Partner '%s' is marked as closed in the directory.", cpartner.display_name))
            if not self.fr_directory_line_id:
                raise UserError(self.env._("No directory line selected on invoice '%s'.", self.display_name))
            if self.fr_directory_line_id.state != 'active':
                raise UserError(self.env._("On '%(invoice)s', the selected directory line '%(dir_line)s' is not active.", dir_line=self.fr_directory_line_id.display_name, invoice=self.display_name))
            if self.fr_directory_line_id.commitment_required and not self.ref:
                raise UserError(self.env._("On '%(invoice)s', the selected directory line '%(dir_line)s' requires a commitment reference but the 'Customer Reference' is not set.", dir_line=self.fr_directory_line_id.display_name, invoice=self.display_name))

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

    def _fr_ctc_send_invoice_prepare_flow_facturx(self):
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

    def _fr_ctc_send_invoice_prepare_flow_cii(self):
        self.ensure_one()
        filename = f"{self.name}.xml"
#        file_bin = self.generate_ubl_xml_string()
        file_bin = self.generate_facturx_xml()
        file_bin_b64 = base64.b64encode(file_bin)
        vals = {
#            "syntax": "UBL",
            "syntax": "CII",
            "filename": filename,
            "processing_rule": "B2B",
            "type": "CustomerInvoice",
            # "profile": ,
            "direction": "out",
            "file_bin": file_bin_b64,
            "company_id": self.company_id.id,
            }
        return vals

    def fr_ctc_send_invoice_immediately(self):
        self.ensure_one()
        self._fr_ctc_send_invoice(send_now=True)

    def _fr_ctc_send_invoice(self, send_now=False):
        self.ensure_one()
        assert self.fr_directory_company_entity_type == 'private'
        assert self.fr_directory_partner_entity_type in ('private', 'public')
        assert self.state == 'posted'
        flow_vals = self._fr_ctc_send_invoice_prepare_flow_facturx()
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

    @api.depends('fr_einvoicing_flow_id')
    def _compute_fr_einvoicing_show_readable_invoice_button(self):
        for move in self:
            show = False
            if move.is_purchase_document() and move.fr_einvoicing_flow_id and move.fr_einvoicing_flow_id.syntax != 'Factur-X':
                show = True
            move.fr_einvoicing_show_readable_invoice_button = show

    def fr_ctc_get_readable_invoice_button(self, ):
        self.ensure_one()
        attach_vals = self._fr_ctc_prepare_readable_attachment()
        attach = self.env['ir.attachment'].create(attach_vals)
        self.write({"fr_einvoicing_show_readable_invoice_button": False})
        msg = self.env._("File %s added to the attachments of the vendor bill.", attach.name)
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._("Readable invoice successfully downloaded"),
                'message': msg,
                }}
        return action

    def _fr_ctc_prepare_readable_attachment(self):
        self.ensure_one()
        flow = self.fr_einvoicing_flow_id
        assert flow
        assert flow.direction == "in"
        assert flow.identifier
        assert self.is_purchase_document()
        inv_ref = self.ref or self.name
        filename = f"readable_{inv_ref.replace('/', '_')}.pdf"
        company = self.company_id
        try:
            session = company._fr_ctc_get_session()
            readable_file_bin = get_flow(session, flow.identifier, doc_type='ReadableView')
        except Exception as err:
            raise UserError(self.env._("Failed to get the readable version of vendor bill/refund %(invoice)s. Error: %(err)s", invoice=self.display_name, err=err)) from err
        vals = {
            'res_model': self._name,
            'res_id': self.id,
            'name': filename,
            'raw': readable_file_bin,
            }
        return vals

    def _fr_einvoicing_send_invoices_cron(self):
        """
        Cron to send invoices to the accredited platform.

        First step creation of new flow for invoices with einvoicing required.
        Second step send the pending flows.
        """
        for company in self.env["res.company"].search([]):
            logger.info(
                "Starting fr_einvoicing cron for company: %s", company.name
            )
            try:
                moves = self.search(
                    [
                        ("company_id", "=", company.id),
                        ("fr_einvoicing_required", "=", True),
                        ("fr_einvoicing_flow_id", "=", False),
                    ]
                )
                for move in moves:
                    move._fr_ctc_send_invoice(send_now=False)
            except Exception as e:
                logger.error(
                    "Error during einvoicing out flow creation for company %s: %s",
                    company.name,
                    str(e),
                )
            try:
                flows = (
                    self.env["fr.einvoicing.flow"]
                    .sudo()
                    .search(
                        [
                            ("company_id", "=", company.id),
                            ("state", "=", "created"),
                            ("direction", "=", "out"),
                        ]
                    )
                )
                flows.send()
            except Exception as e:
                logger.error(
                    "Error during einvoicing out flow sending for company %s: %s",
                    company.name,
                    str(e),
                )
