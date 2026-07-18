# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models

from ..models.res_partner import (
    DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS,
    DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS,
)

logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fr_ctc_accredited_platform = fields.Selection(
        related="company_id.fr_ctc_accredited_platform",
        readonly=False,
    )
    fr_ctc_auth_method = fields.Selection(
        related="company_id.fr_ctc_auth_method", readonly=False, string="Auth Method"
    )
    fr_ctc_client_id = fields.Char(
        related="company_id.fr_ctc_client_id", readonly=False, string="Client ID"
    )
    fr_ctc_client_secret = fields.Char(
        related="company_id.fr_ctc_client_secret",
        readonly=False,
        string="Client Secret",
    )
    fr_ctc_last_flow_import_datetime = fields.Datetime(
        related="company_id.fr_ctc_last_flow_import_datetime", readonly=False
    )
    fr_ctc_send_invoice_format = fields.Selection(
        related="company_id.fr_ctc_send_invoice_format", readonly=False
    )
    fr_ctc_auto_reverse = fields.Boolean(
        related="company_id.fr_ctc_auto_reverse", readonly=False
    )
    fr_ctc_event_auto_send_in_hand = fields.Boolean(
        related="company_id.fr_ctc_event_auto_send_in_hand", readonly=False
    )
    fr_ctc_event_auto_send_approved = fields.Boolean(
        related="company_id.fr_ctc_event_auto_send_approved", readonly=False
    )
    fr_ctc_activity_warning_event_user_ids = fields.Many2many(
        related="company_id.fr_ctc_activity_warning_event_user_ids", readonly=False
    )
    fr_ctc_activity_warning_event_invoice_creator = fields.Boolean(
        related="company_id.fr_ctc_activity_warning_event_invoice_creator",
        readonly=False,
    )
    fr_ctc_activity_warning_event_salesman = fields.Boolean(
        related="company_id.fr_ctc_activity_warning_event_salesman", readonly=False
    )
    fr_ctc_update_partner_if_older_than_days = fields.Integer(
        string="Directory Sync of Partner if Last Sync is older than",
        config_parameter="fr_directory.update_partner_if_older_than_days",
        default=DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS,
    )
    fr_ctc_update_private_inactive_partner_if_older_than_days = fields.Integer(
        string="Directory Sync of Inactive Private Partner if Last Sync is older than",
        config_parameter="fr_directory.update_private_inactive_partner_if_older_than_days",
        default=DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS,
    )
    fr_ctc_directory_sync_on_invoice_post = fields.Selection(
        related="company_id.fr_ctc_directory_sync_on_invoice_post", readonly=False
    )
    fr_ctc_send_out_invoice = fields.Selection(
        related="company_id.fr_ctc_send_out_invoice", readonly=False
    )
    fr_ctc_get_in_invoice = fields.Boolean(
        related="company_id.fr_ctc_get_in_invoice", readonly=False
    )
    fr_ctc_show_company_dir_update_button = fields.Boolean(
        compute="_compute_fr_ctc_show_company_dir_update_button"
    )

    @api.depends("company_id")
    def _compute_fr_ctc_show_company_dir_update_button(self):
        for wiz in self:
            show = False
            if (
                wiz.company_id
                and wiz.company_id.is_france_country
                and wiz.company_id.partner_id.fr_directory_entity_type
                not in ("private", "public", "no")
            ):
                show = True
            wiz.fr_ctc_show_company_dir_update_button = show

    def fr_ctc_test_api_button(self):
        self.ensure_one()
        return self.company_id._fr_ctc_test_api()

    def fr_ctc_authorization_code_onboarding(self):
        self.ensure_one()
        return self.company_id._fr_ctc_authorization_code_redirect()

    def fr_ctc_check_en16931_button(self):
        self.ensure_one()
        self.company_id._en16931_checks()
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _(
                    "Company %s is correctly configured " "for EN16931 e-invoicing."
                )
                % self.company_id.display_name,
                "type": "success",
                "sticky": False,
            },
        }
        return action

    def fr_ctc_check_siren_siret_vat_button(self):
        domain = [
            "|",
            ("siret", "!=", False),
            ("siren", "!=", False),
            ("parent_id", "=", False),
        ]
        partners = (
            self.env["res.partner"].with_context(active_test=False).search(domain)
        )
        logger.info("Start to check SIREN/SIRET/VAT on %s partners", len(partners))
        bad_partner_ids = set()
        for partner in partners:
            updated = partner._fr_directory_check_siren_siret_vat()
            if updated:
                bad_partner_ids.add(partner.id)
        logger.info(
            "End of the check on SIREN/SIRET/VAT. %s errors found", len(bad_partner_ids)
        )
        title = self.env._("Partner's SIREN/SIRET/VAT validity")
        if bad_partner_ids:
            action = {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "warning",
                    "title": title,
                    "message": self.env._(
                        "Changes made to fix errors on %s partner(s). "
                        "See chatter of each partner for details.",
                        len(bad_partner_ids),
                    ),
                    "next": {
                        "type": "ir.actions.act_window",
                        "name": self.env._("Partners"),
                        "res_model": "res.partner",
                        "view_mode": "list,form",
                        "views": [
                            (False, "list"),
                            (False, "form"),
                        ],
                        "domain": [("id", "in", list(bad_partner_ids))],
                    },
                },
            }
        else:
            action = {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "success",
                    "title": title,
                    "message": self.env._("No errors found."),
                },
            }
        return action
