

# E-Invoicing for France
<!-- /!\ Non OCA Context : Set here the badge of your runbot / runboat instance. -->
[![Pre-commit Status](https://github.com/akretion/fr-einvoicing/actions/workflows/pre-commit.yml/badge.svg?branch=18.0)](https://github.com/akretion/fr-einvoicing/actions/workflows/pre-commit.yml?query=branch%3A18.0)
[![Build Status](https://github.com/akretion/fr-einvoicing/actions/workflows/test.yml/badge.svg?branch=18.0)](https://github.com/akretion/fr-einvoicing/actions/workflows/test.yml?query=branch%3A18.0)
[![codecov](https://codecov.io/gh/akretion/fr-einvoicing/branch/18.0/graph/badge.svg)](https://codecov.io/gh/akretion/fr-einvoicing)
<!-- /!\ Non OCA Context : Set here the badge of your translation instance. -->

<!-- /!\ do not modify above this line -->

Odoo modules for e-invoicing and e-reporting in France starting september 1st 2026.

This set of modules depends on several OCA modules. Make sure that you are running up-to-date code for the following OCA repositories:

* [OCA/account-financial-tools](https://github.com/OCA/account-financial-tools)
  * account_dashboard_banner (dependency of l10n_fr_einvoicing_dashboard_banner)
* [OCA/bank-payment](https://github.com/OCA/account-payment)
  * account_payment_mode
  * account_payment_partner
* [OCA/community-data-files](https://github.com/OCA/community-data-files)
  * account_payment_unece
  * account_tax_unece
  * base_unece
  * uom_unece
* [OCA/edi](https://github.com/OCA/edi) (dependencies of l10n_fr_einvoicing_import)
  * account_invoice_import
  * account_invoice_import_facturx
  * account_invoice_import_ubl
  * base_business_document_import
  * base_facturx
  * base_ubl
  * base_ubl_parse
  * pdf_helper
* [OCA/intrastat-extrastat](https://github.com/OCA/intrastat-extrastat)
  * intrastat_base
* [OCA/l10n-france](https://github.com/OCA/l10n-france)
  * l10n_fr_account_invoice_import_facturx
  * l10n_fr_business_document_import
  * l10n_fr_siret
  * In addition to the above, for automatic configuration of UNECE tax codes, you may want to install l10n_fr_account_tax_unece or l10n_fr_oca
* [OCA/reporting-engine](https://github.com/OCA/reporting-engine)
  * report_py3o (dependency of account_invoice_en16931_py3o)
* [OCA/sale-workflow](https://github.com/OCA/sale-workflow)
  * sale_commercial_partner (dependency of l10n_fr_einvoicing_sale)
* [OCA/server-tools](https://github.com/OCA/server-tools)
  * base_view_inheritance_extension

You should also make sure that the code of Odoo 16.0 you are running on is up-to-date.

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
[l10n_fr_einvoicing_directory_import](l10n_fr_einvoicing_directory_import/) | 18.0.1.0.0 |  | Maintain fr.directory.line manually via CSV export/import when the AFNOR directory API is not available
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
