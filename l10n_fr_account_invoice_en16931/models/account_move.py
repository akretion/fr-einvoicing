# Copyright 2026 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _prepare_en16931_dict(self, speedy, pdf_invoice_bin=False):
        vals = super()._prepare_en16931_dict(speedy, pdf_invoice_bin=pdf_invoice_bin)
        chorus = (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_partner_entity_type == "public"
        )
        # TODO improve filtering
        if self.company_id.is_france_country:
            # SELLER
            seller_siren = self.company_id.partner_id._get_siren()
            if seller_siren:
                vals.update(
                    {
                        "BT-30": seller_siren,
                        "BT-30-1": "0002",
                    }
                )
            if chorus:
                seller_siret = self.company_id.partner_id._get_siret()
                if seller_siret:
                    vals["BT-29"]["0009"] = seller_siret
            # BUYER
            buyer_siren = self.partner_id._get_siren()
            if buyer_siren:
                vals.update(
                    {
                        "BT-47": buyer_siren,
                        "BT-47-1": "0002",
                    }
                )
            if chorus:
                buyer_siret = self.commercial_partner_id._get_siret()
                if buyer_siret:
                    vals["BT-46"]["0009"] = buyer_siret
                if (
                    self.fr_directory_line_id.type == "routing_code"
                    and self.fr_directory_line_id.routing_code
                ):
                    vals["BT-46"]["0240"] = self.fr_directory_line_id.routing_code
                    vals["BT-56-0"] = (
                        self.fr_directory_line_id.routing_code_name
                    )  # UBL ?
        return vals

    def _prepare_bg1(self, speedy):
        res = super()._prepare_bg1(speedy)
        # TODO translate ? fields ?
        res += [
            {
                "BT-21": "PMT",
                "BT-22": "Indemnité forfaitaire pour frais de recouvrement "
                "en cas de retard de paiement : 40 €.",
            },
            {
                "BT-21": "PMD",
                "BT-22": "Tout retard de paiement engendre une pénalité "
                "exigible à compter de la date d'échéance, "
                "calculée sur la base de trois fois le taux d'intérêt légal.",
            },
            {
                "BT-21": "AAB",
                "BT-22": "Les réglements reçus avant la date d'échéance "
                "ne donneront pas lieu à escompte.",
            },
        ]
        if (
            hasattr(self, "fr_directory_partner_entity_type")
            and self.fr_directory_partner_entity_type == "public"
        ):
            res.append({"BT-21": "ADN", "BT-22": "B2G"})
        return res
