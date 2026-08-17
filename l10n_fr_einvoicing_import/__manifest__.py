# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# IMPORTANT : about the location of the code
# between l10n_fr_einvoicing and l10n_fr_einvoicing_import
# The decision is the following:
# all the code that doesn't **technically** depend on account_invoice_import
# should be located in l10n_fr_einvoicing (even if the code is related to
# vendor bills). Avantages:
# 1) simplicity
# 2) we can easily support alternatives to account_invoice_import

{
    "name": "France eInvoicing: Import Vendor Bills",
    "version": "16.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Import vendor bills/refunds from accredited platform",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        # This module only depends technically on account_invoice_import
        # but, from a functionnal point of view, we need
        # account_invoice_import_facturx + account_invoice_import_ubl
        "account_invoice_import_facturx",
        "account_invoice_import_ubl",
    ],
    "data": ["views/account_journal.xml", "views/fr_directory_line.xml"],
    "installable": True,
}
