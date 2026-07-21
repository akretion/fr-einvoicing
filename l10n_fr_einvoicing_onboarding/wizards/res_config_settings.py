# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fr_ctc_accredited_platform = fields.Selection(
        related="company_id.fr_ctc_accredited_platform",
        readonly=False,
    )

    def fr_ctc_authorization_code_onboarding(self):
        self.ensure_one()
        return self.company_id._fr_ctc_authorization_code_redirect()
