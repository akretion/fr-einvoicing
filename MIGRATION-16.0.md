# Backport EN16931 → Odoo 16.0

Working branch: `MIG-16.0-account_invoice_en16931`, forked from `18.0` at `a8bf088`.

**Status: the whole stack is ported and installable on 16.0.** Every module below except
`account_invoice_en16931_py3o` is back to `installable: True` and installs on a 16.0 community
database.

## Scope

| Module | Status |
|---|---|
| `account_invoice_en16931` | Ported. Tax layer rewritten on the 16.0 tax engine. |
| `l10n_fr_account_invoice_en16931` | Ported, on top of the `l10n_fr_siret` backport. |
| `l10n_fr_einvoicing` | Ported (Python, views, `env._`). |
| `l10n_fr_einvoicing_import` | Ported. |
| `l10n_fr_einvoicing_purchase` | Ported. |
| `l10n_fr_einvoicing_sale` | Ported. |
| `l10n_fr_einvoicing_dashboard_banner` | Ported. |
| `l10n_fr_einvoicing_batch_payment` | Ported. Renamed from `l10n_fr_einvoicing_payment_batch_oca`: `account_payment_batch_oca` is 18.0-only, the overridden method lives on `account.payment.order` (OCA `account_payment_order`). |
| `l10n_fr_einvoicing_directory_import` | Ported (Sudokeys module, not upstream). Identical to the 18.0 branch, plus the tests. |
| `account_invoice_en16931_py3o` | Out of scope, still `installable: False` (py3o rework). |

## Why this was not a mechanical backport

The 18.0 code is built on the **generic tax engine introduced in Odoo 18** (`base_line` dicts +
`tax_details`). None of the methods it relies on exist on 16.0, which only has `compute_all()`:

- `_prepare_product_base_line_for_taxes_computation`, `_prepare_base_line_for_taxes_computation`
- `_add_tax_details_in_base_line`, `_add_tax_details_in_base_lines`
- `_round_base_lines_tax_details`, `_aggregate_base_lines_tax_details`,
  `_aggregate_base_lines_aggregated_values`, `_prepare_tax_line_for_taxes_computation`

This affects `_check_en16931`, `_prepare_bg25_single_line`, `_prepare_bg20_single_line` and
`_prepare_bg23` (VAT breakdown: `BT-116`/`BT-117`/`BT-118`/`BT-119`). Rounding must match 18.0
exactly, or the EN16931 schematron fails.

Two more 18.0-only idioms had to be undone everywhere: `self.env._("…", key=value)`, which only
returns the string on 16.0 and silently drops its arguments (rewritten as `_("…") % (…)`), and the
view syntax (`<setting>` → `o_setting_box`, `invisible="…"` → `attrs=`, `<list>` → `<tree>`).

## Two extra backports were required first

Neither was available on 16.0. Both now live in Alusage forks, consumed by the 16.0 test instance:

1. **VATEX codes** on `account_tax_unece` — from
   [OCA/community-data-files#277](https://github.com/OCA/community-data-files/pull/277) (still open
   upstream, targets 18.0). Backported on
   `Alusage/community-data-files@16.0-backport-account_tax_unece-vatex`.
2. **`l10n_fr_siret`**: `_get_siren()`, `_get_siret()` and `is_france_country` (on `res.partner`)
   exist on the **18.0 branch only**. Backported on
   `Alusage/l10n-france@16.0-backport-l10n_fr_siret-einvoicing-helpers`.

## Install and test run on 16.0

Run on a jarvis 16.0 worktree (`fr-einvoicing-erp16-16`, branch `dev`), on a database created with
demo data:

```
odoo-dev -d odoo-dev -i account_invoice_en16931,l10n_fr_account_invoice_en16931,l10n_fr_einvoicing,\
l10n_fr_einvoicing_import,l10n_fr_einvoicing_purchase,l10n_fr_einvoicing_sale,\
l10n_fr_einvoicing_dashboard_banner,l10n_fr_einvoicing_batch_payment \
  --test-enable --test-tags '/account_invoice_en16931,/l10n_fr_account_invoice_en16931,…' \
  --stop-after-init
```

The eight modules install (80 modules loaded, none in error) and the suite passes:
`0 failed, 0 error(s) of 15 tests`. The 15 tests are
`l10n_fr_einvoicing/tests/test_partner_check_siren_siret_vat.py`, which exercises
`_fr_directory_check_siren_siret_vat()` — exactly the method whose `self.env._()` calls were
rewritten, so the port of those messages is covered.

The only warning was the demo data, which needed its own port (see the `[FIX] … port the demo data
to 16.0` commit): `l10n_fr` declares the French demo company under `base.partner_demo_company_fr` on
18.0 but under `l10n_fr.partner_demo_company_fr` on 16.0, and `try_loading()` loses its
`template_code` argument on 16.0.

## What is left to port

Nothing structural: every upstream module has a 16.0 counterpart, no 18.0-only idiom is left in the
ported code (`self.env._(`, `<list>`, dynamic `invisible=` are all at zero), and the whole stack
installs and passes its tests.

What remains, in order of interest:

1. **Four upstream 18.0 commits landed after this branch was forked** (fork point `5b0f0ff`), none of
   them backported yet:
   - `4e97b69` [IMP] Configuration to send/receive invoices on accounting config page — also fixes a
     crash when a partner has no last sync date, and the criteria that create a flow on customer
     invoices;
   - `a472fb3` [IMP] `account_invoice_en16931`: add `invoice_attachment_ids` — the biggest one
     (~350 lines): attachment checks for Chorus Pro, invoice form reorganised into a single
     "e-Invoicing" tab, and it touches `account_invoice_en16931_py3o`;
   - `436f45a` [IMP] option to generate Factur-X with the old Chorus XML syntax in the wizard;
   - `948050d` [FIX] don't validate the `fr_ctc` schematron for that old Chorus syntax (one line,
     depends on `436f45a`).
2. **`account_invoice_en16931_py3o`**, still `installable: False`. Its code is already adapted to
   16.0 (`_is_en16931_invoice_report`, `_get_pdf_invoice_variant`); what is missing is a run against
   `report_py3o` from OCA `reporting-engine` 16.0. Note that `a472fb3` changes this module upstream.
3. **The 16.0 tests of `l10n_fr_einvoicing_directory_import` are worth forward-porting to 18.0** —
   the 18.0 branch has none.

Nothing to take from `origin/18.0-add-directory-import` (the module is byte-identical here, minus the
version) nor from `origin/18.0-tmp_hack_chorus` (a temporary Chorus hack). `origin/18.0` itself is
ten commits behind `upstream/18.0`.

## Full analysis

The method-by-method matrix, the tax verdict, effort estimate, risks and the ordered migration plan
live in the spec (Obsidian vault):

`projets/alusage/fr-einvoicing-erp16/specs/2026-07-16-backport-account_invoice_en16931-16.0.md`

Odoo tasks: <https://nicolas.alusage.fr/odoo/project/153/4468> (backport),
<https://nicolas.alusage.fr/odoo/project/153/4525> (reform stack activation).
