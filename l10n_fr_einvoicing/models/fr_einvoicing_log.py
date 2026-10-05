# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import api, fields, models

logger = logging.getLogger(__name__)
DEFAULT_LOG_VACUUM_DAYS = 600


class FrEinvoicingLog(models.Model):
    _name = "fr.einvoicing.log"
    _description = "Logs for France eInvoicing"
    _order = "id desc"
    _rec_name = "create_date"

    company_id = fields.Many2one("res.company", ondelete="cascade", readonly=True)
    type = fields.Selection(
        [
            ("directory_all", "Directory sync on all partners"),
            ("directory_single", "Directory sync on single partner"),
            ("flow_import_all", "Flow import for all companies"),
            ("flow_import_single", "Flow import for one company"),
            ("flow_download", "Flow download"),
            ("flow_process", "Flow processing"),
            ("flow_send_all", "Send flows for all companies"),
            ("flow_generate", "Flow file generation"),
            ("flow_send", "Send flow"),
            ("flow_generate_and_send", "Generate and send flow"),
            ("flow_update_status", "Flow status update"),
        ],
        required=True,
        readonly=True,
    )
    origin = fields.Char(readonly=True)
    logs = fields.Html(readonly=True)
    status = fields.Selection(
        [
            ("success", "Success"),
            ("success_warn", "Success with Warnings"),
            ("failure", "Failure"),
        ],
        readonly=True,
        required=True,
    )
    new_count = fields.Integer(string="Number of New Objects", readonly=True)
    updated_count = fields.Integer(string="Number of Objects Updated", readonly=True)

    @api.autovacuum
    def _gc_old_logs(self):
        """Method automatically called by the autovacuum internal data cron"""
        config_key = "fr_einvoicing.log_days"
        days_str = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(config_key, default=str(DEFAULT_LOG_VACUUM_DAYS))
        )
        try:
            days = int(days_str)
        except Exception:
            days = DEFAULT_LOG_VACUUM_DAYS
            logger.warning(
                f"Failed to convert ir.config_parameter {config_key} ({days_str}) "
                f"to integer. Using default value {days} days"
            )
        limit_date = fields.Datetime.now() - timedelta(days)
        logger.info(f"Autovacuum of FR eInvoicing logs older than {days} days")
        self.search([("create_date", "<", limit_date)]).unlink()

    @api.model
    def _prepare_log(self, result):
        logs = []
        error_count = 0
        warning_count = 0
        for log_type, msg in result["logs"]:
            if log_type == "info":
                logs.append(
                    f'<span style="color: green; font-weight: bold">'
                    f"INFO </span>{msg}"
                )
            elif log_type == "warning":
                logs.append(
                    f'<span style="color: orange; font-weight: bold">'
                    f"WARNING </span>{msg}"
                )
                warning_count += 1
            elif log_type == "error":
                logs.append(
                    f'<span style="color: red; font-weight: bold">'
                    f"ERROR </span>{msg}"
                )
                error_count += 1
            else:  # Should not happen
                logs.append(msg)
        if error_count:
            status = "failure"
        else:
            if warning_count:
                status = "success_warn"
            else:
                status = "success"
        result.update(
            {
                "error_count": error_count,
                "warning_count": warning_count,
            }
        )
        log_vals = {
            "company_id": result.get("company_id"),
            "type": result["log_type"],
            "origin": result.get("log_origin"),
            "status": status,
            "new_count": result.get("new_count"),
            "updated_count": result.get("updated_count"),
            "logs": "<br>".join(logs),
        }
        return log_vals

    def _create_log(self, result):
        log = self.sudo().create(self._prepare_log(result))
        logger.debug("FR einvoicing log ID %d created", log.id)

    @api.model
    def _info_log(self, result, msg):
        logger.info(msg)
        result["logs"].append(("info", msg))

    @api.model
    def _warning_log(self, result, msg):
        logger.warning(msg)
        result["logs"].append(("warning", msg))

    @api.model
    def _error_log(self, result, msg):
        logger.error(msg)
        result["logs"].append(("error", msg))
