# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class FrEinvoicingSend(models.TransientModel):
    _name = "fr.einvoicing.send"
    _description = "Send several invoices to accredited platform"
    _check_company_auto = True

    invoice_ids = fields.Many2many(
        "account.move",
        string="Invoices to Send",
        readonly=True,
        check_company=True,
    )
    invoice_count = fields.Integer(string="Number of Invoices", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    send_method = fields.Selection([
        ('queued', 'Queued'),
        ('immediate', 'Immediate'),
        ], default='queued')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        assert self._context.get("active_model") == "account.move"
        assert self._context.get("active_ids"), "Missing active_ids in ctx"
        invoices = self.env["account.move"].browse(self._context.get("active_ids"))
        state2label = dict(self.env['account.move']._fields['state']._description_selection(self.env))
        company = False
        for invoice in invoices:
            if invoice.move_type not in ("out_invoice", "out_refund"):
                raise UserError(
                    self.env._(
                        "Move '%s' is not a customer invoice/refund. You can only send "
                        "customer invoices/refunds to the accredited platform.", invoice.display_name
                    )
                )
            if invoice.state != "posted":
                raise UserError(
                    self.env._(
                        "The state of invoice/refund '%(invoice)s' is "
                        "'%(invoice_state)s'. You can only send invoices/refunds "
                        "in posted state.",
                        invoice=invoice.display_name,
                        invoice_state=state2label.get(invoice.state),
                    )
                )
            if invoice.commercial_partner_id.fr_directory_entity_type not in ('private', 'public'):
                raise UserError(self.env._(
                    "On invoice/refund '%(invoice)s', customer '%(partner)s' "
                    "is not in the directory, so we can't send it to the accredited platform.",
                    invoice=invoice.display_name,
                    partner=invoice.commercial_partner_id.display_name
                    ))
            if invoice.fr_einvoicing_flow_id:
                raise UserError(
                    self.env._(
                        "Invoice '%(invoice)s' has already been sent: "
                        "it is linked to flow %(flow)s.",
                        invoice=invoice.display_name,
                        flow=invoice.fr_einvoicing_flow_id,
                    )
                )
            if company:
                if company != invoice.company_id:
                    raise UserError(
                        _("All the selected invoices must be in the same company.")
                    )
            else:
                company = invoice.company_id

        res.update(
            {
                "invoice_ids": [Command.set(invoices.ids)],
                "invoice_count": len(invoices),
                "company_id": company.id,
            }
        )
        return res

    def run(self):
        self.ensure_one()
        send_now = self.send_method == "immediate"
        for invoice in self.invoice_ids:
            invoice._fr_ctc_send_invoice(send_now=send_now)
        action = {}
        return action
