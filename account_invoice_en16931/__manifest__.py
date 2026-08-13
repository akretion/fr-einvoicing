# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Invoice EN16931",
    "version": "19.0.1.0.0",
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
    # fonttools is what odoo.tools.pdf.convert_to_pdfa() uses to rebuild the
    # glyph width arrays produced by wkhtmltopdf; without it the PDF/A-3
    # output fails veraPDF rule 6.2.11.5 and Odoo only logs a warning.
    # No upper pin needed on 19.0: convert_to_pdfa() handles both the old
    # getGlyphSet()._hmtx and the current hMetrics API.
    "external_dependencies": {"python": ["factur-x>=6.7", "fonttools"]},
    "data": [
        "security/ir.model.access.csv",
        "wizards/account_invoice_en16931_generate_view.xml",
        "views/account_move.xml",
        "views/res_partner.xml",
        "wizards/res_config_settings_view.xml",
    ],
    "installable": True,
}
