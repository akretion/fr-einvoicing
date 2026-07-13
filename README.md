

# E-Invoicing for France
<!-- /!\ Non OCA Context : Set here the badge of your runbot / runboat instance. -->
[![Pre-commit Status](https://github.com/akretion/fr-einvoicing/actions/workflows/pre-commit.yml/badge.svg?branch=18.0)](https://github.com/akretion/fr-einvoicing/actions/workflows/pre-commit.yml?query=branch%3A18.0)
[![Build Status](https://github.com/akretion/fr-einvoicing/actions/workflows/test.yml/badge.svg?branch=18.0)](https://github.com/akretion/fr-einvoicing/actions/workflows/test.yml?query=branch%3A18.0)
[![codecov](https://codecov.io/gh/akretion/fr-einvoicing/branch/18.0/graph/badge.svg)](https://codecov.io/gh/akretion/fr-einvoicing)
<!-- /!\ Non OCA Context : Set here the badge of your translation instance. -->

<!-- /!\ do not modify above this line -->

Odoo modules for e-invoicing in France starting september 2026.

This set of modules depends on several OCA modules. Some of these OCA modules require a special branch:

* [account_tax_unece](https://github.com/OCA/community-data-files/pull/277) add VATEX codes on taxes

<!-- /!\ do not modify below this line -->

<!-- prettier-ignore-start -->

[//]: # (addons)

Available addons
----------------
addon | version | maintainers | summary
--- | --- | --- | ---
[account_invoice_en16931](account_invoice_en16931/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Base module to generate electronic invoices
[account_invoice_en16931_py3o](account_invoice_en16931_py3o/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Glue module to generate EN16931 invoices with Py3o
[l10n_fr_account_invoice_en16931](l10n_fr_account_invoice_en16931/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Localization of Invoice EN16931 for France
[l10n_fr_einvoicing](l10n_fr_einvoicing/) | 18.0.1.2.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Community implementation of the e-invoicing reform for France
[l10n_fr_einvoicing_dashboard_banner](l10n_fr_einvoicing_dashboard_banner/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Add widgets for eInvoicing flows in Accounting Dashboard Banner
[l10n_fr_einvoicing_import](l10n_fr_einvoicing_import/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Import vendor bills/refunds from accredited platform
[l10n_fr_einvoicing_payment_batch_oca](l10n_fr_einvoicing_payment_batch_oca/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Option to auto-send payment sent event
[l10n_fr_einvoicing_purchase](l10n_fr_einvoicing_purchase/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | Display directory line on purchase order report
[l10n_fr_einvoicing_sale](l10n_fr_einvoicing_sale/) | 18.0.1.0.0 | <a href='https://github.com/alexis-via'><img src='https://github.com/alexis-via.png' width='32' height='32' style='border-radius:50%;' alt='alexis-via'/></a> | eInvoicing for France in Sales

[//]: # (end addons)

<!-- prettier-ignore-end -->

## Licenses

This repository is licensed under [AGPL-3.0](LICENSE).

However, each module can have a totally different license, as long as they adhere to Akretion
policy. Consult each module's `__manifest__.py` file, which contains a `license` key
that explains its license.

----
<!-- /!\ Non OCA Context : Set here the full description of your organization. -->
