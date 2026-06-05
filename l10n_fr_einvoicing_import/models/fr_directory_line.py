# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class FrDirectoryLine(models.Model):
    _inherit = 'fr.directory.line'

    purchase_journal_id = fields.Many2one('account.journal', string='Purchase Journal', copy=False, readonly=True)
