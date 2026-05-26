# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fr_ctc_accredited_platform = fields.Selection(related="company_id.fr_ctc_accredited_platform", readonly=False, )
    fr_ctc_auth_method = fields.Selection(related='company_id.fr_ctc_auth_method', readonly=False, string="Auth Method")
    fr_ctc_client_id = fields.Char(related="company_id.fr_ctc_client_id", readonly=False, string="Client ID")
    fr_ctc_client_secret = fields.Char(related="company_id.fr_ctc_client_secret", readonly=False, string="Client Secret")
    fr_ctc_last_flow_import_datetime = fields.Datetime(
        related="company_id.fr_ctc_last_flow_import_datetime", readonly=False)
    fr_ctc_event_auto_send_in_hand = fields.Boolean(related="company_id.fr_ctc_event_auto_send_in_hand", readonly=False)
    fr_ctc_event_auto_send_approved = fields.Boolean(related="company_id.fr_ctc_event_auto_send_approved", readonly=False)
    fr_ctc_activity_warning_event_user_ids = fields.Many2many(related="company_id.fr_ctc_activity_warning_event_user_ids", readonly=False)
    fr_ctc_activity_warning_event_invoice_creator = fields.Boolean(related="company_id.fr_ctc_activity_warning_event_invoice_creator", readonly=False)
    fr_ctc_activity_warning_event_salesman = fields.Boolean(related="company_id.fr_ctc_activity_warning_event_salesman", readonly=False)

    def fr_ctc_test_api_button(self):
        self.ensure_one()
        return self.company_id._fr_ctc_test_api()

    def fr_ctc_authorization_code_onboarding(self):
        self.ensure_one()
        return self.company_id._fr_ctc_authorization_code_redirect()
