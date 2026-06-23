# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountEdiXmlUbl21Fr(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_21_fr"

    def _import_ubl_retrieve_customer(self, collected_values):
        res = super()._import_ubl_retrieve_customer(collected_values)
        customer_values = collected_values.get("customer_values")
        if customer_values.get("peppol_eas", False) == "0225" and customer_values.get(
            "peppol_endpoint", False
        ):
            collected_values["to_write"]["fr_directory_line_identifier"] = (
                customer_values.get("peppol_endpoint")
            )
        return res
