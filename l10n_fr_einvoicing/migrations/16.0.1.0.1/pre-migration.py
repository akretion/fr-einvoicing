# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    if not openupgrade.column_exists(env.cr, "res_partner", "fr_directory_update_date"):
        openupgrade.rename_fields(
            env,
            [
                (
                    "res.partner",
                    "res_partner",
                    "fr_directory_update_date",
                    "fr_directory_last_sync_date",
                ),
            ],
        )
