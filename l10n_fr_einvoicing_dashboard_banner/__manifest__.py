# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing Dashboard Banner",
    "version": "16.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Add widgets for eInvoicing flows in Accounting Dashboard Banner",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account_dashboard_banner",
        "l10n_fr_einvoicing",
    ],
    "post_init_hook": "create_fr_einvoicing_dashboard_cells",
    "installable": False,
}
