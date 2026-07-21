# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing onboarding",
    "version": "18.0.1.0.1",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Module for France einvoincing onboardingi without all modules.",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account",
        "l10n_fr_siret",
    ],
    "external_dependencies": {"python": ["pyfrctc>=0.14"]},
    "data": [
        "wizards/res_config_settings.xml",
    ],
    "demo": [],
    "installable": True,
}
