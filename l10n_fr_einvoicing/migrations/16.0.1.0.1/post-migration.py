# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    crons = env["ir.cron"]
    xmlids = [
        "fr_directory_update_cron",
        "fr_einvoicing_flow_out_cron",
        "fr_einvoicing_flow_in_cron",
    ]
    for xmlid in xmlids:
        cron = env.ref(f"l10n_fr_einvoicing.{xmlid}", raise_if_not_found=False)
        if cron:
            crons |= cron
    crons.write({"numbercall": -1})
