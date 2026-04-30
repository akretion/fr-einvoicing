# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64

from odoo import api, fields, models, Command
import logging
from pprint import pprint
logger = logging.getLogger(__name__)

try:
    from pyfrctc import send_flow_parsed, get_flow, get_flow_metadata_parsed
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class FrEinvoicingFlow(models.Model):
    _name = "fr.einvoicing.flow"
    _description = "France eInvoicing Flows"
    _order = "id desc"

    # On this object, we decided to use several selection fields
    # that are directly mapped to the fields of the AFNOR flow:
    # the keys of these selection fields are the keys in the AFNOR spec
    # (that's why keys start with an upper letter)
    # I don't usually do that, but I think it's the best option for such
    # a technical object that users won't use much
    # TODO add plateform ?
    identifier = fields.Char(readonly=True)   # flowId
    company_id = fields.Many2one("res.company", ondelete="cascade", required=True)
    direction = fields.Selection([  # flowDirection
        ('In', 'In'),
        ('Out', 'Out'),
        ], required=True, readonly=True)
    type = fields.Selection([  # flowType
        ('CustomerInvoice', "Customer Invoice/Refund"),
        ('SupplierInvoice', "Supplier Invoice/Refund"),
        ('StateInvoice', "Customer Invoice To Chorus ???"),
        ('CustomerInvoiceLC', 'Life Cycle for Customer Invoice/Refund'),
        ('SupplierInvoiceLC', 'Life Cycle for Supplier Invoice/Refund'),
        ('StateCustomerInvoiceLC', 'Life Cycle for Customer Invoice/Refund sent to Chorus Pro'),
        ('StateSupplierInvoiceLC', 'Life Cycle for Supplier Invoice/Refund from Chorus Pro'),
        ('AggregatedCustomerTransactionReport', 'E-reporting Aggregated B2C Sales (flow 10.3)'),
        ('UnitaryCustomerTransactionReport', 'E-reporting Individual B2Bi Sales or B2C Sales (flow 10.1)'),
        ('AggregatedCustomerPaymentReport', 'E-reporting B2C payments (flow 10.4)'),
        ('UnitaryCustomerPaymentReport', 'E-reporting of payments (flow 10.2)'),  # TODO
        ('UnitarySupplierTransactionReport', 'E-reporting of B2Bi Purchases (flow 10.1)'),
        ('MultiFlowReport', 'eReporting with at least 2 flow types'),
        ], readonly=True)
    syntax = fields.Selection([  # flowSyntax
        ('CII', 'Cross Industry Invoice (CII)'),
        ('UBL', 'Universal Business Language (UBL)'),
        ('Factur-X', 'Factur-X'),
        ('CDAR', 'Cross Domain Acknowledgement and Response (CDAR)'),
        ('FRR', 'eReporting'),
        ], readonly=True)
    profile = fields.Selection([  # flowProfile
        ('Basic', 'Basic'),
        ('CIUS', 'CIUS'),
        ('Extended-CTC-FR', 'Extended-CTC-FR'),
        ], readonly=True)
    processing_rule = fields.Selection([
        ('B2B', 'B2B Invoicing'),
        ('B2BInt', 'International B2B e-Reporting'),
        ('B2C', 'B2C e-Reporting'),
        ('B2G', 'B2G e-Invoicing'),
        ('B2GInt', 'International B2G'),  # ??
        ('OutOfScope', 'Out of scope (not regulated flow)'),
        ('B2GOutOfScope', 'B2G Out of scope'),
        ('ArchiveOnly', 'Archive only, no transmission'),
        ('NotApplicable', 'Not Applicable'),
        ], readonly=True)
    submitted_at = fields.Datetime(readonly=True)  # SumittedAt
    updated_at = fields.Datetime(readonly=True, help="Last update of the flow")  # UpdatedAt
    file_bin = fields.Binary(string="File", readonly=True)
    filename = fields.Char(readonly=True)
    state = fields.Selection([
        ('created', 'Created'),  # In + Out
        ('downloaded', 'Downloaded'),  # In
        ('sent', 'Sent'),  # Out
        ('pending', 'Sent, Waiting AP Processing'),  # Out
        ('done', 'Done'),  # In + Out
        ('error', 'Error'),  # In + Out
        ('ap_unknown', 'AP Unknown State'),  # Out
        ], default="created", readonly=True)
    ap_error_details = fields.Text(string="Errors reported by AP", readonly=True)
    move_ids = fields.One2many("account.move", "fr_einvoicing_flow_id", string="Invoices", readonly=True)
    move_list = fields.Char(
        compute="_compute_move_list", string="Invoices for List View", store=True)
    # state côté PA / côté Odoo ?
    # initial M2M
    # O2M

    _sql_constraints = [
        (
            'identifier_company_uniq',
            'unique(company_id, identifier)',
            'This flow identifier already exists in this company.')]

    @api.depends('identifier')
    def _compute_display_name(self):
        for flow in self:
            name = flow.identifier
            if not name:
                name = self.env._('ID %s: to send', flow.id)
            flow.display_name = name

    @api.depends('move_ids')
    def _compute_move_list(self):
        for flow in self:
            move_list = False
            if len(flow.move_ids) == 1:
                move_list = flow.move_ids.display_name
            elif len(flow.move_ids) > 1:
                move_list = self.env._("%d invoices", len(flow.move_ids))
            flow.move_list = move_list

    def send(self):
        """For multiple flows, but all from the same company"""
        # TODO we can't raise an error here in the loop because, if an invoice has been sent,
        # the write should not be rolled-backed
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            if flow.direction != "Out":
                logger.info(f'Skipping flow {flow.display_name} because its direction is {flow.direction}')
                continue
            if flow.identifier:
                logger.info(f"Skipping flow {flow.display_name} because it has already been sent")
                continue
            assert flow.company_id == company

            file_bin = base64.decodebytes(flow.file_bin)
            res = send_flow_parsed(session, file_bin, flow.filename, flow.syntax, flow.processing_rule)
            print('res send_flow_parsed==')
            pprint(res)
            # { 'flowId': 'i_45425',
            #   'flowSyntax': 'Factur-X',
            #    'submittedAt': '2026-04-30T13:10:47.360918Z'}
            flow.sudo().write({
                'identifier': res.get('flowId'),
                'submitted_at': res.get('submitted_at'),
                "updated_at": res.get('submitted_at'),
                'state': 'sent',
            })

    def download(self):
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            if flow.direction != "In":
                logger.info(f'Skipping flow {flow.display_name} because its direction is {flow.direction}')
                continue
            if not flow.identifier:
                logger.info(f'Missing identifier on flow {flow.display_name}: skipping')
                continue
            file_bin = get_flow(session, flow.identifier, doc_type='Original')
            file_b64 = base64.encodebytes(file_bin)
            filename = f"{flow.identifier}.pdf"  # TODO
            flow.sudo().write({
                'file_bin': file_b64,
                'filename': filename,
                'state': 'downloaded',
                })

    def in_process(self):
        for flow in self:
            if flow.direction != "In":
                logger.info(f'Skipping flow {flow.display_name} because its direction is {flow.direction}')
                continue
            if flow.state != 'downloaded':
                logger.info(f"Skipping flow {flow.display_name} because its state is '{flow.state}' and not 'downloaded'")
                continue
            if not flow.file_bin:
                logger.info(f"Skipping flow {flow.display_name} because there is no file attached")
                continue
            flow._in_process_single()

    def _in_process_single(self):
        self.ensure_one()
        assert self.direction == 'In'
        assert self.state == 'downloaded'

    def update_status(self):
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            assert flow.company_id == company
            if not flow.identifier:
                logger.info(f"Skipping flow {flow.display_name} because its identifier is missing")
                continue
            res = get_flow_metadata_parsed(session, flow.identifier)
            # print("update_status res=")
            # pprint(res)
            vals = {}
            for key in ('state', 'ap_error_details', 'updated_at'):
                if res.get(key):
                    vals[key] = res[key]
            if vals:
                flow.sudo().write(vals)
                # Add res['acknowledgement']['details']
#            {'acknowledgement': {'status': 'Ok'},
# 'flowDirection': 'Out',
# 'flowId': 'i_45455',
# 'flowSyntax': 'Factur-X',
# 'flowType': 'CustomerInvoice',
# 'processingRule': 'B2B',
# 'processingRuleSource': 'Computed',
# 'submittedAt': '2026-04-30T13:37:56.572719Z',
# 'updatedAt': '2026-04-30T13:37:57.100431Z'}

    def unlink(self):
        for flow in self:
            if flow.identifier:
                raise UserError(
                    self.env._("Cannot delete flow %s because it has already been sent.", flow.display_name))
        return super().unlink()

    def show_invoices_button(self):
        self.ensure_one()
        action = {}
        if self.move_ids and len(self.move_ids) == 1:
            move = self.move_ids
            if move.is_purchase_document():
                xmlid = "account.action_move_in_invoice_type"
            else:
                xmlid = "account.action_move_out_invoice_type"
            action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
            action.update({
                'views': False,
                'view_id': False,
                'res_id': move.id,
                'view_mode': 'form',
                })
        else:
            raise UserError(self.env._("Flow %s is not linked to an invoice.", self.display_name))
        return action
