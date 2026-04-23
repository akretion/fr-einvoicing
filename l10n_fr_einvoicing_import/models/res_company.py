# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
import datetime
import pytz
from pprint import pprint
import base64
import sys

import logging
logger = logging.getLogger(__name__)

try:
    from pyfrctc import search_flows, get_flow
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)

# Backport of datetime.fromisoformat() for python < 3.11
if sys.version_info < (3, 11):
    from backports.datetime_fromisoformat import MonkeyPatch

    MonkeyPatch.patch_fromisoformat()


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_einvoicing_last_invoice_import_datetime = fields.Datetime(string="Last Vendor Bill Import from Accredited Platform")

    def fr_einvoicing_run_import(self):
        self.ensure_one()
        already_imported_invoices = self.env['account.move'].search_read([
            ('company_id', '=', self.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('fr_einvoicing_flow_id', '!=', False),
            ], ['fr_einvoicing_flow_id'])
        already_imported_flows = [x['fr_einvoicing_flow_id'] for x in already_imported_invoices]

        session = self._fr_ctc_get_session()
        last_dt = self.fr_einvoicing_last_invoice_import_datetime
        now_dt = fields.Datetime.now()
        if not last_dt:
            last_dt = now_dt - datetime.timedelta(days=30)  # TODO temp

        # rewind 1h, just in case
        last_dt -= datetime.timedelta(hours=1)
        last_dt_aware = pytz.utc.localize(last_dt)
        last_iso = last_dt_aware.isoformat(timespec="milliseconds")
        if last_iso.endswith("+00:00"):
            last_iso = f"{last_iso[:-6]}Z"

        res_search = search_flows(session, last_iso, 'In', ['SupplierInvoice'])
        pprint(res_search)
        to_import_flows = set()
        for flow_entry in res_search.get('results', []):
            flow_id = flow_entry.get('flowId')
            if flow_id and flow_id not in already_imported_flows and flow_entry['flowType'] == 'SupplierInvoice':
                to_import_flows.add(flow_id)
        inv_imp_obj = self.env['account.invoice.import']
        invoice_ids = []
        for to_import_flow in to_import_flows:
            file_bin = get_flow(session, to_import_flow, doc_type='Original')
            invoice_file_b64 = base64.b64encode(file_bin)
            invoice_id = inv_imp_obj.create_invoice_webservice(invoice_file_b64, f"{to_import_flow}.pdf", self.id, to_import_flow)
            if invoice_id:
                invoice = self.env['account.move'].browse(invoice_id)
                invoice.write({'fr_einvoicing_flow_id': to_import_flow})
                invoice_ids.append(invoice_id)
        self.sudo().write({'fr_einvoicing_last_invoice_import_datetime': now_dt})
        return invoice_ids
