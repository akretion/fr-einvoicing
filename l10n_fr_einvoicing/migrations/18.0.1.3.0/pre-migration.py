# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_column_renames = {
    "fr_einvoicing_flow": [("odoo_invoice_format", "invoice_format")],
}


@openupgrade.migrate()
def migrate(env, version):
    # odoo_invoice_format only exists if the module was already in version
    # 18.0.1.2.0 or later: on a 16.0 -> 18.0 upgrade, the column may be
    # present already
    if not openupgrade.table_exists(env.cr, "fr_einvoicing_flow"):
        return
    if not openupgrade.column_exists(
        env.cr, "fr_einvoicing_flow", "odoo_invoice_format"
    ):
        return
    if openupgrade.column_exists(env.cr, "fr_einvoicing_flow", "invoice_format"):
        return
    openupgrade.rename_columns(env.cr, _column_renames)
