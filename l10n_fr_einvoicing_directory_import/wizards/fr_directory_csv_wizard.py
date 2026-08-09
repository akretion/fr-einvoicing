# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64
import io
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError


class FrDirectoryCsvWizard(models.TransientModel):
    _name = "fr.directory.csv.wizard"
    _description = "Import/Export eInvoicing directory via CSV"

    # Step 1: export the SIREN numbers to deposit on the directory
    only_missing = fields.Boolean(
        string="Only companies without a directory line",
        default=True,
        help="Export only companies that do not have any directory line yet "
        "(i.e. not registered in the directory).",
    )
    export_file = fields.Binary(string="SIREN file", readonly=True)
    export_filename = fields.Char(readonly=True)
    # Step 2: import the directory return CSV
    import_file = fields.Binary(string="Directory return CSV")
    import_filename = fields.Char()
    result_summary = fields.Text(readonly=True)
    result_partner_ids = fields.Many2many(
        "res.partner", string="Updated companies", readonly=True
    )

    def action_export_siren(self):
        self.ensure_one()
        partners = self.env["res.partner"].browse(
            self.env.context.get("active_ids") or []
        )
        if not partners:
            partners = self.env["res.partner"].search(
                [("is_company", "=", True), ("parent_id", "=", False)]
            )
        if self.only_missing:
            # Drop companies that already have at least one directory line
            # (active or not): they are already registered.
            with_lines = (
                self.env["fr.directory.line"]
                .with_context(active_test=False)
                .search([("partner_id", "in", partners.ids)])
                .partner_id
            )
            partners = partners - with_lines
        Line = self.env["fr.directory.line"]
        chunks = Line._directory_export_siren_chunks(partners)
        if not chunks:
            raise UserError(_("No SIREN to export for the selected companies."))
        # A single CSV, or a ZIP of several CSV when the directory limits
        # (5000 lines / 1 MB per file) require splitting.
        if len(chunks) == 1:
            data, name = chunks[0], "directory_siren.csv"
        else:
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, chunk in enumerate(chunks, start=1):
                    zf.writestr("directory_siren_%02d.csv" % i, chunk)
            data, name = zbuf.getvalue(), "directory_siren.zip"
        count = len(Line._directory_export_siren_list(partners))
        self.write(
            {
                "export_file": base64.b64encode(data),
                "export_filename": name,
                "result_summary": _(
                    "%(c)s SIREN exported in %(f)s file(s) "
                    "(max 5000 lines / 1 MB each)."
                )
                % {"c": count, "f": len(chunks)},
            }
        )
        return self._reopen()

    def action_import(self):
        self.ensure_one()
        if not self.import_file:
            raise UserError(_("Please upload the directory return CSV first."))
        res = self.env["fr.directory.line"]._directory_import_csv(
            base64.b64decode(self.import_file)
        )
        summary = _(
            "Import done: %(c)s created, %(u)s updated, %(s)s skipped, %(a)s ambiguous."
        ) % {
            "c": res["created"],
            "u": res["updated"],
            "s": res["skipped"],
            "a": res.get("ambiguous", 0),
        }
        if res["errors"]:
            summary += "\n\n" + "\n".join(res["errors"][:50])
        self.write(
            {
                "result_summary": summary,
                "result_partner_ids": [(6, 0, res.get("partner_ids", []))],
            }
        )
        return self._reopen()

    def action_view_partners(self):
        """Open the list of companies created/updated by the last import."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Updated companies"),
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("id", "in", self.result_partner_ids.ids)],
        }

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
