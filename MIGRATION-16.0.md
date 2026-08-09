# Backport EN16931 → Odoo 16.0

Working branch: `MIG-16.0-account_invoice_en16931`, rebased on `upstream/16.0`.

**Status: the whole stack is ported and installable on 16.0.** All ten modules below are back to
`installable: True` and install on a 16.0 community database.

## Scope

| Module | Status |
|---|---|
| `account_invoice_en16931` | Ported. Tax layer rewritten on the 16.0 tax engine. |
| `l10n_fr_account_invoice_en16931` | Ported, on OCA `l10n_fr_siret` 16.0. |
| `l10n_fr_einvoicing` | Ported (Python, views, `env._`). |
| `l10n_fr_einvoicing_import` | Ported. |
| `l10n_fr_einvoicing_purchase` | Ported. |
| `l10n_fr_einvoicing_sale` | Ported. |
| `l10n_fr_einvoicing_dashboard_banner` | Ported. |
| `l10n_fr_einvoicing_batch_payment` | Ported. Renamed from `l10n_fr_einvoicing_payment_batch_oca`: `account_payment_batch_oca` is 18.0-only, the overridden method lives on `account.payment.order` (OCA `account_payment_order`). |
| `l10n_fr_einvoicing_directory_import` | Ported (Sudokeys module, not upstream). Identical to the 18.0 branch, plus the tests. |
| `account_invoice_en16931_py3o` | Ported and `installable: True`. Its glue already fit 16.0; `report_py3o` exists in OCA `reporting-engine` 16.0 (`16.0.1.0.6`) with the same `py3o.report` API. |

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

## Dependencies: plain OCA 16.0 is enough

Two prerequisites were missing from OCA 16.0 when this port started, and were carried on Alusage
forks. **Both have since landed upstream — the forks are no longer needed:**

1. **VATEX codes** on `account_tax_unece`: `data/unece_tax_vatex.xml`, the `unece_vatex_id` field
   and `_compute_unece_vatex_id()` are on `OCA/community-data-files` `16.0`.
