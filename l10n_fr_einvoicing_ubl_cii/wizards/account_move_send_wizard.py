# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountMoveSendWizard(models.TransientModel):
    _inherit = "account.move.send.wizard"

    # -------------------------------------------------------------------------
    # DEFAULTS
    # -------------------------------------------------------------------------
    def _get_fr_pa_checkbox_disable_reason(self):
        self.ensure_one()
        move = self.move_id.with_company(self.move_id.company_id)
        if not move.fr_directory_partner_entity_type:
            return self.env._(" (Customer not present in directory)")
        elif not move.fr_directory_line_id:
            return self.env._(" (No directory line selected for customer)")
        else:
            return ""

    def _compute_sending_method_checkboxes(self):
        res = super()._compute_sending_method_checkboxes()
        for wizard in self:
            if fr_pa_checkbox := wizard.sending_method_checkboxes.get("fr_pa"):
                disable_reason = wizard._get_fr_pa_checkbox_disable_reason()
                vals_display = (
                    {"readonly": True, "checked": False}
                    if disable_reason
                    else {"readonly": True, "checked": True}
                )
                if disable_reason:
                    wizard.sending_method_checkboxes = {
                        **wizard.sending_method_checkboxes,
                        "fr_pa": {
                            **fr_pa_checkbox,
                            **vals_display,
                            "label": self.env._(
                                f"French Accredited Platform{disable_reason}",
                            ),
                        },
                    }
        return res
