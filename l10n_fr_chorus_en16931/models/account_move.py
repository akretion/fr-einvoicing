# Copyright 2026 Akretion France (https://www.akretion.com)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _chorus_get_invoice(self, chorus_invoice_format):
        self.ensure_one()
        if chorus_invoice_format == "pdf_factur-x":
            chorus_file_content = self.with_context(
                chorus_old_xml_syntax=True
            )._get_en16931_invoice_bin("facturx")
        else:
            chorus_file_content = super()._chorus_get_invoice(chorus_invoice_format)
        return chorus_file_content
