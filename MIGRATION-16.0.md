# Backport EN16931 → Odoo 16.0

Working branch: `MIG-16.0-account_invoice_en16931`, forked from `18.0` at `a8bf088`.

**Status: analysis only. No migration code has been written yet.** The three modules in scope are
marked `installable: False` on purpose — the code is still the 18.0 code and would not install on
16.0. Only the manifests have been retargeted (`16.0.1.0.0`), to anchor the work.

## Scope

| Module | Status |
|---|---|
| `account_invoice_en16931` | Core of the backport. Tax computation layer must be rewritten. |
| `l10n_fr_account_invoice_en16931` | Blocked on a `l10n_fr_siret` backport (see below). |
| `account_invoice_en16931_py3o` | Portable as is (`report_py3o` exists on 16.0, same signature). |

## Why this is not a mechanical backport

The 18.0 code is built on the **generic tax engine introduced in Odoo 18** (`base_line` dicts +
`tax_details`). None of the methods it relies on exist on 16.0, which only has `compute_all()`:

- `_prepare_product_base_line_for_taxes_computation`, `_prepare_base_line_for_taxes_computation`
- `_add_tax_details_in_base_line`, `_add_tax_details_in_base_lines`
- `_round_base_lines_tax_details`, `_aggregate_base_lines_tax_details`,
  `_aggregate_base_lines_aggregated_values`, `_prepare_tax_line_for_taxes_computation`

This affects `_check_en16931`, `_prepare_bg25_single_line`, `_prepare_bg20_single_line` and
`_prepare_bg23` (VAT breakdown: `BT-116`/`BT-117`/`BT-118`/`BT-119`). Rounding must match 18.0
exactly, or the EN16931 schematron fails.

## Two extra backports are required first

These are **not** available on 16.0 and block the module:

1. **VATEX codes** on `account_tax_unece` — come from
   [OCA/community-data-files#277](https://github.com/OCA/community-data-files/pull/277), which is
   **still open** and targets 18.0. The fields `unece_vatex_id` / `unece_vatex_code` and the
   `tax_vatex_eu_o` record exist on **no** branch today.
2. **`l10n_fr_siret`**: `_get_siren()`, `_get_siret()` and `is_france_country` (on `res.partner`)
   exist on the **18.0 branch only** — absent from 16.0 and 17.0. Required by
   `l10n_fr_account_invoice_en16931`.

## Full analysis

The method-by-method matrix, the tax verdict, effort estimate, risks and the ordered migration plan
live in the spec (Obsidian vault):

`projets/alusage/fr-einvoicing-erp16/specs/2026-07-16-backport-account_invoice_en16931-16.0.md`

Odoo task: <https://nicolas.alusage.fr/odoo/project/153/4468>
