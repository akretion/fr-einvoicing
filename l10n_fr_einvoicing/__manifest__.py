# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'France eInvoicing',
    'version': '18.0.1.0.1',
    'category': 'Accounting',
    'license': 'AGPL-3',
    'summary': 'Community implementation of the e-invoicing reform for France',
    'author': 'Akretion',
    'maintainers': ['alexis-via'],
    'website': 'https://github.com/akretion/fr-einvoicing',
    'depends': [
        'l10n_fr_siret_account',
        ],
    'excludes': ['l10n_fr_chorus_account'],  # to be discussed
    'external_dependencies': {'python': ["pyfrctc>=0.7"]},
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rule.xml',
        "data/ir_cron.xml",
        "data/mail_activity_type.xml",
        "data/ir_actions_server.xml",
        'wizards/res_config_settings_view.xml',
        "wizards/fr_einvoicing_event_manual_view.xml",
        "views/menu.xml",
        "views/fr_directory_line.xml",
        "views/fr_einvoicing_flow.xml",
        "views/fr_einvoicing_event.xml",
        "views/res_partner.xml",
        "views/account_move.xml",
        "views/account_journal.xml",
        "views/fr_einvoicing_log.xml",
        "views/onboarding_templates.xml",
    ],
    'installable': True,
}
