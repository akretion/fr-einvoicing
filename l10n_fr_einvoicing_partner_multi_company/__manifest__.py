# Copyright 2026 Akretion France (https://www.akretion.com/)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Compatibility fr-einvoicing and partner_multi_company",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Compatibility between l10n_fr_einvoicing and partner_multi_company",
    "author": "Akretion",
    "maintainers": ["florian-dacosta"],
    "website": "https://github.com/akretion/fr-einvoicing",
    "depends": [
        "l10n_fr_einvoicing",
        "partner_multi_company",
    ],
    "data": [
        "security/ir_rule.xml",
    ],
    "installable": True,
    "auto_install": True,
}
