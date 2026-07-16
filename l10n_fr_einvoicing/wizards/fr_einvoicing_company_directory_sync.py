# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.exceptions import UserError


class FrEinvoicingCompanyDirectorySync(models.TransientModel):
    _name = "fr.einvoicing.company.directory.sync"
    _description = "FR eInvoicing Company Directory Sync"

    company_id = fields.Many2one("res.company", required=True)
    company_partner_id = fields.Many2one(
        related="company_id.partner_id", string="Company Partner"
    )
    company_fr_directory_entity_type = fields.Selection(
        related="company_id.partner_id.fr_directory_entity_type",
        string="Company Directory Status",
    )
    company_default_fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        string="Company Default Directory Line",
        domain="[('partner_id', '=', company_partner_id), ('state', '=', 'active')]",
    )
    error = fields.Html(readonly=True)
    state = fields.Selection(
        [
            ("dir_sync", "Directory Sync"),
            ("select_default_dir_line", "Select Default Directory Line"),
            ("error", "Error"),
        ],
        default="dir_sync",
    )

    def dir_sync_button(self):
        self.ensure_one()
        company = self.company_id
        partner = company.partner_id
        if partner.fr_directory_entity_type in ("private", "public", "no"):
            raise UserError(
                self.env._(
                    "The directory status of '%s' is already ok.", partner.display_name
                )
            )
        partner._fr_directory_sync_logs(
            company, self.env._("Company directory sync wizard")
        )
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_fr_einvoicing.fr_einvoicing_company_directory_sync_action"
        )
        action["res_id"] = self.id
        if partner.fr_directory_entity_type == "private":
            if partner.fr_directory_line_active_count > 1:
                self.write({"state": "select_default_dir_line"})
            elif partner.fr_directory_line_active_count == 1:
                company._fr_ctc_compute_invoice_company_dir_line()
                action = {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "type": "success",
                        "title": self.env._("Directory Successfully Synced"),
                        "message": self.env._(
                            "Company %s has 1 directory line.", company.display_name
                        ),
                        "next": {"type": "ir.actions.act_window_close"},
                    },
                }
            else:
                self.write(
                    {
                        "state": "error",
                        "error": self.env._(
                            "The directory status of %s is <strong>Private VAT "
                            "Registered</strong> but Odoo didn't get any active "
                            "directory line. This should not happen.",
                            partner.display_name,
                        ),
                    }
                )
        elif partner.fr_directory_entity_type == "private_inactive":
            self.write(
                {
                    "state": "error",
                    "error": self.env._(
                        "The company %s is not active in the directory yet. "
                        "If you successfully performed the onboarding, you should "
                        "try again tomorrow.",
                        partner.display_name,
                    ),
                }
            )
        elif partner.fr_directory_entity_type == "no":
            self.write(
                {
                    "state": "error",
                    "error": self.env._(
                        "The company %s is not a private VAT registrered entity "
                        "according to the directory.",
                        partner.display_name,
                    ),
                }
            )
        elif partner.fr_directory_entity_type == "public":
            self.write(
                {
                    "state": "error",
                    "error": self.env._(
                        "The company %s is a public entity. This scenario is "
                        "not supported.",
                        partner.display_name,
                    ),
                }
            )
        else:
            raise ValueError("Wrong value for fr_directory_entity_type")
        return action

    def select_default_dir_line_button(self):
        self.ensure_one()
        default_dir_line = self.company_default_fr_directory_line_id
        if not default_dir_line:
            raise UserError(
                self.env._("You must select a default directory line for the company.")
            )
        self.company_partner_id.write(
            {"default_fr_directory_line_id": default_dir_line.id}
        )
        self.company_id._fr_ctc_compute_invoice_company_dir_line()
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Directory Successfully Synced"),
                "message": self.env._(
                    "The directory lines of company %s are correctly synced "
                    "and configured.",
                    self.company_id.display_name,
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
        return action
