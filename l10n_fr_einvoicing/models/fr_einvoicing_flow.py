# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import logging

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

try:
    from pyfrctc import get_flow, get_flow_metadata_parsed, parse_cdar, send_flow_parsed
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
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
    identifier = fields.Char(readonly=True)  # flowId
    company_id = fields.Many2one("res.company", ondelete="cascade", required=True)
    direction = fields.Selection(
        [  # flowDirection
            ("in", "In"),
            ("out", "Out"),
        ],
        required=True,
        readonly=True,
    )
    type = fields.Selection(
        [  # flowType
            ("CustomerInvoice", "Customer Invoice/Refund"),
            ("SupplierInvoice", "Supplier Invoice/Refund"),
            ("StateInvoice", "Customer Invoice To Chorus ???"),
            ("CustomerInvoiceLC", "Life Cycle for Customer Invoice/Refund"),
            ("SupplierInvoiceLC", "Life Cycle for Supplier Invoice/Refund"),
            (
                "StateCustomerInvoiceLC",
                "Life Cycle for Customer Invoice/Refund sent to Chorus Pro",
            ),
            (
                "StateSupplierInvoiceLC",
                "Life Cycle for Supplier Invoice/Refund from Chorus Pro",
            ),
            (
                "AggregatedCustomerTransactionReport",
                "E-reporting Aggregated B2C Sales (flow 10.3)",
            ),
            (
                "UnitaryCustomerTransactionReport",
                "E-reporting Individual B2Bi Sales or B2C Sales (flow 10.1)",
            ),
            ("AggregatedCustomerPaymentReport", "E-reporting B2C payments (flow 10.4)"),
            (
                "UnitaryCustomerPaymentReport",
                "E-reporting of payments (flow 10.2)",
            ),
            (
                "UnitarySupplierTransactionReport",
                "E-reporting of B2Bi Purchases (flow 10.1)",
            ),
            ("MultiFlowReport", "eReporting with at least 2 flow types"),
        ],
        readonly=True,
    )
    syntax = fields.Selection(
        [  # flowSyntax
            ("CII", "Cross Industry Invoice (CII)"),
            ("UBL", "Universal Business Language (UBL)"),
            ("Factur-X", "Factur-X"),
            ("CDAR", "Cross Domain Acknowledgement and Response (CDAR)"),
            ("FRR", "eReporting"),
        ],
        readonly=True,
    )
    profile = fields.Selection(
        [  # flowProfile
            ("Basic", "Basic"),
            ("CIUS", "CIUS"),
            ("Extended-CTC-FR", "Extended-CTC-FR"),
        ],
        readonly=True,
    )
    processing_rule = fields.Selection(
        [
            ("B2B", "B2B Invoicing"),
            ("B2BInt", "International B2B e-Reporting"),
            ("B2C", "B2C e-Reporting"),
            ("B2G", "B2G e-Invoicing"),
            ("B2GInt", "International B2G"),  # ??
            ("OutOfScope", "Out of scope (not regulated flow)"),
            ("B2GOutOfScope", "B2G Out of scope"),
            ("ArchiveOnly", "Archive only, no transmission"),
            ("NotApplicable", "Not Applicable"),
        ],
        readonly=True,
    )
    submitted_at = fields.Datetime(readonly=True)  # SumittedAt
    updated_at = fields.Datetime(
        readonly=True, help="Last update of the flow"
    )  # UpdatedAt
    file_bin = fields.Binary(string="File", readonly=True)
    filename = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("created", "Created"),  # in + out
            ("downloaded", "Downloaded"),  # in
            ("sent", "Sent"),  # out
            ("pending", "Sent, Waiting AP Processing"),  # out
            ("done", "Done"),  # in + out
            ("error", "Error"),  # in + out
            ("ap_unknown", "AP Unknown State"),  # out
        ],
        default="created",
        readonly=True,
        required=True,
    )
    ap_error_details = fields.Text(string="Errors reported by AP", readonly=True)
    odoo_error_details = fields.Text(string="Odoo Errors", readonly=True)
    move_ids = fields.One2many(
        "account.move", "fr_einvoicing_flow_id", string="Invoices", readonly=True
    )
    move_list = fields.Char(
        compute="_compute_move_list", string="Invoices for List View", store=True
    )
    event_ids = fields.One2many(
        "fr.einvoicing.event", "flow_id", readonly=True, string="Events"
    )
    # state côté PA / côté Odoo ?
    # initial M2M
    # O2M

    _sql_constraints = [
        (
            "identifier_company_uniq",
            "unique(company_id, identifier)",
            "This flow identifier already exists in this company.",
        )
    ]

    @api.depends("identifier")
    def _compute_display_name(self):
        state2label = dict(self._fields["state"]._description_selection(self.env))
        for flow in self:
            name = flow.identifier
            if not name:
                name = self.env._("ID %s: to send", flow.id)
            if flow.state:
                name = f"{name} ({state2label.get(flow.state)})"
            flow.display_name = name

    @api.depends("move_ids")
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
        # TODO we can't raise an error here in the loop because,
        # if an invoice has been sent, the write should not be rolled-backed
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            if flow.direction != "out":
                logger.info(
                    f"Skipping flow {flow.display_name} because its direction "
                    f"is {flow.direction}"
                )
                continue
            if flow.identifier:
                logger.info(
                    f"Skipping flow {flow.display_name} because it has "
                    "already been sent"
                )
                continue
            assert flow.company_id == company

            file_bin = base64.decodebytes(flow.file_bin)
            res = send_flow_parsed(
                session, file_bin, flow.filename, flow.syntax, flow.processing_rule
            )
            print("res send_flow_parsed==")
            from pprint import pprint

            pprint(res)
            # { 'flowId': 'i_45425',
            #   'flowSyntax': 'Factur-X',
            #    'submittedAt': '2026-04-30T13:10:47.360918Z'}
            flow.sudo().write(
                {
                    "identifier": res.get("flowId"),
                    "submitted_at": res.get("submitted_at"),
                    "updated_at": res.get("submitted_at"),
                    "state": "sent",
                }
            )
            flow.move_ids.filtered(lambda x: not x.is_move_sent).is_move_sent = True

    def download(self):
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            if flow.direction != "in":
                logger.info(
                    f"Skipping flow {flow.display_name} because its direction "
                    f"is {flow.direction}"
                )
                continue
            if not flow.identifier:
                logger.info(f"Missing identifier on flow {flow.display_name}: skipping")
                continue
            file_bin = get_flow(session, flow.identifier, doc_type="Original")
            file_b64 = base64.encodebytes(file_bin)
            if self.syntax == "Factur-X":
                filename = f"{flow.identifier}.pdf"
            else:
                filename = f"{flow.identifier}.xml"
            flow.sudo().write(
                {
                    "file_bin": file_b64,
                    "filename": filename,
                    "state": "downloaded",
                }
            )

    def in_process(self):
        for flow in self:
            if flow.direction != "in":
                logger.info(
                    f"Skipping flow {flow.display_name} because its direction "
                    f"is {flow.direction}"
                )
                continue
            if flow.state != "downloaded":
                logger.info(
                    f"Skipping flow {flow.display_name} because its state is "
                    f"'{flow.state}' and not 'downloaded'"
                )
                continue
            if not flow.file_bin:
                logger.info(
                    f"Skipping flow {flow.display_name} because there is "
                    "no file attached"
                )
                continue
            flow._in_process_single()

    def _import_supplier_invoice(self):
        """Method inherited in l10n_fr_einvoicing_import
        If you don't want to use the OCA module account_invoice_import, you can develop
        an alternative to l10n_fr_einvoicing_import and inherit this method"""
        self.ensure_one()
        return False

    def _in_process_single(self):
        self.ensure_one()
        assert self.direction == "in"
        assert self.state == "downloaded"
        if self.type == "SupplierInvoice":
            move_id = self._import_supplier_invoice()
            if move_id:
                self.sudo().write({"state": "done"})
                if self.company_id.fr_ctc_event_auto_send_in_hand:
                    move = self.env["account.move"].browse(move_id)
                    move._fr_ctc_create_simple_event("in_hand")
            else:
                flow_vals = {
                    "state": "error",
                }
                self.sudo().write(flow_vals)

        elif self.type in (
            "CustomerInvoiceLC",
            "SupplierInvoiceLC",
            "StateCustomerInvoiceLC",
            "StateSupplierInvoiceLC",
        ):
            # MOVE to a dedicated other method
            # TODO very important point : flow LC can arrive BEFORE invoice !!!
            # here, it will fail because of that !
            xml_bytes = base64.decodebytes(self.file_bin)
            event_dict = parse_cdar(xml_bytes)
            print("event_dict===============", event_dict)
            move = self._match_invoice_from_event(event_dict)
            if move:
                self._create_event(event_dict, move)
                flow_vals = {"state": "done"}
            else:
                if self.type in ("CustomerInvoiceLC", "StateCustomerInvoiceLC"):
                    inv_type_label = "customer invoice/refund"
                elif self.type in ("SupplierInvoiceLC", "StateSupplierInvoiceLC"):
                    inv_type_label = "supplier invoice/refund"
                err_details = (
                    f"No {inv_type_label} found with number "
                    f"{event_dict['invoice_number']}"
                )
                flow_vals = {
                    "state": "error",
                    "odoo_error_details": err_details,
                }

            self.sudo().write(flow_vals)

    def _match_invoice_from_event(self, event_dict):
        self.ensure_one()
        assert self.type in (
            "CustomerInvoiceLC",
            "SupplierInvoiceLC",
            "StateCustomerInvoiceLC",
            "StateSupplierInvoiceLC",
        )
        if self.type in ("CustomerInvoiceLC", "StateCustomerInvoiceLC"):
            domain = [
                ("name", "=", event_dict["invoice_number"]),
                ("company_id", "=", self.company_id.id),
            ]
        elif self.type in ("SupplierInvoiceLC", "StateSupplierInvoiceLC"):
            # TODO add partner, because ref is by partner
            domain = [
                ("ref", "=", event_dict["invoice_number"]),
                ("company_id", "=", self.company_id.id),
            ]
        move = self.env["account.move"].search(domain, limit=1)
        if not move:
            logger.warning("No invoice found with domain %s", domain)
        return move

    def _create_event(self, event_dict, move):
        event_vals = self._prepare_event(event_dict, move)
        event = self.env["fr.einvoicing.event"].sudo().create(event_vals)
        users = move._fr_ctc_activity_warning_event_users(event)
        if users:
            mail_activity_common_vals = move._fr_ctc_prepare_activity_warning_event(
                event
            )
            for user in users:
                mail_activity_vals = dict(mail_activity_common_vals, user_id=user.id)
                activity = self.env["mail.activity"].sudo().create(mail_activity_vals)
                logger.info(
                    "Mail activity ID %d created for user %s",
                    activity.id,
                    user.display_name,
                )
        if event.attachment_ids:
            href_attachs = []
            for event_attach in event.attachment_ids:
                attach = self.env["ir.attachment"].create(
                    {
                        "name": event_attach.name,
                        "raw": event_attach.raw,
                        "res_model": "account.move",
                        "res_id": move.id,
                        "company_id": self.company_id.id,
                    }
                )
                href_attachs.append(
                    f"<a href=# data-oe-model=ir.attachment "
                    f"data-oe-id={attach.id}>{attach.name}</a>"
                )
            move.sudo().message_post(
                body=Markup(
                    self.env._(
                        "%(attach_count)s attachment(s) added by received "
                        "event <a href=# data-oe-model=fr.einvoicing.event "
                        "data-oe-id=%(event_id)s>%(event_dname)s</a>: "
                        "%(attach_list)s",
                        attach_count=len(href_attachs),
                        event_id=event.id,
                        event_dname=event.display_name,
                        attach_list=", ".join(href_attachs),
                    )
                )
            )
        return event

    def _prepare_event(self, event_dict, move):
        event_obj = self.env["fr.einvoicing.event"]
        currency_name2id = {
            x["name"]: x["id"]
            for x in self.env["res.currency"]
            .with_context(active_test=False)
            .search_read([], ["name"])
        }
        event_vals = {
            "move_id": move.id,
            "flow_id": self.id,
            "company_id": self.company_id.id,
            "direction": "in",
            "datetime": event_dict["lc_datetime"],
            "date": event_dict["lc_datetime"].date(),
            "status": event_obj._get_status_key(event_dict["status_code"]),
            "detail_ids": [],
            "payment_ids": [],
            "attachment_ids": [],
            "state": "done",
        }
        for doc_status in event_dict.get("doc_status", []):
            if (
                doc_status.get("reason_code")
                or doc_status.get("comment")
                or doc_status.get("action_code")
            ):
                detail_dict = {
                    "reason": doc_status.get("reason_code"),
                    "comment": doc_status.get("comment"),
                    "action": doc_status.get("action_code"),
                }
                event_vals["detail_ids"].append(Command.create(detail_dict))
            for doc_characteristic in doc_status.get("doc_characteristics", []):
                if (
                    doc_characteristic.get("amount")
                    and doc_characteristic["amount"].get("currency") in currency_name2id
                    and doc_characteristic["amount"].get("float")
                ):
                    pay_dict = {
                        "date": doc_characteristic["date"],
                        "currency_id": currency_name2id[
                            doc_characteristic["amount"]["currency"]
                        ],
                        "amount": doc_characteristic["amount"]["float"],
                    }
                    event_vals["payment_ids"].append(Command.create(pay_dict))
        for attach in event_dict.get("attachments", []):
            event_vals["attachment_ids"].append(
                Command.create({"name": attach["filename"], "raw": attach["bin"]})
            )
        return event_vals

    def update_status(self):
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        for flow in self:
            assert flow.company_id == company
            if not flow.identifier:
                logger.info(
                    f"Skipping flow {flow.display_name} because its identifier "
                    "is missing"
                )
                continue
            res = get_flow_metadata_parsed(session, flow.identifier)
            # print("update_status res=")
            # pprint(res)
            vals = {}
            for key in ("state", "ap_error_details", "updated_at"):
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
                    self.env._(
                        "Cannot delete flow %s because it has already been sent.",
                        flow.display_name,
                    )
                )
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
            action.update(
                {
                    "views": False,
                    "view_id": False,
                    "res_id": move.id,
                    "view_mode": "form",
                }
            )
        else:
            raise UserError(
                self.env._("Flow %s is not linked to an invoice.", self.display_name)
            )
        return action