2. **`l10n_fr_siret` helpers**: `is_france_country`, `_get_siren()`, `_get_siret()` and `_get_nic()`
   are on `OCA/l10n-france` `16.0`, added on 27/07 by
   [`9e662b1a`](https://github.com/OCA/l10n-france/commit/9e662b1a).

⚠️ That same commit also extended `_check_siret` to the `vat` field: a French VAT number must now
end with the nine digits of the SIREN. Any partner data carrying an inconsistent pair — including
demo data — is rejected on load. This is what made the demo of `l10n_fr_einvoicing` abort the
database on instances running a post-27/07 `l10n_fr_siret`; fixed on this branch, and the same pair
is still on `18.0`.

Activating `account_invoice_en16931_py3o` adds one more repository to provision: `report_py3o` from
OCA `reporting-engine` 16.0, whose `external_dependencies` are `py3o.template` and `py3o.formats`
(picked up by jarvis `update_requirements`) plus the `libreoffice` deb. Odoo does not check the `deb`
key at install time, so the module installs without it — but no py3o report can actually be
rendered, hence no end-to-end test of the glue.

## 🔴 A French database is not EN16931-ready out of the box

`account_invoice_en16931._post()` calls `_en16931_checks()`, which refuses to post **any** customer
invoice while the company's tax configuration is incomplete. On a fresh French database that takes
two separate steps, and neither happens on its own.

**Step 1 — install `l10n_fr_account_tax_unece`** (OCA `l10n-france`, `post_init_hook`
`set_unece_on_taxes`). Without it, every post fails with *"Tax 'TVA 20% (Goods)' has no UNECE Tax
Type"*. The module is not a dependency of anything in this stack, and it looks self-installing — its
manifest says `"auto_installable": True` — but **that key does not exist in Odoo**. The real one is
`auto_install`, and unknown manifest keys are ignored silently, so it never auto-installs. Upstream
OCA typo, identical on 16.0, 17.0 and 18.0, so not a backport artefact.

**Step 2 — set a VAT exemption reason on the exempt taxes.** With step 1 done, the check moves on to
*"VAT tax 'TVA 0% EXO (Goods)' has UNECE Tax Category '[E] Exempt from tax' so it should have a VAT
Exemption Reason"* — on `TVA 0% EXO` for both goods and services. `l10n_fr_account_tax_unece` sets
`unece_type_id` and `unece_categ_id` only; it never sets `unece_vatex_id` (zero occurrences in its
data file), and `account_tax_unece._compute_unece_vatex_id()` auto-maps categories K and G
(intra-EU, export) but not E. That is deliberate: a national exemption reason is a legal choice
(which CGI article), so no module can guess it — it has to be configured.

Both steps were verified on a demo database: with the stack alone, the demo invoices and seven
`account_payment_partner` tests fail on step 1; installing the module moves them to step 2 rather
than fixing them — the failure count does not budge. What the database looks like after step 1, which
shows the auto-mapping covering K and G but not E:

| company | sale tax | type | categ | vatex |
|---|---|---|---|---|
| Burger Queen | TVA 0% EU M | VAT | K | `VATEX-EU-IC` |
| Burger Queen | TVA 0% EXPORT | VAT | G | `VATEX-EU-G` |
| Burger Queen | **TVA 0% EXO** (goods, services) | VAT | **E** | **missing** |
| Burger Queen | TVA 20% / 10% | VAT | S | n/a |

Invoice-wise: `Burger Queen → 4 draft`, `Tricatel → 4 posted`. The draft ones cannot be rescued by
configuring the taxes afterwards — they are posted during install — so on a fresh demo database
expect four invoices left in draft on the French company. Note that `account`'s own demo does post
fine, because the dependency graph installs `account` well before `account_invoice_en16931`, while
`_post()` is not yet overridden.

### Running the test suite in the jarvis dev container

Pass `--http-port` on a free port (e.g. `--http-port=8899`). The container's entrypoint runs a
**resident Odoo** on 8069; sharing that port makes every core `HttpCase` hit the resident server
instead of the test one — a parasitised run showed 84 failures + 46 errors, with `web`, `payment`,
`portal`, `bus`, `web_editor` and nine `TestXMLRPC` failing, all of which vanish once the port is
isolated. Worse, on an empty database the resident server may start initialising it concurrently with
the run, which breaks the registry (`duplicate key … pg_type_typname_nsp_index`) and stops the
container.

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

### Full-cascade run, after the upstream backports

Same worktree, database recreated with demo data, all **ten** modules installed and `--test-enable`
left unrestricted, so the whole dependency cascade is tested too (83 modules loaded, none in error):

```
odoo -d odoo-dev -i account_invoice_en16931,account_invoice_en16931_py3o,\
l10n_fr_account_invoice_en16931,l10n_fr_einvoicing,l10n_fr_einvoicing_batch_payment,\
l10n_fr_einvoicing_dashboard_banner,l10n_fr_einvoicing_directory_import,\
l10n_fr_einvoicing_import,l10n_fr_einvoicing_purchase,l10n_fr_einvoicing_sale \
  --test-enable --stop-after-init
```

**Our ten modules: 49 tests, 0 failures, 0 errors** (34 in `l10n_fr_einvoicing_directory_import`,
15 in `l10n_fr_einvoicing`) — confirmed twice, with and without `l10n_fr_account_tax_unece`, the
second time with the port isolated (`33 failed, 14 error(s) of 1646`). Testing the cascade also
surfaces 47 failures in modules we do not own: `mail` 11, `account_invoice_import` 8, `base` 7,
`account_payment_partner` 7, `sms` 5, `google_gmail` 3, `sale` 2, and one each in `report_py3o`,
`base_vat` and `account_dashboard_banner`. None is caused by this backport, and three are worth
knowing about:

- `account_invoice_import` (8) — from the `Alusage/edi` fork. Reproduced **on a clean database with
  that module alone**, no reform stack installed: same `2 failures, 6 errors of 11 tests`. The cause
  is a `payment_term` line inserted without `account_id`
  (`account_move_line_check_accountable_required_fields`). Pre-existing, and worth checking against
  [OCA/edi#1379](https://github.com/OCA/edi/pull/1379).
- `account_payment_partner` (7) — these do go through our `_post`, but the check that blocks them
  (`_en16931_checks()`, in `account_invoice_en16931._post`) is unchanged from before the backport:
  posting any customer invoice is refused while the company's taxes have no UNECE tax type, which is
  the module's intended behaviour. It does mean **installing `account_invoice_en16931` breaks any
  third-party test that posts a customer invoice on a company without UNECE-coded taxes** — an
  upstream design point, not a 16.0 one. `4e97b69` narrows exactly this kind of check to
  `fr_einvoicing_required` in `l10n_fr_einvoicing`; `account_invoice_en16931` still checks
  unconditionally.
- `account_dashboard_banner` (1) — `isinstance(x, (int | float))` needs Python 3.10; this image runs
  3.9. A bug in the OCA 16.0 module, unrelated to the reform stack.

The rest are core modules failing on this from-source image (`base`, `mail`, `sms`, `google_gmail`,
`sale`, `base_vat` — RTC, VIES SOAP, sanitizer), plus `report_py3o`'s `test_py3o_report_availability`
(no LibreOffice in the image, so `lo_bin_path` is empty).

## Rebase on `upstream/16.0`

Akretion opened its own `16.0` branch and carried seven commits onto it (the send/receive
configuration, `invoice_attachment_ids`, `business_process_type` (BT-23), the Chorus old-syntax
option and its schematron exemption, and two fixes). Four of them had been backported on this
branch beforehand; those backports were dropped on the rebase, upstream's own versions being
authoritative.

Those commits are written against 18.0 APIs, so one commit re-ports them to 16.0:

| What upstream added | What 16.0 required |
|---|---|
| Twelve `self.env._("…", key=value)` calls | Rewritten as `_("…") % {…}`: `env._` does not exist before 17.0 and silently drops its arguments. |
| BT-23 moved to `l10n_fr_account_invoice_en16931`, deciding on `product_id.type == "consu"` | On 16.0 the `stock` module adds `('product', 'Storable Product')` to `product.type`, so goods are `'product'` and every physical-goods invoice would be reported as a mixed process (M1/M2) instead of B1/B2. Uses the `_EN16931_GOODS_TYPES` tuple carried by `account_invoice_en16931`. |
| The shared `e-Invoicing` notebook page and the new settings, in 17+ view syntax | Converted to `attrs=` and to `o_setting_box`. |

Upstream's `[FIX] don't store fr_einvoicing_required` supersedes the fix that was carried here for
[#36](https://github.com/akretion/fr-einvoicing/issues/36) (MemoryError when the issuer's entity
type is set on a database with a real invoicing history): dropping `store=True` removes the mass
recompute at the root, so the local fix was dropped on the rebase.

## What is left to port

Nothing. Every upstream module has a 16.0 counterpart, all ten are `installable: True`, no 18.0-only
idiom is left in the ported code (`self.env._(`, `<list>`, dynamic `invisible=`/`readonly=` are all
at zero), and the whole stack installs and passes its tests on a demo database.

Two follow-ups, both outside the 16.0 stack itself:

1. **`account_invoice_en16931_py3o` has no end-to-end run.** It installs, but exercising the glue
   means rendering a py3o report, which needs LibreOffice in the image — absent here, which is also
   why `report_py3o`'s own `test_py3o_report_availability` fails (`lo_bin_path` empty). Nothing
   points at the port; it is untested past install.
2. **The 16.0 tests of `l10n_fr_einvoicing_directory_import` are forward-ported to 18.0** on the
   local branch `18.0-directory-import-tests` (off `origin/18.0-add-directory-import`, where that
   module lives — it is absent from `upstream/18.0`). Not pushed, not run against an 18.0 database.

Nothing to take from `origin/18.0-add-directory-import` (the module is byte-identical here, minus the
version and the wizard view idiom) nor from `origin/18.0-tmp_hack_chorus` (a temporary Chorus hack).
`origin/18.0` itself is ten commits behind `upstream/18.0`.

## Full analysis

The method-by-method matrix, the tax verdict, effort estimate, risks and the ordered migration plan
live in the spec (Obsidian vault):

`projets/alusage/fr-einvoicing-erp16/specs/2026-07-16-backport-account_invoice_en16931-16.0.md`

Odoo tasks: <https://nicolas.alusage.fr/odoo/project/153/4468> (backport),
<https://nicolas.alusage.fr/odoo/project/153/4525> (reform stack activation).
