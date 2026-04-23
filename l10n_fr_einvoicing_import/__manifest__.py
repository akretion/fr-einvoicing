# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'France eInvoicing: Import Vendor Bills',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'license': 'AGPL-3',
    'summary': 'Import vendor bills/refunds from accredited platform',
    'author': 'Akretion',
    'maintainers': ['alexis-via'],
    'website': 'https://github.com/akretion/fr-einvoicing',
    'depends': [
        'l10n_fr_einvoicing', 'account_invoice_import',
        ],
    'external_dependencies': {'python': ["pyfrctc"]},
    'data': [
#        'security/ir.model.access.csv',
        'wizards/res_config_settings_view.xml',
#        "views/res_partner.xml",
        "views/account_journal.xml",
    ],
    'installable': True,
}
