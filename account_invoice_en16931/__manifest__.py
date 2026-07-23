# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Invoice EN16931",
    "version": "16.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Base module to generate electronic invoices",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account_tax_unece",
        "uom_unece",
        "base_vat",
        "intrastat_base",
    ],
    # Optional: install account_payment_unece (OCA bank-payment stack) if you
    # want the payment means block (BT-81/84/86) filled in the generated XML.
    # It is not a hard dependency here: _en16931_payment_mean() reads the payment
    # mode defensively and simply omits that block when the stack is absent.
    "excludes": ["account_einvoice_generate"],
    # fonttools is an optional dependency of odoo.tools.pdf.convert_to_pdfa():
    # without it, the glyph width arrays produced by wkhtmltopdf are left as is
    # and the PDF/A-3 output fails veraPDF rule 6.2.11.5. Declaring it here makes
    # the Factur-X PDF actually PDF/A compliant. 16.0-specific.
    # Pinned < 4.34: convert_to_pdfa() reads getGlyphSet()._hmtx, an internal
    # fontTools API removed around 4.34 (KO on 4.38+), so a newer fonttools
    # raises AttributeError instead of fixing the glyph widths.
    "external_dependencies": {"python": ["factur-x>=6.5", "fonttools<4.34"]},
    "data": [
        "security/ir.model.access.csv",
        "wizards/account_invoice_en16931_generate_view.xml",
        "views/account_move.xml",
        "views/res_partner.xml",
        "wizards/res_config_settings_view.xml",
    ],
    "installable": True,
}
