# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import tarfile
import zipfile
from io import BytesIO

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AccountInvoiceEn16931Generate(models.TransientModel):
    _name = "account.invoice.en16931.generate"
    _description = "Invoice EN16931 Generate"

    move_ids = fields.Many2many(
        "account.move", string="Customer Invoices", required=True, readonly=True
    )
    invoice_format = fields.Selection(
        [
            ("facturx", "Factur-X"),
            ("facturx_ubl", "Factur-X with additional UBL XML attachment"),
            ("pdf_ubl", "PDF invoice with UBL XML attachment"),
            ("ubl_pdf", "UBL XML with embedded PDF file"),
            ("ubl", "UBL XML"),
            ("cii_pdf", "CII XML with embedded PDF file"),
            ("cii", "CII XML"),
        ],
        required=True,
        default="facturx",
    )
    archive_format = fields.Selection(
        [
            ("zip", "ZIP"),
            ("tar.gz", "Tar GZ"),
            ("tar.bz2", "Tar BZ2"),
            ("tar.xz", "Tar XZ"),
            ("tar", "Tar (no compression)"),
        ],
        default="zip",
    )
    type = fields.Selection(
        [
            ("single", "Single"),
            ("multi", "Multi"),
        ],
        compute="_compute_type",
    )
    filename = fields.Char()
    file_data = fields.Binary()

    @api.depends("move_ids")
    def _compute_type(self):
        for wiz in self:
            wiz.type = len(wiz.move_ids) > 1 and "multi" or "single"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_ids = []
        if self.env.context.get("active_model") and self.env.context.get("active_ids"):
            moves = self.env["account.move"].browse(self.env.context["active_ids"])
            for move in moves:
                if (
                    move.is_sale_document()
                    and move.state != "cancel"
                    and move.partner_id
                    and move.invoice_line_ids.filtered(
                        lambda x: x.display_type == "product"
                    )
                ):
                    move_ids.append(move.id)
        if not move_ids:
            raise UserError(
                _("No customer invoice/refund in draft or posted state selected.")
            )
        res["move_ids"] = [Command.set(move_ids)]
        return res

    def generate_button(self):
        self.ensure_one()
        if not self.move_ids:
            raise UserError(_("You must select at least one customer invoice/refund."))
        if len(self.move_ids) == 1:
            move = self.move_ids
            file_b64 = move._get_en16931_invoice_bin(self.invoice_format, b64=True)
            filename = move._prepare_en16931_filename(self.invoice_format)
        else:
            if not self.archive_format:
                raise UserError(_("You must select an archive format."))
            if self.archive_format == "zip":
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    for move in self.move_ids:
                        inv_filename = move._prepare_en16931_filename(
                            self.invoice_format
                        )
                        inv_bin = move._get_en16931_invoice_bin(self.invoice_format)
                        zip_file.writestr(inv_filename, inv_bin)
                archive_bin = zip_buffer.getvalue()
            else:
                tar_buffer = BytesIO()
                compression = self.archive_format[4:]
                with tarfile.open(
                    fileobj=tar_buffer, mode=f"w:{compression}"
                ) as tar_file:
                    for move in self.move_ids:
                        inv_filename = move._prepare_en16931_filename(
                            self.invoice_format
                        )
                        inv_bin = move._get_en16931_invoice_bin(self.invoice_format)
                        tar_info = tarfile.TarInfo(name=inv_filename)
                        tar_info.size = len(inv_bin)
                        tar_file.addfile(tar_info, fileobj=BytesIO(inv_bin))
                archive_bin = tar_buffer.getvalue()
            file_b64 = base64.encodebytes(archive_bin)
            filename = f"customer_invoices.{self.archive_format}"
        self.write(
            {
                "filename": filename,
                "file_data": file_b64,
            }
        )
        action = {
            "name": _("Invoice(s)"),
            "type": "ir.actions.act_url",
            "url": f"web/content/?model={self._name}&id={self.id}&"
            f"filename_field=filename&field=file_data&download=true&"
            f"filename={filename}",
            "target": "new",
        }
        return action
