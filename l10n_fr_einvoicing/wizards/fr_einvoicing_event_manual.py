# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class FrEinvoicingEventManual(models.TransientModel):
    _name = "fr.einvoicing.event.manual"
    _description = "Create eInvoicing Event manually"

    move_id = fields.Many2one(
        "account.move", string="Invoice", readonly=True, required=True
    )
    move_type = fields.Selection(related="move_id.move_type")
    status_sale = fields.Selection(
        "_status_sale_selection", string="Status for Customer Invoice/Refunds"
    )
    status_purchase = fields.Selection(
        "_status_purchase_selection", string="Status for Vendor Bills/Refunds"
    )
    status_readonly = fields.Boolean(readonly=True)
    confirm = fields.Boolean()
    confirm_required = fields.Boolean(compute="_compute_required_fields")
    detail_required = fields.Boolean(compute="_compute_required_fields")
    detail_ids = fields.One2many(
        "fr.einvoicing.event.detail.manual", "event_id", string="Reasons and Actions"
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "fr_einvoicing_event_manual_attachment_rel",
        string="Attachments",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        assert self._context.get("active_model") == "account.move"
        res["move_id"] = self._context.get("active_id")
        move = self.env["account.move"].browse(res["move_id"])
        assert move.is_invoice() and move.fr_einvoicing_flow_id
        return res

    def _status_sale_selection(self):
        return self.env["fr.einvoicing.event"]._status_selection_manual("sale")

    def _status_purchase_selection(self):
        return self.env["fr.einvoicing.event"]._status_selection_manual("purchase")

    @api.depends("status_sale", "status_purchase", "move_id")
    def _compute_required_fields(self):
        for wiz in self:
            detail_required = False
            confirm_required = False
            if wiz.move_id.is_sale_document():
                status = wiz.status_sale
            else:
                status = wiz.status_purchase
            if status:
                status_dict = self.env["fr.einvoicing.event"]._get_all_status()[status]
                detail_required = status_dict.get("detail_required")
                confirm_required = status_dict.get("confirm_required")
            wiz.detail_required = detail_required
            wiz.confirm_required = confirm_required

    def _prepare_event_vals(self):
        self.ensure_one()
        status = (
            self.move_id.is_sale_document() and self.status_sale or self.status_purchase
        )
        vals = {
            "status": status,
            "direction": "out",
            "company_id": self.move_id.company_id.id,
            "move_id": self.move_id.id,
        }
        if self.attachment_ids:
            vals["attachment_ids"] = [
                Command.create({"name": x.name, "raw": x.raw})
                for x in self.attachment_ids
            ]
        if self.detail_required:
            vals["detail_ids"] = [
                Command.create(
                    {
                        "reason": x[f"reason_{status}"],
                        "comment": x.comment,
                        "action": x.action,
                    }
                )
                for x in self.detail_ids
            ]
        return vals

    def run(self):
        self.ensure_one()
        assert self.move_id
        status = (
            self.move_id.is_sale_document() and self.status_sale or self.status_purchase
        )
        if self.detail_required:
            if not self.detail_ids:
                raise UserError(
                    _("For this status, you must create at least one line of details.")
                )
        if self.confirm_required and not self.confirm:
            if status == "refused":
                raise UserError(
                    _(
                        "You must confirm the refusal of the vendor bill/refund, "
                        "or click on cancel. Reminder: the refusal is definitive. "
                        "On the contrary, if you want to block the vendor bill "
                        "temporarily, you should create an event 'Disputed'."
                    )
                )
            else:
                raise UserError(
                    _("You must confirm the creation of the event or click on cancel.")
                )
        event = (
            self.env["fr.einvoicing.event"].sudo().create(self._prepare_event_vals())
        )
        self.move_id.message_post(
            body=Markup(
                _(
                    "Event <a href=# data-oe-model=fr.einvoicing.event "
                    "data-oe-id=%(event_id)s>%(event)s</a> created."
                )
                % {"event": event.display_name, "event_id": event.id}
            )
        )
        if status == "refused":
            self.move_id.with_context(by_pass_refusal_event_wizard=True).button_cancel()


class FrEinvoicingEventDetailManual(models.TransientModel):
    _name = "fr.einvoicing.event.detail.manual"
    _description = "Detail of an eInvoicing Event created manually"

    event_id = fields.Many2one(
        "fr.einvoicing.event.manual",
        string="Event",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    reason_dispute = fields.Selection(
        "_reason_dispute_selection", string="Dispute Reason"
    )
    reason_partially_approved = fields.Selection(
        "_reason_partially_approved_selection", string="Partially Approved Reason"
    )
    reason_suspended = fields.Selection("_reason_suspended", string="Suspended Reason")
    reason_refused = fields.Selection("_reason_refused", string="Refused Reason")
    action = fields.Selection("_action_selection")
    comment = fields.Text(required=True)

    @api.model
    def _reason_dispute_selection(self):
        return self._reason_selection("dispute")

    @api.model
    def _reason_partially_approved_selection(self):
        return self._reason_selection("partially_approved")

    @api.model
    def _reason_suspended(self):
        return self._reason_selection("suspended")

    @api.model
    def _reason_refused(self):
        return self._reason_selection("refused")

    @api.model
    def _reason_selection(self, status):
        all_res = self.env["fr.einvoicing.event.detail"]._get_all_reasons()
        res = [
            (key, values["label"])
            for key, values in all_res.items()
            if status in values.get("manual_status", [])
        ]
        return res

    @api.model
    def _action_selection(self):
        return self.env["fr.einvoicing.event.detail"]._action_selection()
