# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _fr_ctc_prepare_flow(self):
        # Extends l10n_fr_einvocing
        vals = super()._fr_ctc_prepare_flow()
        # If invoice_edi_format set on partner is UBL 21 for France we update syntax
        # Otherwise we keep default Factur-X
        invoice_edi_format = self.commercial_partner_id.invoice_edi_format
        if invoice_edi_format == "ubl_21_fr":
            vals.update({"syntax": "UBL"})
        return vals
