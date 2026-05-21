# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from markupsafe import Markup


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def generated2uploaded(self):
        res = super().generated2uploaded()
        if self.payment_type == "outbound" and self.company_id.fr_ctc_event_auto_send_payment_sent:
            invoices = self.env['account.move']
            for payment in self.payment_ids:
                for inv in payment.invoice_ids:
                    if inv.move_type in ('in_invoice', 'out_refund') and inv.fr_einvoicing_flow_id:
                        vals = {
                            'status': 'payment_sent',
                            'company_id': inv.company_id.id,
                            'move_id': inv.id,
                            'direction': 'out',
                            'payment_ids': [Command.create({
                                'amount': payment.amount,
                                'currency_id': payment.currency_id.id,
                                "date": payment.date,
                                })],
                            }

                        event = self.env['fr.einvoicing.event'].sudo().create(vals)
                        inv.message_post(body=Markup(self.env._("Event <a href=# data-oe-model=fr.einvoicing.event data-oe-id=%s>Payment Sent</a> created automatically by Odoo", event.id)))
                        invoices |= inv
            payment_ids = self.payment_ids.ids
#            for inv in invoices:
#                pay_infos = (
#                isinstance(inv.invoice_payments_widget, dict)
#                and inv.invoice_payments_widget["content"]
#                or []
#                )
#                for pay_info in pay_infos:
#                    print('pay_info=', pay_info)
#                    if pay_info['account_payment_id'] and pay_info['account_payment_id'] in payment_ids:
#                        amount = pay_info['amount']
#                        currency_id = pay_info['currency_id']
#                        if amount > 0 and currency_id:
#                            currency = self.env['res.currency'].browse(currency_id)
#                            inv._fr_ctc_create_event('payment_sent', amount=amount, currency=currency)
#                            move.message_post(body=Markup(self.env._("Event <strong>Approved</strong> created automatically by Odoo")))
        return res
