# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


import logging

from odoo import api, fields, models

logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_ctc_ereporting_minimize = fields.Boolean(
        string="Don't Send Infos that are not Strictly Required", default=True
    )
    fr_ctc_ereporting_update_lock_dates = fields.Boolean(
        string="Update Lock Date when e-Reporting is Confirmed and Sent"
    )
    fr_ctc_ereporting_auto = fields.Boolean(
        default=True, string="Auto Generate and Transmit e-Reporting"
    )
    fr_ctc_ereporting_deadline_days = fields.Selection(
        [
            ("0", "On Deadline Day"),
            ("1", "1 day before Deadline"),
            ("2", "2 days before Deadline"),
            ("3", "3 days before Deadline"),
            ("4", "4 days before Deadline"),
        ],
        default="1",
        string="Day when e-Reporting is auto-Generated and Transmitted",
    )

    @api.model
    def _fr_ctc_cron_ereporting_auto_generate_transmit(self):
        logger.info("Start cron FR eReporting")
        companies = self.sudo().search(
            [
                ("partner_id.fr_directory_entity_type", "=", "private"),
                ("fr_ctc_ereporting_auto", "=", True),
            ]
        )
        for company in companies:
            logger.debug(
                f"Company {company.display_name} has "
                f"fr_ctc_ereporting_deadline_days="
                f"{company.fr_ctc_ereporting_deadline_days}"
            )
            # TODO to be continued
        logger.info("End cron FR eReporting")
