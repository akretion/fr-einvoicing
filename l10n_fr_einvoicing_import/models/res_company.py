# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
import datetime
import pytz
from pprint import pprint

import logging
logger = logging.getLogger(__name__)

try:
    from pyfrctc import search_flows_parsed
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_einvoicing_last_invoice_import_datetime = fields.Datetime(string="Last Vendor Bill Import from Accredited Platform")

    def fr_einvoicing_run_import(self):
        self.ensure_one()
        flow_obj = self.env['fr.einvoicing.flow']
        already_imported_invoices = flow_obj.search_read([
            ('company_id', '=', self.id),
            ('identifier', '!=', False),
            ], ['identifier'])  # TODO limits
        already_imported_flows = [x['identifier'] for x in already_imported_invoices]

        session = self._fr_ctc_get_session()
        last_dt = self.fr_einvoicing_last_invoice_import_datetime
        now_dt = fields.Datetime.now()
        if not last_dt:
            last_dt = now_dt - datetime.timedelta(days=30)  # TODO temp

        # rewind 1h, just in case
        # TODO move to pyfrctc
        last_dt -= datetime.timedelta(hours=1)
        last_dt_aware = pytz.utc.localize(last_dt)
        last_iso = last_dt_aware.isoformat(timespec="milliseconds")
        if last_iso.endswith("+00:00"):
            last_iso = f"{last_iso[:-6]}Z"

        res_search = search_flows_parsed(session, last_iso, 'In', ['SupplierInvoice'])
        pprint(res_search)
        to_create_flows = []
        for flow_entry in res_search:
            pprint(flow_entry)
            flow_id = flow_entry.get('flowId')
            if not flow_id:
                continue
            if flow_entry.get('direction'):
                if flow_entry['direction'] != 'In':
                    logger.error(f"Flow {flow_entry} has direction '{flow_entry['direction']}': it should be 'In'")
                    continue
            if flow_entry.get('type'):
                if flow_entry['type'] != 'SupplierInvoice':
                    logger.error(f"Flow {flow_entry} has type '{flow_entry['type']}': it should be 'SupplierInvoice'")
                    continue
            if flow_id in already_imported_flows:
                logger.info(f'Flow {flow_id} skipped because it has already been imported')
                continue
            flow_vals = {
                'direction': 'In',
                'identifier': flow_entry.get('flowId'),
                'syntax': flow_entry.get('flowSyntax'),
                'type': flow_entry.get('flowType'),
                'processing_rule': flow_entry.get('processingRule'),
                'updated_at': flow_entry.get('updated_at'),
                'submitted_at': flow_entry.get('submitted_at'),  # I don't know what it means on In
                'ap_error_details': flow_entry.get('ap_error_details'),
                "company_id": self.id,
                }
            to_create_flows.append(flow_vals)
        flows = flow_obj.sudo().create(to_create_flows)
        return flows
