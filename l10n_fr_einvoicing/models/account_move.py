# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
from pprint import pprint

import logging
logger = logging.getLogger(__name__)

try:
    from pyfrctc import send_flow
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
    fr_einvoicing_flow_id = fields.Char(readonly=True, string="Flow ID", copy=False)  # Temporary field. Will be replaced by a M2O to a flow object I think
    fr_einvoicing_sent_datetime = fields.Datetime(readonly=True, string="Sent on", copy=False)

    # TODO add unicity of fr_einvoicing_flow_id ?

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

    def _fr_ctc_send_invoice(self):
        self.ensure_one()
        assert self.fr_directory_company_entity_type == 'private'
        assert self.fr_directory_partner_entity_type in ('private', 'public')
        assert self.state == 'posted'
        session = self.company_id._fr_ctc_get_session()
        filename = f"{self.name}.pdf"
        file_bin, filetype = self.env["ir.actions.report"]._render(
            "account.report_invoice_with_payments", [self.id]
            )
        assert filetype == "pdf", "wrong filetype"
        logger.info('Start to send invoice %s ID %d to PA', self.display_name, self.id)
        res = send_flow(session, file_bin, filename, 'Factur-X', 'B2B')
        # print('send_invoice_result========================')
        # pprint(res)
        # {'flowId': 'i_40810',
        #  'flowSyntax': 'Factur-X',
        #  'submittedAt': '2026-04-21T21:22:11.794582Z'}
        flow_id = res.get('flowId')
        self.write({
            'fr_einvoicing_sent_datetime': fields.Datetime.now(),
            'fr_einvoicing_flow_id': flow_id,
            })
