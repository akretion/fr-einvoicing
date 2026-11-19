# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Florian da Costa <florian.dacosta@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class FrDirectoryLine(models.Model):
    _inherit = "fr.directory.line"

    def _get_fr_directory_line_usages(self):
        return super()._get_fr_directory_line_usages() + [
            ("sale.order", "fr_directory_line_id")
        ]
