# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_ctc_directory_sync_on_sale_order_confirm = fields.Selection([
        ('blocking', 'Yes, always'),
        ('not_blocking', 'Yes, if directory is reachable'),
        ('no', 'No'),
        ], default="not_blocking", string="Directory Sync on Sale Order Confirmation")
    fr_ctc_directory_sync_on_sale_order_confirm_days = fields.Integer(
        string="Directory Sync on Sale Order Confirmation if Last Sync is older than",
        default=30)

    _sql_constraints = [(
        'fr_ctc_directory_sync_on_sale_order_confirm_days_positive',
        'CHECK(fr_ctc_directory_sync_on_sale_order_confirm_days >= 0)',
        'The number of days for directory sync on sale order confirmation must be positive.'
        )]
