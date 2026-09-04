# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


import logging

from markupsafe import Markup

from odoo import api, fields, models

logger = logging.getLogger(__name__)

try:
    from pyfrctc import get_ereporting_types_to_declare_today
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_ctc_ereporting_minimize = fields.Boolean(
        string="Don't Send Infos that are not Strictly Required", default=True
    )
    fr_ctc_ereporting_update_lock_dates = fields.Boolean(
        string="Update Lock Date when e-Reporting is Sent"
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
        default="2",
        string="Day when e-Reporting is auto-Generated and Transmitted",
    )

    @api.model
    def _fr_ctc_cron_ereporting_auto_generate_transmit(self):
        today = fields.Date.context_today(self)
        # from datetime import date
        # today = date(2026, 9, 8)  # only for tests
        logger.info(f"Start cron FR eReporting for date {fields.Date.to_string(today)}")
        mail_tpl = self.env.ref("l10n_fr_ereporting.fr_ereporting_mail_template")
        companies = self.sudo().search(
            [
                ("partner_id.fr_directory_entity_type", "=", "private"),
                ("fr_ctc_ereporting_auto", "=", True),
            ]
        )
        erep_obj = self.env["fr.ereporting"]
        for company in companies:
            logger.debug(
                f"Company {company.display_name} has "
                f"fr_ctc_ereporting_deadline_days="
                f"{company.fr_ctc_ereporting_deadline_days}"
            )
            try:
                days_before_deadline = int(company.fr_ctc_ereporting_deadline_days)
            except Exception:
                days_before_deadline = 0
            types2start_date = get_ereporting_types_to_declare_today(
                company.fr_vat_periodicity, days_before_deadline, today=today
            )
            logger.debug(f"types2start_date={types2start_date} with today=")
            if types2start_date:
                logger.info(f"Processing e-Reporting in company {company.display_name}")
            else:
                logger.info(
                    f"Nothing to do in company {company.display_name} that has "
                    f"VAT periodicity {company.fr_vat_periodicity} and days "
                    f"before deadline={days_before_deadline}"
                )

            mail_coreinfo = {}
            # key = reporting display_name
            # value = {
            #     'created': True/False,
            #     'gen_sent': True/False,
            #     'gen_sent_error': 'Error msg (only wehn gen_sent=False)',
            # }
            # We don't want already sent e-reporting in mail_coreinfo,
            # otherwise we would have a mail notif for each day between
            # (deadline - fr_ctc_ereporting_deadline_days) and the deadline
            for rep_type, start_date in types2start_date.items():
                ereporting = erep_obj.sudo().search(
                    [
                        ("company_id", "=", company.id),
                        ("type", "=", rep_type),
                        ("start_date", "=", start_date),
                    ]
                )
                if ereporting:
                    created = False
                    if ereporting.state == "draft":
                        logger.info(
                            f"e-Reporting {ereporting.display_name} has already "
                            "been created and is currently in draft"
                        )
                    else:
                        logger.info(
                            f"e-Reporting {ereporting.display_name} has already "
                            "been created and sent"
                        )
                else:
                    created = True
                    ereporting = erep_obj.sudo().create(
                        {
                            "company_id": company.id,
                            "type": rep_type,
                            "start_date": start_date,
                        }
                    )
                    ereporting.message_post(
                        body=self.env._(
                            "Created automatically by the scheduled action."
                        )
                    )

                if ereporting.state == "draft":
                    logger.info(
                        f"Generating content of e-Reporting {ereporting.display_name}"
                    )
                    try:
                        ereporting.sudo().generate_button()
                        logger.info(f"Sending e-Reporting {ereporting.display_name}")
                        ereporting.sudo().send_button()
                        ereporting.message_post(
                            body=Markup(
                                self.env._("e-Reporting sent by the scheduled action.")
                            )
                        )
                        mail_coreinfo[ereporting.display_name] = {
                            "created": created,
                            "gen_sent": True,
                        }
                    except Exception as err:
                        logger.error(err)
                        # for logs, we need to have the name of the e-reporting
                        # for message_post(), we don't want to e-reporting name
                        # => maybe we could put the logs in the table per
                        msg = self.env._(
                            "Generation and sending of the e-Reporting "
                            "<strong>failed</strong>. Error: <strong>%s</strong>",
                            err,
                        )
                        ereporting.message_post(body=Markup(msg))
                        mail_coreinfo[ereporting.display_name] = {
                            "created": created,
                            "gen_sent": False,
                            "gen_sent_error": err,
                        }
                        continue
            if company.fr_vat_remind_user_ids and mail_coreinfo:
                logger.info(
                    f"Generating eReporting notif email "
                    f"for company {company.display_name}"
                )
                mail_tpl.with_context(mail_coreinfo=mail_coreinfo).send_mail(company.id)

        logger.info("End cron FR eReporting")
