# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "L10n FR Chorus EN16931",
    "summary": "Generate Chorus-compliant invoices",
    "version": "18.0.1.0.0",
    "category": "French Localization",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "license": "AGPL-3",
    "depends": [
        "l10n_fr_chorus_account",
        "l10n_fr_einvoicing",
    ],
    "excludes": ["l10n_fr_chorus_facturx"],
    "data": [
        "wizards/chorus_directory_line_migration_view.xml",
        "security/ir.model.access.csv",
        "views/account_move.xml",
    ],
    "installable": True,
    "auto_install": False,
}
