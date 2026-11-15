# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    if not openupgrade.table_exists(env.cr, "fr_einvoicing_flow"):
        return
    # On a multi-version upgrade (16.0 -> 18.0, or even 18.0.1.1.0 -> 18.0.1.3.0),
    # the pre-migration script of 18.0.1.3.0 has already renamed the column to its
    # final name 'invoice_format' before this post-migration script is played.
    # Only flows without any invoice format are updated: the 16.0 version of
    # this module may already be up-to-date (backport) and have set it.
    if openupgrade.column_exists(env.cr, "fr_einvoicing_flow", "invoice_format"):
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE fr_einvoicing_flow
            SET invoice_format='facturx'
            WHERE syntax='Factur-X' AND invoice_format IS NULL
            """,
        )
    elif openupgrade.column_exists(env.cr, "fr_einvoicing_flow", "odoo_invoice_format"):
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE fr_einvoicing_flow
            SET odoo_invoice_format='facturx'
            WHERE syntax='Factur-X' AND odoo_invoice_format IS NULL
            """,
        )
