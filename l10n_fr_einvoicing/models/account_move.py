# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
import base64
from pprint import pprint

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
    fr_einvoicing_flow_id = fields.Many2one("fr.einvoicing.flow", readonly=True, string="Flow", copy=False)
    fr_einvoicing_flow_state = fields.Selection(related='fr_einvoicing_flow_id.state', store=True, string="Flow State")
    fr_einvoicing_flow_submitted_at = fields.Datetime(related="fr_einvoicing_flow_id.submitted_at", store=True, string="Flow Sent on")

    @api.depends('company_id', 'partner_id')
    def _compute_fr_directory_line_id(self):
        for move in self:
            fr_directory_line_id = False
            cpartner = move.commercial_partner_id
            if move.is_sale_document() and move.company_id._fr_ctc_is_vat_registered() and cpartner.fr_directory_entity_type in ('private', 'public'):
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
        return super()._post(soft=soft)

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
            "direction": "Out",
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
