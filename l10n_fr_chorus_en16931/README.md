# Module l10n_fr_chorus_en16931

This module is designed to be used on Odoo deployments that use the eInvoicing modules
hosted in this Github project and also use the OCA Chorus Pro connector (module
**l10n_fr_chorus_account**). This is needed until
[SUPER PDP](https://www.superpdp.tech/) fully supports the transmission of e-Invoices to
Chorus Pro.

This module also contains a wizard to migrate:

- the **Chorus Services** configured on invoicing contacts of French public-sector
  entities,
- the **Chorus attachments** on customer invoice/refunds to the new field **eInvoice
  Attachments** added by the module **account_invoice_en16931**

To deploy this module, follow these instructions:

1. Uninstall the module **account_einvoice_generate**. It should trigger the uninstall
   of the modules account_invoice_facturx, l10n_fr_account_invoice_facturx and
   l10n_fr_chorus_facturx. The module l10n_fr_chorus_account is kept installed.
2. Install the module l10n_fr_chorus_en16931.
3. Go to the accounting configuration page: in the _Chorus Pro_ section, set the field
   **Chorus Invoice Format** to **Factur-X (new module)**.
4. Go to the menu **Configuration > Technical > Chorus Pro > Chorus Directory Line
   Migration**: read instructions on the pop-up and launch the migration. Look at the
   warnings and errors that may have been written in the Odoo server logs during the
   execution of this migration wizard.
