# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import _, fields, models
from odoo.tools.misc import formatLang


class AccountDashboardBannerCell(models.Model):
    _inherit = "account.dashboard.banner.cell"

    cell_type = fields.Selection(
        selection_add=(
            [
                ("fr_einvoicing_flows_error", "eInv. Flows in Error"),
                ("fr_einvoicing_flows_in_progress", "eInv. Flows in Progress"),
            ]
        ),
        ondelete={
            "fr_einvoicing_flows_error": "cascade",
            "fr_einvoicing_flows_in_progress": "cascade",
        },
    )

    def _prepare_cell_data(self, company, speedy):
        self.ensure_one()
        cell_type = self.cell_type
        if cell_type.startswith("fr_einvoicing_flows_"):
            warn = tooltip = False
            action = self.env["ir.actions.actions"]._for_xml_id(
                "l10n_fr_einvoicing.fr_einvoicing_flow_action"
            )
            domain = [("company_id", "=", company.id)]
            if cell_type == "fr_einvoicing_flows_error":
                domain.append(("state", "=", "error"))
                tooltip = _("Number of eInvoicing flows in 'Error' state.")
            elif cell_type == "fr_einvoicing_flows_in_progress":
                domain.append(("state", "not in", ("error", "done")))
                tooltip = _(
                    "Number of eInvoicing flows in state other than 'Error' or 'Done'."
                )
            action["domain"] = domain
            count = self.env["fr.einvoicing.flow"].search_count(domain)
            if cell_type == "fr_einvoicing_flows_error" and count > 0 and self.warn:
                warn = True
            res = {
                "cell_type": cell_type,
                "label": self.custom_label or speedy["cell_type2label"][cell_type],
                "raw_value": count,
                "value": formatLang(self.env, count, digits=0),
                "tooltip": self.custom_tooltip or tooltip,
                "warn": warn,
                "action": action,
            }
        else:
            res = super()._prepare_cell_data(company, speedy)
        return res

    def _compute_warn_fields(self):
        res = super()._compute_warn_fields()
        self.filtered(
            lambda x: x.cell_type == "fr_einvoicing_flows_error"
        ).warn_type_show = False
        return res
