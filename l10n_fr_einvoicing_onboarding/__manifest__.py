# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing onboarding for V16.0",
    "version": "16.0.1.0.1",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Module for France einvoincing onboarding.",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account",
        "l10n_fr_siret",
    ],
    "external_dependencies": {"python": ["pyfrctc>=0.12"]},
    "data": [
        "wizards/res_config_settings.xml",
    ],
    "demo": [],
    "installable": True,
}
