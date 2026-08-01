# Backport EN16931 → Odoo 16.0

Working branch: `MIG-16.0-account_invoice_en16931`, forked from `18.0` at `a8bf088`.

**Status: the whole stack is ported and installable on 16.0.** All ten modules below are back to
`installable: True` and install on a 16.0 community database, and the four upstream 18.0 commits
that landed after the fork point are backported (see *What is left to port*).

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

## Two extra backports were required first

Neither was available on 16.0. Both now live in Alusage forks, consumed by the 16.0 test instance:

1. **VATEX codes** on `account_tax_unece` — from
   [OCA/community-data-files#277](https://github.com/OCA/community-data-files/pull/277) (still open
   upstream, targets 18.0). Backported on
   `Alusage/community-data-files@16.0-backport-account_tax_unece-vatex`.
2. **`l10n_fr_siret`**: `_get_siren()`, `_get_siret()` and `is_france_country` (on `res.partner`)
   exist on the **18.0 branch only**. Backported on
   `Alusage/l10n-france@16.0-backport-l10n_fr_siret-einvoicing-helpers`.

Activating `account_invoice_en16931_py3o` adds one more repository to provision: `report_py3o` from
OCA `reporting-engine` 16.0, whose `external_dependencies` are `py3o.template` and `py3o.formats`
(picked up by jarvis `update_requirements`) plus the `libreoffice` deb. Odoo does not check the `deb`
key at install time, so the module installs without it — but no py3o report can actually be
rendered, hence no end-to-end test of the glue.

## 🔴 `l10n_fr_account_tax_unece` must be installed explicitly

On a French database, nothing can be posted until the taxes carry a UNECE tax type:
`account_invoice_en16931._post()` calls `_en16931_checks()`, which raises
*"Tax 'TVA 20% (Goods)' has no UNECE Tax Type"* on **every** customer invoice. The module that fills
those codes in is `l10n_fr_account_tax_unece` (OCA `l10n-france`, `post_init_hook`
`set_unece_on_taxes`), and it is **not** a dependency of anything in this stack.

It looks like it should install itself — its manifest says `"auto_installable": True` — but that key
does not exist in Odoo. The real one is **`auto_install`**, and unknown manifest keys are silently
ignored, so the module never auto-installs. The typo is upstream OCA and present on 16.0, 17.0 and
18.0 alike, so this is not a backport artefact.

Consequences, all reproduced on a demo database with the stack installed but without that module:
the demo invoices of `account` stay in draft (`Error while posting demo data`, four of them), and the
seven `account_payment_partner` tests that post a customer invoice fail. **Install
`l10n_fr_account_tax_unece` with the stack** — or, on an existing database, install it and re-run its
hook, then re-post.

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
15 in `l10n_fr_einvoicing`). Testing the cascade also surfaces 45 failures in modules we do not own.
None is caused by this backport, and three are worth knowing about:

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

## Upstream 18.0 commits backported after the fork

Four commits landed on `upstream/18.0` after the fork point `5b0f0ff`. All four are now backported,
authorship preserved, each with its `cherry picked from` trailer:

| Upstream | Backport | What the 16.0 port required |
|---|---|---|
| `4e97b69` | `49e3102` | Config to send/receive invoices on the accounting config page (`fr_ctc_send_out_invoice` replaces `fr_ctc_disable_private_invoice_sending`, `fr_ctc_get_in_invoice` gates the `SupplierInvoice` flow type); also fixes a crash when a partner has no last sync date, and narrows flow creation to `fr_einvoicing_required`. Settings converted back to `o_setting_box`; the local `"company_id"` dependency of `_compute_einvoicing_required` kept (see the MemoryError comment above it). |
| `a472fb3` | `3aeb188` | `invoice_attachment_ids` (~350 lines): Chorus Pro attachment checks, Factur-X PDF attachments, `generate_en16931_xml()` reduced to a single flavor returning `(xml_bytes, attachments)`, `variant` renamed `invoice_format`, invoice form collapsed into one "e-Invoicing" tab. Ten `self.env._()` calls rewritten as `_() % …`; the new tab and group converted to `attrs=`; the 16.0-only `_en16931_pdf_to_pdfa()` call and the `company_partner_id` invisible field (needed by the 16.0 client-side domain) kept. |
| `436f45a` | `4836bcf` | Factur-X with the old Chorus XML syntax as a wizard option (`facturx_old_chorus`), driven by the `chorus_old_xml_syntax` context key. Applied cleanly. |
| `948050d` | `a53db93` | Don't validate the `fr_ctc` schematron for that syntax (one line). Applied cleanly. |

## What is left to port

Nothing. Every upstream module has a 16.0 counterpart, all ten are `installable: True`, no 18.0-only
idiom is left in the ported code (`self.env._(`, `<list>`, dynamic `invisible=`/`readonly=` are all
at zero), the four post-fork upstream commits are in, and the whole stack installs and passes its
tests on a demo database.

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
