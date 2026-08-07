# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "France eInvoicing Directory Import/Export (CSV)",
    "version": "16.0.1.0.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "Maintain fr.directory.line manually via CSV export/import "
    "when the AFNOR directory API is not available",
    "author": "Sudokeys",
    "website": "https://github.com/akretion/fr-einvoicing",
    "license": "AGPL-3",
    "depends": [
        "l10n_fr_einvoicing",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/fr_directory_csv_wizard_views.xml",
    ],
    "installable": True,
}
