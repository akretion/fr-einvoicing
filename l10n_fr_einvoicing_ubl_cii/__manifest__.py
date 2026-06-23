{
    "name": "France eInvoicing - UBL-CII from Odoo",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": """
        Community implementation of the e-invoicing reform for France using Odoo
        Factur-x format
    """,
    "author": "Le Filament",
    "maintainers": ["remi-filament"],
    "website": "https://github.com/lefilament/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        "l10n_fr_account_edi_ubl_cii",
    ],
    "excludes": ["account_peppol", "l10n_fr_pdp"],
    "data": [
        "data/cii_22_templates.xml",
    ],
    "installable": True,
}
