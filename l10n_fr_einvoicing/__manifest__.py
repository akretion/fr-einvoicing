# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing",
    "version": "16.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Community implementation of the e-invoicing reform for France",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_account_invoice_en16931",
    ],
    # "excludes": ["l10n_fr_chorus_account"],  # we need the module for the transition
    "external_dependencies": {"python": ["pyfrctc>=0.15"]},
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_cron.xml",
        "data/mail_activity_type.xml",
        "data/ir_actions_server.xml",
        "wizards/fr_einvoicing_company_directory_sync_view.xml",
        "wizards/res_config_settings_view.xml",
        "wizards/fr_einvoicing_event_manual_view.xml",
        "wizards/account_move_reversal_view.xml",
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
    # demo data will have to be re-designed
    #  "demo": ["demo/partner_demo.xml"],
    "installable": True,
}
