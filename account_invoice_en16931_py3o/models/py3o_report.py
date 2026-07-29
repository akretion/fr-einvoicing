# Copyright 2017-2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class Py3oReport(models.TransientModel):
    _inherit = "py3o.report"

    def _postprocess_report(self, model_instance, result_path):
        report = self.ir_actions_report_id
        if (
            self.env["ir.actions.report"]._is_invoice_report(report.report_name)
            and model_instance
            and len(model_instance) == 1
            and report.report_type == "py3o"
            and report.py3o_filetype == "pdf"
            and result_path
            and not self.env.context.get("regular_pdf_invoice")
        ):
            move = model_instance
            invoice_format = move._get_pdf_invoice_format()
            if invoice_format:
                move._regular_pdf_invoice_to_en16931_pdf_invoice(
                    result_path, invoice_format
                )
        return super()._postprocess_report(model_instance, result_path)
