# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eReporting",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Community implementation of e-reporting for France",
    "author": "Akretion",
    "maintainers": ["alexis-via"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        "l10n_fr_account_vat_return",
    ],
    "external_dependencies": {"python": ["packaging", "unidecode", "pyfrctc>=0.16"]},
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_cron.xml",
        "wizards/res_config_settings_view.xml",
        "views/account_move.xml",
        "views/account_move_line.xml",
        "views/fr_ereporting.xml",
    ],
    "installable": True,
}
