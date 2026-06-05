# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo import Command, models


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def generated2uploaded(self):
        res = super().generated2uploaded()
        if (
            self.payment_type == "outbound"
            and self.company_id.fr_ctc_event_auto_send_payment_sent
        ):
            for payment in self.payment_ids:
                for inv in payment.invoice_ids:
                    if (
                        inv.move_type in ("in_invoice", "out_refund")
                        and inv.fr_einvoicing_flow_id
                    ):
                        vals = {
                            "status": "payment_sent",
                            "company_id": inv.company_id.id,
                            "move_id": inv.id,
                            "direction": "out",
                            "payment_ids": [
                                Command.create(
                                    {
                                        "amount": payment.amount,
                                        "currency_id": payment.currency_id.id,
                                        "date": payment.date,
                                    }
                                )
                            ],
                        }

                        event = self.env["fr.einvoicing.event"].sudo().create(vals)
                        inv.message_post(
                            body=Markup(
                                self.env._(
                                    "Event <a href=# data-oe-model=fr.einvoicing.event "
                                    "data-oe-id=%s>Payment Sent</a> "
                                    "created automatically by Odoo",
                                    event.id,
                                )
                            )
                        )
        # For the moment, we implement a "simple" solution where the amount
        # in the event is the amount of the payment, even if this payment
        # is for multiple invoices. Maybe we'll have to change it one day to write
        # in the event the amount of the payment affected to the invoice of
        # the event
        return res
