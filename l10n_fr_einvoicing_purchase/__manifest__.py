# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing Purchase",
    "version": "16.0.1.0.0",
    "category": "Inventory/Purchase",
    "license": "AGPL-3",
    "summary": "Display directory line on purchase order report",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        "purchase",
    ],
    "data": [
        "views/purchase_order.xml",
        "reports/purchase_order_template.xml",
    ],
    "installable": True,
}
