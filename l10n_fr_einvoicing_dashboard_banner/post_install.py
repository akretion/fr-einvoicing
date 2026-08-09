# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


# 16.0: post_init_hook receives (cr, registry), not (env) as of 17.0+.
from odoo import SUPERUSER_ID, api


def create_fr_einvoicing_dashboard_cells(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    vals_list = [
        {"cell_type": "fr_einvoicing_flows_error", "sequence": 15, "warn": True},
        {"cell_type": "fr_einvoicing_flows_in_progress", "sequence": 16},
    ]
    env["account.dashboard.banner.cell"].create(vals_list)
