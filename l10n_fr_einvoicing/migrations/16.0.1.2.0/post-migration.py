# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    if openupgrade.table_exists(env.cr, "fr_einvoicing_flow"):
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE fr_einvoicing_flow
            SET odoo_invoice_format='facturx'
            WHERE syntax='Factur-X'
            """,
        )
