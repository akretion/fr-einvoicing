# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Invoice EN16931",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Base module to generate electronic invoices",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account_tax_unece",
        "uom_unece",
        "account_payment_unece",
        "base_vat",
        "intrastat_base",
    ],
    "excludes": ["account_einvoice_generate"],
    "external_dependencies": {"python": ["factur-x>=6.7", "packaging"]},
    "data": [
        "security/ir.model.access.csv",
        "wizards/account_invoice_en16931_generate_view.xml",
        "views/account_move.xml",
        "views/res_partner.xml",
        "wizards/res_config_settings_view.xml",
    ],
    "installable": True,
}
