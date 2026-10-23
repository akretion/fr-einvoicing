# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fr_ctc_ereporting_minimize = fields.Boolean(
        related="company_id.fr_ctc_ereporting_minimize", readonly=False
    )
    fr_ctc_ereporting_update_lock_dates = fields.Boolean(
        related="company_id.fr_ctc_ereporting_update_lock_dates", readonly=False
    )
    fr_ctc_ereporting_auto = fields.Boolean(
        related="company_id.fr_ctc_ereporting_auto", readonly=False
    )
    fr_ctc_ereporting_deadline_days = fields.Selection(
        related="company_id.fr_ctc_ereporting_deadline_days", readonly=False
    )
