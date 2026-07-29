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

## Full analysis

The method-by-method matrix, the tax verdict, effort estimate, risks and the ordered migration plan
live in the spec (Obsidian vault):

`projets/alusage/fr-einvoicing-erp16/specs/2026-07-16-backport-account_invoice_en16931-16.0.md`

Odoo tasks: <https://nicolas.alusage.fr/odoo/project/153/4468> (backport),
<https://nicolas.alusage.fr/odoo/project/153/4525> (reform stack activation).
