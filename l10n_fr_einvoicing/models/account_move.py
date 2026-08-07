# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import os.path

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.tools.misc import formatLang

logger = logging.getLogger(__name__)

try:
    from pyfrctc import get_flow
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)

# Variables for invoice attachments on Chorus Pro
CHORUS_FILENAME_MAX = 50
CHORUS_FILESIZE_MAX_MO = 10
CHORUS_ALLOWED_EXTENSIONS = [
    ".BMP",
    ".GIF",
    ".FAX",
    ".ODT",
    ".PPT",
    ".TIFF",
    ".XLS",
    ".BZ2",
    ".GZ",
    ".JPEG",
    ".P7S",
    ".RTF",
    ".TXT",
    ".XML",
    ".CSV",
    ".GZIP",
    ".JPG",
    ".PDF",
    ".SVG",
    ".XHTML",
    ".XLSX",
    ".DOC",
    ".HTM",
    ".ODP",
    ".PNG",
    ".TGZ",
    ".XLC",
    ".ZIP",
    ".DOCX",
    ".HTML",
    ".ODS",
    ".PPS",
    ".TIF",
    ".XLM",
    ".PPTX",
]


class AccountMove(models.Model):
    _inherit = "account.move"

    fr_directory_company_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type",
        string="Company Directory Entity Type",
    )
    fr_directory_partner_entity_type = fields.Selection(
        related="commercial_partner_id.fr_directory_entity_type",
        string="Customer Directory Entity Type",
    )
    fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_fr_directory_line_id",
        store=True,
        precompute=True,
        readonly=False,
        tracking=True,
        ondelete="restrict",
        string="Directory Line",
        domain="[('partner_id', '=', commercial_partner_id), ('state', '=', 'active')]",
    )
    # fr_directory_line_identifier is NOT a related field because, for a supplier
    # invoice, the supplier may not have its directory lines in Odoo, so we would
    # just write the identifier as a Char on the field below
    fr_directory_line_identifier = fields.Char(
        compute="_compute_fr_directory_line_identifier",
        store=True,
        readonly=False,
        string="Directory Line Identifier",
    )
    company_partner_id = fields.Many2one(
        related="company_id.partner_id", string="Company Partner"
    )
    company_fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        compute="_compute_company_fr_directory_line_id",
        store=True,
        precompute=True,
        readonly=False,
        ondelete="restrict",
        string="Company Directory Line",
        domain="[('partner_id', '=', company_partner_id), ('state', '=', 'active')]",
    )
    fr_einvoicing_flow_id = fields.Many2one(
        "fr.einvoicing.flow",
        readonly=True,
        string="Flow",
        copy=False,
        check_company=True,
    )
    fr_einvoicing_flow_state = fields.Selection(
        related="fr_einvoicing_flow_id.state", store=True, string="Flow State"
    )
    fr_einvoicing_flow_submitted_at = fields.Datetime(
        related="fr_einvoicing_flow_id.submitted_at", store=True, string="Flow Sent on"
    )
    fr_einvoicing_event_ids = fields.One2many(
        "fr.einvoicing.event", "move_id", readonly=True, string="Events"
    )
    fr_einvoicing_last_event_id = fields.Many2one(
        "fr.einvoicing.event",
        compute="_compute_last_event",
        store=True,
        check_company=True,
        string="Last Event",
    )
    fr_einvoicing_last_event_decoration = fields.Char(
        related="fr_einvoicing_last_event_id.status_decoration", store=True
    )
    fr_einvoicing_show_readable_invoice_button = fields.Boolean(
        compute="_compute_fr_einvoicing_show_readable_invoice_button",
        store=True,
        readonly=False,
    )
    fr_einvoicing_required = fields.Boolean(
        compute="_compute_einvoicing_required",
        string="E-invoicing Required",
    )

    _sql_constraints = [
        (
            "fr_einvoicing_flow_unique",
            "unique(fr_einvoicing_flow_id)",
            "Each invoice must be linked to a different flow.",
        )
    ]

    @api.depends("fr_einvoicing_event_ids")
    def _compute_last_event(self):
        for move in self:
            last_event_id = (
                move.fr_einvoicing_event_ids
                and move.fr_einvoicing_event_ids[0].id
                or False
            )
            move.fr_einvoicing_last_event_id = last_event_id

    @api.depends("company_id", "partner_id")
    def _compute_fr_directory_line_id(self):
        for move in self:
            fr_directory_line_id = False
            cpartner = move.commercial_partner_id
            if (
                move.is_sale_document()
                and move.company_id._fr_ctc_is_vat_registered()
                and cpartner.fr_directory_entity_type in ("private", "public")
            ):
                if move.partner_id.default_fr_directory_line_id:
                    fr_directory_line_id = (
                        move.partner_id.default_fr_directory_line_id.id
                    )
                elif cpartner.default_fr_directory_line_id:
                    fr_directory_line_id = cpartner.default_fr_directory_line_id.id
                if not fr_directory_line_id:
                    dir_lines = self.env["fr.directory.line"].search(
                        [("partner_id", "=", cpartner.id), ("state", "=", "active")]
                    )
                    if len(dir_lines) == 1:
                        fr_directory_line_id = dir_lines.id
            move.fr_directory_line_id = fr_directory_line_id

    @api.depends(
        "fr_directory_company_entity_type",
        "fr_directory_partner_entity_type",
        "move_type",
        "company_id.fr_ctc_send_out_invoice",
    )
    def _compute_einvoicing_required(self):
        for move in self:
            fr_einvoicing_required = False
            send_out_invoice = move.company_id.fr_ctc_send_out_invoice
            if (
                move.is_sale_document()
                and move.fr_directory_company_entity_type == "private"
            ):
                if (
                    send_out_invoice == "all"
                    and move.fr_directory_partner_entity_type in ("public", "private")
                ) or (
                    send_out_invoice == "b2b"
                    and move.fr_directory_partner_entity_type == "private"
                ) or (
                    send_out_invoice == "b2g"
                    and move.fr_directory_partner_entity_type == "public"
                ):
                    fr_einvoicing_required = True
            move.fr_einvoicing_required = fr_einvoicing_required

    @api.depends("fr_directory_line_id")
    def _compute_fr_directory_line_identifier(self):
        for move in self:
            if move.fr_directory_line_id:
                move.fr_directory_line_identifier = move.fr_directory_line_id.identifier

    @api.depends("company_id")
    def _compute_company_fr_directory_line_id(self):
        for move in self:
            company_fr_directory_line_id = False
            if (
                move.is_sale_document()
                and move.company_id
                and move.company_id._fr_ctc_is_vat_registered()
            ):
                comp_partner = move.company_id.partner_id
                if comp_partner.default_fr_directory_line_id:
                    company_fr_directory_line_id = (
                        comp_partner.default_fr_directory_line_id
                    )
                elif comp_partner.fr_directory_line_ids:
                    company_fr_directory_line_id = (
                        comp_partner.fr_directory_line_ids.filtered(
                            lambda x: x.state == "active"
                        )[:1]
                    )
            move.company_fr_directory_line_id = company_fr_directory_line_id

    @api.constrains("business_process_type", "commercial_partner_id")
    def _check_business_process_type_b2g(self):
        for move in self:
            if move.is_sale_document():
                # Rule BR-FR-CPRO-23
                if (
                    move.business_process_type == "fr_S3"
                    and move.commercial_partner_id.fr_directory_entity_type != "public"
                ):
                    raise ValidationError(
                        _(
                            "Business Process Type 'S3' can only be used for a "
                            "public-sector customer (rule BR-FR-CPRO-23). On invoice "
                            "'%(invoice)s', Business Process Type is 'S3' but the "
                            "customer (%(partner)s) is not a public-sector customer."
                        )
                        % {
                            "invoice": move.display_name,
                            "partner": self.commercial_partner_id.display_name,
                        }
                    )
                # Rule BR-FR-CPRO-24
                if (
                    move.business_process_type == "fr_S5"
                    and move.commercial_partner_id.fr_directory_entity_type == "public"
                ):
                    raise ValidationError(
                        _(
                            "Business Process Type 'S5' cannot be used for a "
                            "public-sector customer (rule BR-FR-CPRO-24). On invoice "
                            "'%(invoice)s', the customer (%(partner)s) is a "
                            "public-sector customer but Business Process Type "
                            "has been set to 'S5'."
                        )
                        % {
                            "invoice": move.display_name,
                            "partner": self.commercial_partner_id.display_name,
                        }
                    )

    def unlink(self):
        for move in self:
            if move.fr_einvoicing_flow_id:
                msg = _(
                    "Invoice '%(invoice)s' is linked to flow '%(flow)s', "
                    "so you cannot delete it."
                ) % {
                    "invoice": move.display_name,
                    "flow": move.fr_einvoicing_flow_id.display_name,
                }
                if move.state != "cancel":
                    add_msg = _("You can cancel it instead.")
                    msg = f"{msg} {add_msg}"
                raise UserError(msg)
        return super().unlink()

    def _fr_directory_sync_action_server(self):
        """Used by the ir.actions.server called by RedirectWarning()"""
        action = {}
        if self.env.context.get("fr_directory_sync_move_id"):
            move = self.browse(self.env.context["fr_directory_sync_move_id"])
            partner = move.commercial_partner_id
            try:
                partner._fr_directory_sync_logs(
                    move.company_id, "Invoice Redirect Warning"
                )
                move.message_post(
                    body=Markup(
                        _(
                            "Directory sync of <a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a>."
                        )
                        % {
                            "partner_id": partner.id,
                            "partner_name": partner.display_name,
                        }
                    )
                )
            except Exception as err:
                logger.warning(
                    "Failed to sync directory for partner %s. Error: %s",
                    move.commercial_partner_id.display_name,
                    err,
                )
                move.message_post(
                    body=Markup(
                        _(
                            "Failed to sync directory for partner <a href=# "
                            "data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a>."
                            "<br/>Error: %(err)s"
                        )
                        % {
                            "partner_id": partner.id,
                            "partner_name": partner.display_name,
                            "err": str(err),
                        }
                    )
                )
            action = self.env["ir.actions.actions"]._for_xml_id(
                "account.action_move_out_invoice_type"
            )
            action.update(
                {
                    "views": False,
                    "view_id": False,
                    "res_id": move.id,
                    "view_mode": "form,list",
                }
            )
        else:
            logger.error("Missing key fr_directory_sync_move_id in context")
        return action

    def _post(self, soft=True):
        for move in self:
            company = move.company_id
            if (
                move.is_sale_document()
                and company._fr_ctc_is_vat_registered(raise_if_misconfigured=True)
                and move.fr_einvoicing_required
            ):
                move._fr_ctc_sale_document_post_checks()
                move._fr_ctc_sale_document_create_flow()
            if (
                move.is_purchase_document()
                and move.fr_einvoicing_flow_id
                and company.fr_ctc_event_auto_send_approved
                and not move.fr_einvoicing_event_ids.filtered(
                    lambda ev: ev.status == "approved"
                )
            ):
                move._fr_ctc_create_simple_event("approved")
        return super()._post(soft=soft)

    def _fr_ctc_sale_document_create_flow(self):
        self.ensure_one()
        if self.commercial_partner_id.fr_directory_entity_type in ("public", "private"):
            flow_vals = self._fr_ctc_prepare_flow()
            flow = self.env["fr.einvoicing.flow"].sudo().create(flow_vals)
            self.sudo().write({"fr_einvoicing_flow_id": flow.id})
            logger.info(
                "Flow ID %s created for customer invoice %s ID %d",
                flow.id,
                self.display_name,
                self.id,
            )

    def _fr_ctc_sale_document_post_checks(self):  # noqa: C901
        self.ensure_one()
        today = fields.Date.context_today(self)
        cpartner = self.commercial_partner_id
        company = self.company_id
        dir_sync_done = False
        if (
            (
                not cpartner.fr_directory_entity_type
                or cpartner.fr_directory_entity_type == "private_inactive"
            )
            and cpartner.is_company
            and cpartner.is_france_country
            and cpartner._get_siren()
        ):
            try:
                cpartner._fr_directory_sync_logs(company, self.display_name)
                self._compute_fr_directory_line_id()
                dir_sync_done = True
                self.message_post(
                    body=Markup(
                        _(
                            "Successful directory sync of the french entity "
                            "<a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                            "that didn't have any directory status. "
                            "New directory status: "
                            "<strong>%(new_entity_type)s</strong>."
                        )
                        % {
                            "partner_id": cpartner.id,
                            "partner_name": cpartner.display_name,
                            "new_entity_type": dict(
                                cpartner._fields[
                                    "fr_directory_entity_type"
                                ]._description_selection(self.env)
                            ).get(cpartner.fr_directory_entity_type),
                        }
                    )
                )
            except Exception as err:
                logger.warning(
                    "Failed to update partner (triggered from customer "
                    "invoice/refund %s): %s",
                    self.display_name,
                    err,
                )
                self.message_post(
                    body=Markup(
                        _(
                            "Directory sync of the french entity "
                            "<a href=# data-oe-model=res.partner "
                            "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                            "that didn't have any directory status "
                            "<strong>failed</strong>.<br/>Error: %(err)s."
                        )
                        % {
                            "partner_id": cpartner.id,
                            "partner_name": cpartner.display_name,
                            "err": str(err),
                        }
                    )
                )
        if cpartner.fr_directory_entity_type in ("public", "private"):
            if (
                company.fr_ctc_directory_sync_on_invoice_post
                in ("blocking", "not_blocking")
                and not dir_sync_done
            ):
                if (
                    cpartner.fr_directory_last_sync_date
                    and cpartner.fr_directory_last_sync_date >= today
                ):
                    self.message_post(
                        body=Markup(
                            _(
                                "No query to the directory because the last "
                                "directory sync of "
                                "<a href=# data-oe-model=res.partner "
                                "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                                "was today."
                            )
                            % {
                                "partner_id": cpartner.id,
                                "partner_name": cpartner.display_name,
                            }
                        )
                    )
                else:
                    try:
                        cpartner._fr_directory_sync_logs(company, self.display_name)
                        dir_sync_done = True
                        self.message_post(
                            body=Markup(
                                _(
                                    "Successful directory sync of "
                                    "<a href=# data-oe-model=res.partner "
                                    "data-oe-id=%(partner_id)s>%(partner_name)s</a> "
                                    "upon confirmation."
                                )
                                % {
                                    "partner_id": cpartner.id,
                                    "partner_name": cpartner.display_name,
                                }
                            )
                        )
                    except Exception as err:
                        if company.fr_ctc_directory_sync_on_invoice_post == "blocking":
                            raise UserError(
                                _(
                                    "Failed to query the directory for partner "
                                    "'%(partner)s'. Error: %(err)s"
                                )
                                % {"partner": cpartner.display_name, "err": err}
                            ) from err
                        else:
                            logger.warning(
                                "Failed to update the directory for partner %s ID %s. "
                                "Error: %s",
                                cpartner.display_name,
                                cpartner.id,
                                err,
                            )
                            self.message_post(
                                body=Markup(
                                    _(
                                        "Directory sync of "
                                        "<a href=# data-oe-model=res.partner "
                                        "data-oe-id=%(partner_id)s>%(partner_name)s"
                                        "</a> <strong>failed</strong>."
                                        "<br/>Error: %(err)s."
                                    )
                                    % {
                                        "partner_id": cpartner.id,
                                        "partner_name": cpartner.display_name,
                                        "err": str(err),
                                    }
                                )
                            )
            err_msg = cpartner._fr_directory_confirm_common_checks()
            if err_msg:
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
            if not self.fr_directory_line_id:
                err_msg = (
                    _("No directory line selected on invoice '%s'.") % self.display_name
                )
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
            err_msg = self.fr_directory_line_id._confirm_common_checks(
                self.ref, self.display_name
            )
            if err_msg:
                self._fr_ctc_raise_error(err_msg, dir_sync_done)
            if not self.company_fr_directory_line_id:
                raise UserError(
                    _("No company directory line selected on invoice '%s'.")
                    % self.display_name
                )
            if self.company_fr_directory_line_id.state != "active":
                raise UserError(
                    _(
                        "On '%(invoice)s', the selected company directory line "
                        "'%(dir_line)s' is not active."
                    )
                    % {
                        "dir_line": self.company_fr_directory_line_id.display_name,
                        "invoice": self.display_name,
                    }
                )
        if cpartner.fr_directory_entity_type == "public":  # Chorus Pro checks
            if not company.partner_id._get_siret():  # BR-FR-CPRO-03
                raise UserError(
                    _(
                        "Invoice '%(invoice)s' is for a public entity and will be "
                        "routed to Chorus Pro, so company '%(company)s' "
                        "must have a SIRET."
                    )
                    % {"invoice": self.display_name, "company": company.display_name}
                )
            # 16.0: move.preferred_payment_method_line_id is 18.0-only. The 16.0
            # equivalent is the OCA payment_mode_id (account_payment_partner),
            # read defensively so the Chorus check is skipped rather than crashing
            # when that optional OCA module is not installed.
            if (
                not getattr(self, "payment_mode_id", False)
                and self.move_type == "out_invoice"
            ):
                raise UserError(
                    _(
                        "Missing Payment Method on invoice '%(invoice)s'. "
                        "This information is required for Chorus Pro."
                    )
                    % {"invoice": self.display_name}
                )
            # BR-FR-CPRO-30
            for attach in self.invoice_attachment_ids:
                self._fr_ctc_check_chorus_attachment(attach)

    def _fr_ctc_check_chorus_attachment(self, attach):
        # https://communaute.chorus-pro.gouv.fr/pieces-jointes-dans-chorus-pro-quelques-regles-a-respecter/ # noqa: B950,E501
        self.ensure_one()
        if len(attach.name) > CHORUS_FILENAME_MAX:
            raise UserError(
                _(
                    "On Chorus Pro, invoice attachment filenames "
                    "must have %(filename_max)s caracters maximum "
                    "(extension included). On invoice '%(invoice)s', "
                    "attachment '%(filename)s' has %(filename_size)s "
                    "caracters."
                )
                % {
                    "filename_max": CHORUS_FILENAME_MAX,
                    "filename": attach.name,
                    "invoice": self.display_name,
                    "filename_size": len(attach.name),
                }
            )
        filename, file_extension = os.path.splitext(attach.name)
        if not file_extension:
            raise UserError(
                _(
                    "On Chorus Pro, invoice attachments must have an extension. "
                    "On invoice '%(invoice)s', attachment '%(filename)s' doesn't "
                    "have any extension."
                )
                % {"invoice": self.display_name, "filename": attach.name}
            )
        if file_extension.upper() not in CHORUS_ALLOWED_EXTENSIONS:
            raise UserError(
                _(
                    "On Chorus Pro, the allowed file extensions for "
                    "invoice attachments are: %(extension_list)s.\n"
                    "On invoice '%(invoice)s', attachment '%(filename)s' "
                    "has extension '%(extension)s' which is not part of this list."
                )
                % {
                    "extension_list": ", ".join(CHORUS_ALLOWED_EXTENSIONS),
                    "invoice": self.display_name,
                    "filename": attach.name,
                    "extension": file_extension.upper(),
                }
            )
        if not attach.file_size:
            raise UserError(
                _(
                    "On invoice '%(invoice)s', the size of the attachment "
                    "'%(filename)s' is 0."
                )
                % {"invoice": self.display_name, "filename": attach.name}
            )
        filesize_mo = round(attach.file_size / (1024 * 1024), 1)
        if filesize_mo >= CHORUS_FILESIZE_MAX_MO:
            raise UserError(
                _(
                    "On Chorus Pro, each attachment cannot exceed %(size_max)s Mb. "
                    "On invoice '%(invoice)s', the size of attachment '%(filename)s' "
                    "is %(size)s Mb."
                )
                % {
                    "size_max": CHORUS_FILESIZE_MAX_MO,
                    "invoice": self.display_name,
                    "filename": attach.name,
                    "size": formatLang(self.env, filesize_mo),
                }
            )

    def _fr_ctc_raise_error(self, err_msg, dir_sync_done):
        self.ensure_one()
        if dir_sync_done:
            action = self.env.ref(
                "l10n_fr_einvoicing.fr_directory_sync_invoice_redirect_warning"
            )
            raise RedirectWarning(
                err_msg,
                action.id,
                _("Sync Customer Directory Now"),
                additional_context={"fr_directory_sync_move_id": self.id},
            )
        else:
            raise UserError(err_msg)

    def button_cancel(self):
        if (
            len(self) == 1
            and self.is_purchase_document()
            and self.fr_einvoicing_flow_id
            and not self.env.context.get("by_pass_refusal_event_wizard")
            and not self.fr_einvoicing_event_ids.filtered(
                lambda x: x.status == "refused"
            )
        ):
            action = self.env["ir.actions.actions"]._for_xml_id(
                "l10n_fr_einvoicing.fr_einvoicing_event_manual_action"
            )
            action["context"] = {
                "default_status_purchase": "refused",
                "default_status_readonly": True,
            }
            return action
        return super().button_cancel()

    def button_draft(self):
        # 16.0: there is no _check_draftable() hook (18.0-only, extracted from
        # button_draft). Inject the check directly in button_draft() instead.
        for move in self:
            if (
                move.is_sale_document()
                and move.fr_einvoicing_flow_id
                and not self.env.context.get("sudo_draftable_fr_einvoicing_flow")
            ):
                if move.fr_einvoicing_flow_id.state == "created":
                    logger.info(
                        f"Deleting flow {move.fr_einvoicing_flow_id.display_name} "
                        f"ID {move.fr_einvoicing_flow_id.id} state created to allow "
                        f"back to draft of invoice {move.display_name} ID {move.id}"
                    )
                    move.message_post(
                        body=_(
                            "Deleting the eInvoicing flow of this invoice that was "
                            "only in created state because of the reset to draft."
                        )
                    )
                    move.sudo().fr_einvoicing_flow_id.unlink()
                else:
                    raise UserError(
                        _(
                            "You cannot reset to draft '%s' because it is linked "
                            "to an eInvoicing flow that has already been generated."
                        )
                        % move.display_name
                    )
        return super().button_draft()

    def _fr_ctc_prepare_flow(self):
        self.ensure_one()
        partner_entity_type = self.commercial_partner_id.fr_directory_entity_type
        if partner_entity_type == "private":
            processing_rule = "B2B"
        elif partner_entity_type == "public":
            processing_rule = "B2G"
        else:
            processing_rule = "OutOfScope"
        odoo_invoice_format = self.company_id.fr_ctc_send_invoice_format or "facturx"
        odoo_invoice_format2SYNTAX = {
            "facturx": "Factur-X",
            "ubl_pdf": "UBL",
            "ubl": "UBL",
            "cii_pdf": "CII",
            "cii": "CII",
        }
        vals = {
            "direction": "out",
            "syntax": odoo_invoice_format2SYNTAX[odoo_invoice_format],
            "odoo_invoice_format": odoo_invoice_format,
            "processing_rule": processing_rule,
            "type": "CustomerInvoice",
            "company_id": self.company_id.id,
        }
        return vals

    def fr_ctc_send_invoice_immediately_button(self):
        self.ensure_one()
        assert self.fr_einvoicing_required
        assert self.state == "posted"
        flow = self.fr_einvoicing_flow_id
        assert flow
        assert flow.state in ("created", "generated")
        # TODO add logs ?
        result = {"logs": []}
        if flow.state == "created":
            flow._generate(result)
        if flow.state == "generated":
            session = self.company_id._fr_ctc_get_session()
            flow._send(session, result)

        # write is_move_sent=True is made by the _send() method

    def _fr_ctc_prepare_simple_event(self, status):
        self.ensure_one()
        vals = {
            "move_id": self.id,
            "company_id": self.company_id.id,
            "status": status,
            "direction": "out",
        }
        return vals

    def _fr_ctc_create_simple_event(self, status, post_message=True):
        self.ensure_one()
        event_vals = self._fr_ctc_prepare_simple_event(status)
        event = self.env["fr.einvoicing.event"].sudo().create(event_vals)
        if post_message:
            self.message_post(
                body=Markup(
                    _(
                        "Event <a href=# data-oe-model=fr.einvoicing.event "
                        "data-oe-id=%(event_id)s>%(event)s</a> "
                        "created automatically by Odoo."
                    )
                    % {"event": event.display_name, "event_id": event.id}
                )
            )
        return event

    def _fr_ctc_activity_warning_event_users(self, event):
        """Get users that will get a mail.activity when an event is received
        on an invoice. This method also fixes the conditions for the activity
        to be sent"""
        self.ensure_one()
        users = False
        if self.is_sale_document() and event.status_decoration in ("danger", "warning"):
            company = self.company_id
            users = company.fr_ctc_activity_warning_event_user_ids
            if company.fr_ctc_activity_warning_event_invoice_creator:
                users |= self.create_uid
            if company.fr_ctc_activity_warning_event_salesman and self.user_id:
                users |= self.user_id
        return users

    def _fr_ctc_prepare_activity_warning_event(self, event):
        # Field user_id is added later in the code, to avoid calling this method
        # too many times
        mail_activity_vals = {
            "res_id": self.id,
            "res_model_id": self.env.ref("account.model_account_move").id,
            "activity_type_id": self.env.ref(
                "l10n_fr_einvoicing.warning_invoice_event_mail_activity_type"
            ).id,
            "summary": _("Event %(event)s received on %(invoice)s")
            % {
                "event": event.display_name,
                "invoice": self.with_context(input_full_display_name=True).display_name,
            },
            "note": event.infos,
            "automated": True,
        }
        return mail_activity_vals

    @api.depends("fr_einvoicing_flow_id")
    def _compute_fr_einvoicing_show_readable_invoice_button(self):
        for move in self:
            show = False
            if (
                move.is_purchase_document()
                and move.fr_einvoicing_flow_id
                and move.fr_einvoicing_flow_id.syntax != "Factur-X"
            ):
                show = True
            move.fr_einvoicing_show_readable_invoice_button = show

    def fr_ctc_get_readable_invoice_button(self):
        self.ensure_one()
        attach_vals = self._fr_ctc_prepare_readable_attachment()
        attach = self.env["ir.attachment"].create(attach_vals)
        self.write({"fr_einvoicing_show_readable_invoice_button": False})
        msg = _("File %s added to the attachments of the vendor bill.") % attach.name
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Readable invoice successfully downloaded"),
                "message": msg,
            },
        }
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
            readable_file_bin = get_flow(
                session, flow.identifier, doc_type="ReadableView"
            )
        except Exception as err:
            raise UserError(
                _(
                    "Failed to get the readable version of vendor bill/refund "
                    "%(invoice)s. Error: %(err)s"
                )
                % {"invoice": self.display_name, "err": err}
            ) from err
        vals = {
            "res_model": self._name,
            "res_id": self.id,
            "name": filename,
            "raw": readable_file_bin,
        }
        return vals
