# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fr_ctc_directory_sync_on_sale_order_confirm = fields.Selection(
        related="company_id.fr_ctc_directory_sync_on_sale_order_confirm", readonly=False
    )
    fr_ctc_directory_sync_on_sale_order_confirm_days = fields.Integer(
        related="company_id.fr_ctc_directory_sync_on_sale_order_confirm_days",
        readonly=False,
    )
