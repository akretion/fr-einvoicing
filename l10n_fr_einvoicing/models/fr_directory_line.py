# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class FrDirectoryLine(models.Model):
    _name = 'fr.directory.line'
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
    active = fields.Boolean(compute="_compute_active", store=True)
    identifier = fields.Char(required=True, readonly=True)
    type = fields.Selection([
        ('siren', 'SIREN'),
        ('siret', 'SIRET'),
        ('routing_code', 'Routing Code'),
        ('suffix', 'Suffix'),
        ('error', 'Malformed'),
        ], readonly=True, required=True)
    siren = fields.Char(readonly=True, string="SIREN")
    siret = fields.Char(readonly=True, string="SIRET")
    suffix = fields.Char(readonly=True, string="Suffix")
    routing_code = fields.Char(readonly=True, string="Routing Code")
    routing_code_name = fields.Char(readonly=True)
    commitment_required = fields.Boolean(readonly=True)
    state = fields.Selection([  # directoryLineStatus
        ('upcoming', 'Upcoming'),  # Upcoming
        ('active', 'Active'),   # = Enabled
        ('disabled', 'Disabled'),  # Disabled
        ('inactive', 'Inactive'),  # key directoryLineStatus not present
        ], readonly=True, index=True)

    _sql_constraints = [
        (
            "partner_identifier_uniq",
            "unique(partner_id, identifier)",
            "This identifier already exists for this partner!",
        )
    ]

    @api.depends('state')
    def _compute_active(self):
        for line in self:
            line.active = line.state != "disabled"

    @api.depends('identifier', 'routing_code_name', 'state')
    def _compute_display_name(self):
        state2label = dict(self._fields['state']._description_selection(self.env))
        for line in self:
            name = line.identifier
            if line.type == "routing_code" and line.routing_code_name:
                name = f"{name} {line.routing_code_name}"
            if line.state != 'active':
                name = f"[{state2label.get(line.state)}] {name}"
            line.display_name = name
