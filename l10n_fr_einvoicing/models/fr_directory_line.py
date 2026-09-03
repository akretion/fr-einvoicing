# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import api, fields, models

logger = logging.getLogger(__name__)

try:
    from pyfrctc import check_directory_line_peppol_status
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)


class FrDirectoryLine(models.Model):
    _name = "fr.directory.line"
    _description = "eInvoicing Directory Line for France"
    _order = "partner_id, identifier"
    _rec_names_search = ["identifier", "routing_code_name"]

    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        ondelete="cascade",
        domain=[("parent_id", "=", False)],
        readonly=True,
        index=True,
    )
    partner_entity_type = fields.Selection(
        related="partner_id.fr_directory_entity_type", store=True
    )
    company_id = fields.Many2one(
        related="partner_id.company_id",
        store=True,
        help="The directory line has the same company as the partner.",
    )
    active = fields.Boolean(compute="_compute_active", store=True)
    identifier = fields.Char(required=True, readonly=True)
    type = fields.Selection(
        [
            ("siren", "SIREN"),
            ("siret", "SIRET"),
            ("routing_code", "Routing Code"),
            ("suffix", "Suffix"),
            ("error", "Malformed"),
        ],
        readonly=True,
        required=True,
    )
    siren = fields.Char(readonly=True, string="SIREN")
    siret = fields.Char(readonly=True, string="SIRET")
    suffix = fields.Char(readonly=True)
    routing_code = fields.Char(readonly=True)
    routing_code_name = fields.Char(readonly=True)
    commitment_required = fields.Boolean(readonly=True)
    state = fields.Selection(
        [  # directoryLineStatus
            ("upcoming", "Upcoming"),  # Upcoming
            ("active", "Active"),  # = Enabled
            ("disabled", "Disabled"),  # Disabled
            ("inactive", "Inactive"),  # key directoryLineStatus not present
        ],
        readonly=True,
        index=True,
    )
    peppol_status = fields.Selection(
        "_peppol_status_selection",
        readonly=True,
        string="PEPPOL Status",
    )
    peppol_status_date = fields.Date(
        readonly=True, string="Last Update of PEPPOL Status"
    )
    peppol_accredited_platform = fields.Char(
        readonly=True, string="Accredited Platform"
    )

    _sql_constraints = [
        (
            "partner_identifier_uniq",
            "unique(partner_id, identifier)",
            "This identifier already exists for this partner!",
        )
    ]

    @api.model
    def _peppol_status_selection(self):
        return [
            ("ok", self.env._("OK")),
            ("not_present", self.env._("Not in PEPPOL")),
            ("query_failed", self.env._("DNS Query Failed")),
        ]

    @api.depends("state")
    def _compute_active(self):
        for line in self:
            line.active = line.state != "disabled"

    @api.depends("identifier", "routing_code_name", "state", "peppol_status")
    def _compute_display_name(self):
        state2label = dict(self._fields["state"]._description_selection(self.env))
        for line in self:
            name = line.identifier
            if line.type == "routing_code" and line.routing_code_name:
                name = f"{name} {line.routing_code_name}"
            if line.state != "active":
                name = f"[{state2label.get(line.state)}] {name}"
            if (
                line.partner_entity_type == "private"
                and line.peppol_status == "not_present"
            ):
                name = f"❌ {name}"
            line.display_name = name

    def _confirm_common_checks(self, commitment_ref, origin):
        """This methods returns an error message as string when there is a problem.
        It returns None when everything is OK.
        It is used both at sale.order confirmation and invoice confirmation
        """
        self.ensure_one()
        if self.state != "active":
            return self.env._(
                "On '%(origin)s', the selected directory line '%(dir_line)s' "
                "is not active.",
                origin=origin,
                dir_line=self.display_name,
            )
        if self.commitment_required and not commitment_ref:
            return self.env._(
                "On '%(origin)s', the selected directory line '%(dir_line)s' "
                "requires a commitment reference but the 'Customer Reference' "
                "is not set.",
                origin=origin,
                dir_line=self.display_name,
            )
        return None

    def peppol_status_update(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.partner_entity_type != "private":
                if line.peppol_status:
                    line.sudo().write(
                        {
                            "peppol_status": False,
                            "peppol_status_date": False,
                            "peppol_accredited_platform": False,
                        }
                    )
                    logger.info(
                        f"Partner {line.partner_id.display_name} is not a private "
                        "entity, so PEPPOL status has been set to False"
                    )
                else:
                    logger.info(
                        f"Partner {line.partner_id.display_name} is not a private "
                        "entity, so PEPPOL status is left empty"
                    )
                continue
            logger.info(f"Updating PEPPOL status on directory line {line.identifier}")
            assert line.identifier
            try:
                res = check_directory_line_peppol_status(line.identifier)
                peppol_status = res and "ok" or "not_present"
                peppol_accredited_platform = res
            except Exception:
                peppol_status = "query_failed"
                peppol_accredited_platform = None
            vals = {
                "peppol_status": peppol_status,
                "peppol_status_date": today,
                "peppol_accredited_platform": peppol_accredited_platform,
            }
            line.sudo().write(vals)

    def _peppol_status_update_if_ko_or_old(self, days=30):
        today = fields.Date.context_today(self)
        for line in self:
            if line.partner_entity_type == "private" and (
                not line.peppol_status_date
                or line.peppol_status_date <= today - timedelta(days)
                or line.peppol_status in ("query_failed", "not_present")
            ):
                line.peppol_status_update()
