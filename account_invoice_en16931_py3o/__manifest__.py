# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Invoice EN16931 Py3o",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Glue module to generate EN16931 invoices with Py3o",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "account_invoice_en16931",
        "report_py3o",
    ],
    "data": [],
    # report_py3o dropped the "py3o.report" model in 19.0: post-processing now
    # happens in ir.actions.report._render_py3o. The _postprocess_report hook this
    # glue overrides no longer exists, so it must be rewritten before re-enabling.
    "installable": False,
}
