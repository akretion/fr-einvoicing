# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing Sale",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "license": "AGPL-3",
    "summary": "eInvoicing for France in Sales",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        "sale_commercial_partner",
    ],
    "data": [
        "data/ir_actions_server.xml",
        "views/sale_order.xml",
        "wizards/res_config_settings_view.xml",
    ],
    "installable": True,
    "auto_install": True,
}
