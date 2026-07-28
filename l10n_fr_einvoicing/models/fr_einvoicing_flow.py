# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import logging
import time

from markupsafe import Markup
from stdnum.fr.siren import is_valid as siren_is_valid
from stdnum.fr.siren import to_tva as siren_to_vat
from stdnum.fr.siret import is_valid as siret_is_valid

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .res_partner import SUPERPDP_SANDBOX_SIREN

logger = logging.getLogger(__name__)

try:
    from pyfrctc import (
        generate_cdar,
        get_flow,
        get_flow_metadata_parsed,
        parse_cdar,
        send_flow_parsed,
    )
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
    odoo_invoice_format = fields.Selection(
        [
            ("facturx", "Factur-X"),
            ("ubl_pdf", "UBL XML with embedded PDF file"),
            ("ubl", "UBL XML"),
            ("cii_pdf", "CII XML with embedded PDF file"),
            ("cii", "CII XML"),
        ],
        readonly=True,
    )  # Only for out flows, when syntax in (UBL, CII, Factur-X)
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
            (
                "Undefined",
                "Not yet defined when in Pending state or unable to define "
                "when in Error state",
            ),
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
            ("generated", "Generated"),  # out
            ("downloaded", "Downloaded"),  # in
            ("sent", "Sent"),  # out
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
    move_id = fields.Many2one(
        "account.move", compute="_compute_move_id", store=True, string="Invoice"
    )
    event_ids = fields.One2many(
        "fr.einvoicing.event", "flow_id", readonly=True, string="Events"
    )
    event_id = fields.Many2one(
        "fr.einvoicing.event", compute="_compute_event_id", store=True
    )
    auto_internal_move_id = fields.Many2one(
        "account.move", string="Auto-generated Internal Refund/Invoice", readonly=True
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
    def _compute_move_id(self):
        for flow in self:
            if flow.move_ids and len(flow.move_ids) == 1:
                flow.move_id = flow.move_ids

    @api.depends("event_ids")
    def _compute_event_id(self):
        for flow in self:
            if flow.event_ids and len(flow.event_ids) == 1:
                flow.event_id = flow.event_ids

    def generate_button(self):
        log_obj = self.env["fr.einvoicing.log"]
        company = self[0].company_id
        result = {
            "log_type": "flow_generate",
            "log_origin": "Generate File button",
            "company_id": company.id,
            "logs": [],
            "updated_count": 0,
        }
        msg = f"File generation requested on {len(self)} flow(s) IDs {self.ids}"
        log_obj._info_log(result, msg)
        for flow in self:
            assert flow.company_id == company
            flow._generate(result)
        return self._create_log_prepare_notif_action(
            result,
            self.env._("Generate flow file"),
            self.env._("%(count)s flow file(s) successfully generated."),
            self.env._("No flow file generated."),
            self.env._(
                "%(count)s flow file(s) failed to be generated: see logs for error."
            ),
        )

    def _generate(self, result):
        self.ensure_one()
        log_obj = self.env["fr.einvoicing.log"]
        move_obj = self.env["account.move"]
        if self.direction != "out":
            msg = (
                f"Skipping generation of flow {self.display_name} ID {self.id} "
                f"because its direction is {self.direction}"
            )
            log_obj._info_log(result, msg)
            return
        if self.state != "created":
            msg = (
                f"Skipping generation of flow {self.display_name} ID {self.id} "
                f"because its state is '{self.state}' and not 'created'"
            )
            log_obj._info_log(result, msg)
            return
        if self.file_bin:
            msg = (
                f"Skipping flow {self.display_name} ID {self.id} because there is "
                "already an attached file"
            )
            log_obj._warning_log(result, msg)
            return
        if self.event_ids:
            assert len(self.event_ids) == 1
            event = self.event_ids
            saxon_server_url = move_obj._get_specific_saxon_server_url()
            try:
                data_dict = event._prepare_xml_data()
                xml_bytes = generate_cdar(
                    data_dict, check_schematron=True, saxon_server_url=saxon_server_url
                )
                file_b64 = base64.encodebytes(xml_bytes)
            except Exception as err:
                msg = (
                    f"Error in the generation of CDAR file for "
                    f"flow {self.display_name} ID {self.id}: {err}"
                )
                log_obj._error_log(result, msg)
                vals = {"state": "error", "odoo_error_details": str(err)}
                self.sudo().write(vals)
                return
            filename_suffix = ""
            if event.move_id.state == "posted":
                filename_suffix = f"_{event.move_id.name.replace('/', '_')}"
            filename = f"cdar_{event.status}{filename_suffix}.xml"
        elif self.move_ids:
            assert len(self.move_ids) == 1
            move = self.move_ids
            if self.syntax in ("Factur-X", "UBL", "CII"):
                filename = move._prepare_en16931_filename(self.odoo_invoice_format)
                try:
                    file_b64 = move._get_en16931_invoice_bin(
                        self.odoo_invoice_format, b64=True
                    )
                except Exception as err:
                    msg = (
                        f"Error in the generation of the {self.syntax} file for "
                        f"flow {self.display_name} ID {self.id}: {err}"
                    )
                    log_obj._error_log(result, msg)
                    vals = {"state": "error", "odoo_error_details": str(err)}
                    self.sudo().write(vals)
                    return
            else:
                raise ValueError(
                    f"Syntax '{self.syntax}' is not applicable for invoices"
                )
        else:
            raise UserError(
                self.env._(
                    "A flow should be linked either to an invoice or to an event. "
                    "This should never happen."
                )
            )
        vals = {
            "state": "generated",
            "file_bin": file_b64,
            "filename": filename,
        }
        self.sudo().write(vals)
        if "updated_count" in result:
            result["updated_count"] += 1

    def send_button(self):
        """For multiple flows, but all from the same company"""
        # we can't raise an error here in the loop because,
        # if an invoice has been sent, the write should not be rolled-backed
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        result = {
            "log_type": "flow_send",
            "log_origin": "Send button",
            "company_id": company.id,
            "logs": [],
            "updated_count": 0,
        }
        msg = f"Send requested on {len(self)} flow(s) IDs {self.ids}"
        self.env["fr.einvoicing.log"]._info_log(result, msg)
        for flow in self:
            assert flow.company_id == company
            flow._send(session, result)
        return self._create_log_prepare_notif_action(
            result,
            self.env._("Send flows"),
            self.env._("%(count)s flow(s) successfully sent."),
            self.env._("No flow sent."),
            self.env._("%(count)s flow(s) failed to be sent: see logs for error."),
        )

    def _create_log_prepare_notif_action(
        self, result, title, success_msg, no_msg, failure_msg
    ):
        self.env["fr.einvoicing.log"]._create_log(result)
        msg_list = []
        notif_type = "success"
        if result["updated_count"]:
            msg_list.append(success_msg % {"count": result["updated_count"]})
        else:
            msg_list.append(no_msg)
        if result["warning_count"]:
            notif_type = "warning"
            msg_list.append(
                self.env._("%(count)s warning(s).", count=result["warning_count"])
            )
        if result["error_count"]:
            notif_type = "danger"
            msg_list.append(failure_msg % {"count": result["error_count"]})

        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notif_type,
                "title": title,
                "message": " ".join(msg_list),
                "next": {  # refresh data on current page
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }
        return action

    def _send(self, session, result):
        self.ensure_one()
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "out":
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} "
                f"because its direction is {self.direction}"
            )
            log_obj._info_log(result, msg)
            return
        if self.state != "generated":
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} "
                f"because its state is '{self.state}' and not 'generated'"
            )
            log_obj._info_log(result, msg)
            return
        if not self.file_bin:
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} because there "
                "is no attached file"
            )
            log_obj._warning_log(result, msg)
            return
        if not self.filename:
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} because the "
                "filename is not set"
            )
            log_obj._warning_log(result, msg)
            return
        if not self.syntax:
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} because the "
                "syntax is not set"
            )
            log_obj._warning_log(result, msg)
            return
        if not self.processing_rule:
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} because the "
                "processing rule is not set"
            )
            log_obj._warning_log(result, msg)
            return
        if self.identifier:
            msg = (
                f"Skip sending of flow {self.display_name} ID {self.id} because it "
                "already has an identifier, which means it has already been sent"
            )
            log_obj._warning_log(result, msg)
            return
        file_bin = base64.decodebytes(self.file_bin)
        try:
            res = send_flow_parsed(
                session, file_bin, self.filename, self.syntax, self.processing_rule
            )
        except Exception as err:
            msg = f"Error while sending flow {self.display_name} ID {self.id}: {err}"
            log_obj._error_log(result, msg)
            flow_vals = {"odoo_error_details": str(err)}
            self.sudo().write(flow_vals)
            return
        # from pprint import pprint
        # pprint(res)
        # { 'flowId': 'i_45425',
        #   'flowSyntax': 'Factur-X',
        #    'submittedAt': '2026-04-30T13:10:47.360918Z'}
        flow_vals = {
            "identifier": res.get("flowId"),
            "submitted_at": res.get("submitted_at"),
            "updated_at": res.get("submitted_at"),
            "state": "sent",
            "odoo_error_details": False,
        }
        self.sudo().write(flow_vals)
        if "updated_count" in result:
            result["updated_count"] += 1
        if self.move_ids:
            self.move_ids.filtered(lambda x: not x.is_move_sent).sudo().write(
                {"is_move_sent": True}
            )

    def download_button(self):
        log_obj = self.env["fr.einvoicing.log"]
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        result = {
            "log_type": "flow_download",
            "log_origin": "Download button",
            "company_id": company.id,
            "logs": [],
            "updated_count": 0,
        }
        msg = f"Download requested on {len(self)} flow(s) IDs {self.ids}"
        log_obj._info_log(result, msg)
        for flow in self:
            assert flow.company_id == company
            flow._download(session, result)

        return self._create_log_prepare_notif_action(
            result,
            self.env._("Download from AP"),
            self.env._("%(count)s flow(s) successfully downloaded."),
            self.env._("No flow downloaded."),
            self.env._(
                "%(count)s flow(s) failed to be downloaded: see logs for error."
            ),
        )

    def _download(self, session, result):
        self.ensure_one()
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "in":
            msg = (
                f"No download for flow {self.display_name} ID {self.id} "
                f"because its direction is {self.direction}"
            )
            log_obj._info_log(result, msg)
            return
        if self.state != "created":
            msg = (
                f"No download for flow {self.display_name} ID {self.id} "
                f"because its state is '{self.state}' and not 'created'"
            )
            log_obj._info_log(result, msg)
            return
        if not self.identifier:
            msg = (
                f"Missing identifier on flow {self.display_name} ID {self.id}: "
                f"no download"
            )
            log_obj._warning_log(result, msg)
            return
        try:
            file_bin = get_flow(session, self.identifier, doc_type="Original")
        except Exception as err:
            msg = (
                f"Failed to download flow {self.display_name} ID {self.id}. "
                f"Error: {err}"
            )
            log_obj._error_log(result, msg)
            return
        file_b64 = base64.encodebytes(file_bin)
        if self.syntax == "Factur-X":
            filename = f"{self.identifier}.pdf"
        else:
            filename = f"{self.identifier}.xml"
        self.sudo().write(
            {
                "file_bin": file_b64,
                "filename": filename,
                "state": "downloaded",
            }
        )
        msg = f"Successful download of flow {self.display_name}: file {filename} saved"
        log_obj._info_log(result, msg)
        if "updated_count" in result:
            result["updated_count"] += 1

    def process_button(self):
        log_obj = self.env["fr.einvoicing.log"]
        company = self[0].company_id
        result = {
            "log_type": "flow_process",
            "log_origin": "Process button",
            "company_id": company.id,
            "logs": [],
            "updated_count": 0,
        }
        msg = f"Processing requested on {len(self)} flow(s) IDs {self.ids}"
        log_obj._info_log(result, msg)
        for flow in self:
            assert flow.company_id == company
            flow._process(result)
        return self._create_log_prepare_notif_action(
            result,
            self.env._("Process flows"),
            self.env._("%(count)s flow(s) successfully processed."),
            self.env._("No flow processed."),
            self.env._("%(count)s flow(s) failed to be processed: see logs for error."),
        )

    def _import_supplier_invoice(self, result):
        """Method inherited in l10n_fr_einvoicing_import
        If you don't want to use the OCA module account_invoice_import, you can develop
        an alternative to l10n_fr_einvoicing_import and inherit this method"""
        self.ensure_one()
        return False

    def _process(self, result):  # noqa: C901
        self.ensure_one()
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "in":
            msg = (
                f"Skipping flow {self.display_name} ID {self.id} "
                f"because its direction is {self.direction}"
            )
            log_obj._info_log(result, msg)
            return
        if self.state != "downloaded":
            msg = (
                f"Skipping flow {self.display_name} ID {self.id} because its state "
                f"is '{self.state}' and not 'downloaded'"
            )
            log_obj._info_log(result, msg)
            return
        if not self.file_bin:
            msg = (
                f"Skipping flow {self.display_name} ID {self.id} because there is "
                "no file attached"
            )
            log_obj._warning_log(result, msg)
            return
        msg = f"Start to process flow {self.display_name} ID {self.id} type {self.type}"
        log_obj._info_log(result, msg)
        if self.type == "SupplierInvoice":
            move_id = error = None
            try:
                move_id = self._import_supplier_invoice(result)
            except Exception as err:
                error = str(err)
                msg = (
                    f"Error in creation of the supplier invoice/refund from flow "
                    f"{self.display_name} ID {self.id}: {error}"
                )
                log_obj._warning_log(result, msg)
            if move_id:
                flow_vals = {"state": "done"}
                if "updated_count" in result:
                    result["updated_count"] += 1
                if self.company_id.fr_ctc_event_auto_send_in_hand:
                    move = self.env["account.move"].browse(move_id)
                    event = move._fr_ctc_create_simple_event("in_hand")
                    msg = (
                        f"In hand event ID {event.id} successfully created "
                        f"for invoice ID {move_id}"
                    )
                    log_obj._info_log(result, msg)
            else:
                err_details = "Odoo failed to created the supplier invoice/refund."
                if error:
                    err_details += f" Error: {error}"
                flow_vals = {
                    "state": "error",
                    "odoo_error_details": err_details,
                }
                msg = (
                    f"Odoo failed to create the supplier invoice/refund. "
                    f"Flow {self.display_name} ID {self.id} set to error state."
                )
                log_obj._warning_log(result, msg)
            self.sudo().write(flow_vals)

        elif self.type in (
            "CustomerInvoiceLC",
            "SupplierInvoiceLC",
            "StateCustomerInvoiceLC",
            "StateSupplierInvoiceLC",
        ):
            # We could imagine that the LC flow can arrive BEFORE invoice flow
            # but I have never seen it so far, so probably PA is giving
            # us the flows in an order where invoices arrives before all
            # its LC
            event_dict = None
            try:
                xml_bytes = base64.decodebytes(self.file_bin)
                event_dict = parse_cdar(xml_bytes)
                logger.debug(
                    "Successful parsing of CDAR XML: event_dict=%s", event_dict
                )
            except Exception as err:
                msg = (
                    f"Error in the parsing of the CDAR XML file from flow "
                    f"{self.display_name} ID {self.id}: {err}"
                )
                log_obj._warning_log(result, msg)
                flow_vals = {
                    "state": "error",
                    "odoo_error_details": str(err),
                }
            if event_dict:
                move = self._match_invoice_from_event(event_dict, result)
                if move:
                    event = self._create_event(event_dict, move)
                    flow_vals = {"state": "done"}
                    if (
                        event.status in ("refused", "rejected")
                        and self.company_id.fr_ctc_auto_reverse
                    ):
                        try:
                            flow_vals["auto_internal_move_id"] = (
                                self._auto_reverse_invoice(event, result)
                            )
                        except Exception as err:
                            msg = (
                                f"Auto-reverse triggered by event {event.display_name} "
                                f"ID {event.id} failed. Error: {str(err)}"
                            )
                            log_obj._warning_log(result, msg)

                    if "updated_count" in result:
                        result["updated_count"] += 1
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

    def _match_invoice_from_event(self, event_dict, result):
        self.ensure_one()
        assert self.type in (
            "CustomerInvoiceLC",
            "SupplierInvoiceLC",
            "StateCustomerInvoiceLC",
            "StateSupplierInvoiceLC",
        )
        domain = move = None
        if self.type in ("CustomerInvoiceLC", "StateCustomerInvoiceLC"):
            domain = [
                ("name", "=", event_dict["invoice_number"]),
                ("company_id", "=", self.company_id.id),
                ("move_type", "in", ("out_invoice", "out_refund")),
            ]
        elif self.type in ("SupplierInvoiceLC", "StateSupplierInvoiceLC"):
            partner = self._match_partner_from_event(event_dict, result)
            if partner:
                domain = [
                    ("ref", "=", event_dict["invoice_number"]),
                    ("company_id", "=", self.company_id.id),
                    ("move_type", "in", ("in_invoice", "in_refund")),
                    ("commercial_partner_id", "=", partner.id),
                ]
        if domain:
            move = self.env["account.move"].search(domain, limit=1)
            if not move:
                logger.warning("No invoice found with domain %s", domain)
        return move

    def _match_partner_from_event(self, event_dict, result):
        log_obj = self.env["fr.einvoicing.log"]
        partner = None
        invoice_issuer = event_dict.get("invoice_issuer")
        if invoice_issuer:
            base_domain = [
                ("parent_id", "=", False),
                ("company_id", "in", (False, self.company_id.id)),
            ]
            if invoice_issuer.get("0009"):
                siret = invoice_issuer["0009"].replace(" ", "")
                if not siret_is_valid(siret):
                    msg = f"SIRET {siret} written in event file is invalid"
                    log_obj._warning_log(result, msg)
                else:
                    partner = self.env["res.partner"].search(
                        base_domain + [("siret", "=", siret)], limit=1
                    )
                    if partner:
                        msg = (
                            f"Partner {partner.display_name} ID {partner.id} "
                            f"found with SIRET {siret}"
                        )
                        log_obj._info_log(result, msg)
            siren = False
            if not partner and invoice_issuer.get("0002"):
                siren = invoice_issuer["0002"].replace(" ", "")
                if not siren_is_valid(siren) and siren not in SUPERPDP_SANDBOX_SIREN:
                    msg = f"SIREN {siren} written in event file is invalid."
                    log_obj._warning_log(result, msg)
                else:
                    partner = self.env["res.partner"].search(
                        base_domain + [("siren", "=", siren)], limit=1
                    )
                    if partner:
                        msg = (
                            f"Partner {partner.display_name} ID {partner.id} "
                            f"found with SIREN {siren}"
                        )
                        log_obj._info_log(result, msg)
                    else:
                        # French VAT number computed from SIREN
                        vat = f"FR{siren_to_vat(siren)}"
                        partner = self.env["res.partner"].search(
                            base_domain + [("vat", "=", vat)], limit=1
                        )
                        if partner:
                            msg = (
                                f"Partner {partner.display_name} ID {partner.id} "
                                f"found with VAT {vat} computed from SIREN {siren}"
                            )
                            log_obj._info_log(result, msg)
            if not partner:
                msg = f"No partner found with SIREN {siren}"
                log_obj._warning_log(result, msg)
        return partner

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

    def _auto_reverse_invoice(self, event, result):
        move = event.move_id
        log_obj = self.env["fr.einvoicing.log"]
        if not move.is_sale_document():
            msg = (
                f"No auto-reversal because invoice {move.display_name} ID {move.id} "
                f"is not a sale document"
            )
            log_obj._warning_log(result, msg)
            return False
        elif move.state != "posted":
            msg = (
                f"No auto-reversal because invoice {move.display_name} "
                f"ID {move.id} has state={move.state}"
            )
            log_obj._warning_log(result, msg)
            return False
        if move.reversal_move_ids:
            msg = (
                f"No auto-reversal because invoice {move.display_name} "
                f"ID {move.id} has already been reversed"
            )
            log_obj._warning_log(result, msg)
            return False
        lang = move.partner_id.lang
        status_label = dict(
            event._fields["status"]._description_selection(
                self.with_context(lang=lang).env
            )
        ).get(event.status)
        default_reverse_vals = {
            "fr_einvoicing_internal": True,
            "invoice_origin": self.env._(
                "Auto-reverse on %(status)s event", status=status_label
            ),
            "ref": self.with_context(lang=lang).env._(
                "Reversal of %(move)s following %(status)s event",
                status=status_label,
                move=move.display_name,
            ),
        }
        reversed_move = move._reverse_moves([default_reverse_vals], cancel=True)
        reversed_move.message_post(
            body=Markup(
                self.env._(
                    "Auto-created because the option "
                    "<strong>Auto Reverse Invoice if Refused/Rejected</strong> "
                    "is enabled and event "
                    "<a href=# data-oe-model=fr.einvoicing.event "
                    "data-oe-id=%(event_id)s>%(event)s</a> has been received on "
                    "<a href=# data-oe-model=account.move "
                    "data-oe-id=%(move_id)s>%(move)s</a>.",
                    event_id=event.id,
                    event=event.display_name,
                    move_id=move.id,
                    move=move.display_name,
                )
            )
        )
        move.message_post(
            body=Markup(
                self.env._(
                    "Auto-reversed by "
                    "<a href=# data-oe-model=account.move "
                    "data-oe-id=%(reversed_move_id)s>%(reversed_move)s</a> because "
                    "the option <strong>Auto Reverse Invoice if "
                    "Refused/Rejected</strong> is enabled and event "
                    "<a href=# data-oe-model=fr.einvoicing.event "
                    "data-oe-id=%(event_id)s>%(event)s</a> has been received "
                    "on this invoice.",
                    event_id=event.id,
                    event=event.display_name,
                    reversed_move_id=reversed_move.id,
                    reversed_move=reversed_move.display_name,
                )
            )
        )
        msg = (
            f"Invoice {move.display_name} ID {move.id} has been auto-reversed: "
            f"{reversed_move.display_name} ID {reversed_move.id}"
        )
        log_obj._info_log(result, msg)
        return reversed_move.id

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
                        "date": doc_characteristic.get("date"),
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

    def update_status_button(self):
        log_obj = self.env["fr.einvoicing.log"]
        company = self[0].company_id
        session = company._fr_ctc_get_session()
        result = {
            "log_type": "flow_update_status",
            "log_origin": "Update Status button",
            "company_id": company.id,
            "logs": [],
            "updated_count": 0,
        }
        msg = f"Status update requested on {len(self)} flow(s) IDs {self.ids}"
        log_obj._info_log(result, msg)
        for flow in self:
            assert flow.company_id == company
            flow._update_status(session, result)
        return self._create_log_prepare_notif_action(
            result,
            self.env._("Flow status update"),
            self.env._("%(count)s flow(s) status updated."),
            self.env._("No flow status updated."),
            self.env._(
                "%(count)s flow status failed to be updated: see logs for error."
            ),
        )

    def _update_status(self, session, result):
        self.ensure_one()
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "out":
            msg = (
                f"Skipping status update of flow {self.display_name} ID {self.id} "
                f"because its direction is {self.direction}"
            )
            log_obj._info_log(result, msg)
            return
        if self.state != "sent":
            msg = (
                f"Skipping status update of flow {self.display_name} ID {self.id} "
                f"because its state is '{self.state}' and not 'sent'"
            )
            log_obj._info_log(result, msg)
            return
        if not self.identifier:
            msg = (
                f"Skipping status update of flow {self.display_name} ID {self.id} "
                f"because its identifier is missing"
            )
            log_obj._warning_log(result, msg)
            return
        try:
            res = get_flow_metadata_parsed(session, self.identifier)
        except Exception as err:
            msg = (
                f"Error while updating status of flow {self.display_name} "
                f"ID {self.id}: {err}"
            )
            log_obj._error_log(result, msg)
            flow_vals = {"odoo_error_details": str(err)}
            self.sudo().write(flow_vals)
            return
        # print("update_status res=")
        # pprint(res)
        vals = {}
        for key in ("state", "ap_error_details", "updated_at"):
            if res.get(key):
                vals[key] = res[key]
        if vals:
            self.sudo().write(vals)
        if vals.get("state"):
            msg = (
                f"Successful status update of flow {self.display_name} ID {self.id}. "
                f"New state: '{vals['state']}'"
            )
            if "updated_count" in result:
                result["updated_count"] += 1

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
                        "Cannot delete flow %s because it has an identifier.",
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

    @api.model
    def _cron_companies(self):
        companies = (
            self.env["res.company"]
            .sudo()
            .search(
                [
                    ("fr_ctc_accredited_platform", "!=", False),
                    ("fr_ctc_auth_method", "!=", False),
                    # line below will probably be removed one day, if we see that
                    # companies also send to non-assujetis entities using the
                    # PEPPOL directory (instead of the PPF directory)
                    ("partner_id.fr_directory_entity_type", "=", "private"),
                ]
            )
        )
        return companies

    @api.model
    def _in_cron(self):
        log_obj = self.env["fr.einvoicing.log"]
        result = {
            "log_type": "flow_import_all",
            "log_origin": "Cron",
            "company_id": False,
            "logs": [],
            "new_count": 0,
        }
        log_obj._info_log(result, "Start FR einvoicing flow import cron")
        for company in self._cron_companies():
            log_obj._info_log(
                result, f"Start to import in company {company.display_name}"
            )
            try:
                session = company._fr_ctc_get_session()
            except Exception as err:
                msg = (
                    f"Failed to get a session in company {company.display_name}. "
                    f"Error: {err}"
                )
                log_obj._error_log(result, msg)
                continue
            company._fr_ctc_run_import(session, result)
            base_domain = [("direction", "=", "in"), ("company_id", "=", company.id)]
            flows_left_to_download = self.sudo().search(
                base_domain + [("state", "=", "created")]
            )
            if flows_left_to_download:
                msg = (
                    f"Found {len(flows_left_to_download)} incoming flows that are "
                    "still waiting to be downloaded"
                )
                log_obj._info_log(result, msg)
                for flow in flows_left_to_download:
                    flow._download(session, result)
            flows_left_to_process = self.sudo().search(
                base_domain + [("state", "=", "downloaded")]
            )
            if flows_left_to_process:
                msg = (
                    f"Found {len(flows_left_to_process)} incoming flows that are "
                    "still waiting to be processed"
                )
                log_obj._info_log(result, msg)
                for flow in flows_left_to_process:
                    flow._process(result)
        log_obj._info_log(result, "End of FR einvoicing flow import cron")
        log_obj._create_log(result)

    @api.model
    def _out_cron(self):
        log_obj = self.env["fr.einvoicing.log"]
        result = {
            "log_type": "flow_send_all",
            "log_origin": "Cron",
            "company_id": False,
            "logs": [],
            "new_count": 0,
            "updated_count": 0,
        }
        log_obj._info_log(result, "Start FR einvoicing outgoing flow cron")
        for company in self._cron_companies():
            log_obj._info_log(
                result,
                f"Start to process outgoing flows in company {company.display_name}",
            )
            try:
                session = company._fr_ctc_get_session()
            except Exception as err:
                msg = (
                    f"Failed to get a session in company {company.display_name}. "
                    f"Error: {err}"
                )
                log_obj._error_log(result, msg)
                continue
            base_domain = [("direction", "=", "out"), ("company_id", "=", company.id)]
            flows_to_generate = self.sudo().search(
                base_domain + [("state", "=", "created")]
            )
            if flows_to_generate:
                msg = (
                    f"Found {len(flows_to_generate)} outgoing flows that are "
                    "waiting to be generated"
                )
                log_obj._info_log(result, msg)
                for flow in flows_to_generate:
                    flow._generate(result)
            flows_to_send = self.sudo().search(
                base_domain + [("state", "=", "generated")]
            )
            if flows_to_send:
                msg = (
                    f"Found {len(flows_to_send)} outgoing flows that are "
                    "waiting to be sent"
                )
                log_obj._info_log(result, msg)
                for flow in flows_to_send:
                    flow._send(session, result)
            logger.debug("sleep a few seconds before updating status")
            time.sleep(3)
            update_status_flows = self.sudo().search(
                base_domain + [("state", "=", "sent")], order="id"
            )
            if update_status_flows:
                msg = (
                    f"Found {len(update_status_flows)} sent flows waiting for a "
                    "status update"
                )
                log_obj._info_log(result, msg)
                for flow in update_status_flows:
                    flow._update_status(session, result)
        log_obj._info_log(result, "End of FR einvoicing outgoing flow cron")
        log_obj._create_log(result)

    def back2created_button(self):
        self.ensure_one()
        assert self.state == "error"
        self.sudo().write(
            {
                "state": "created",
                "file_bin": False,
                "filename": False,
                "ap_error_details": False,
                "odoo_error_details": False,
            }
        )
        # TODO: log ?
