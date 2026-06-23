# Copyright 2026 Le Filament (https://le-filament.com/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    invoice_sending_method = fields.Selection(
        selection_add=[("fr_pa", "by French Accredited Platform")],
    )

    def _l10n_fr_get_base_identifier(self):
        self.ensure_one()
        if siret := self._get_siret(raise_if_none=False):
            return "siret", siret
        elif siren := self._get_siren(raise_if_none=False):
            return "siren", siren
        else:
            return super()._l10n_fr_get_base_identifier()

    # Overwrite functions from account_edi_ubl_cii to compute eas and endpoint based
    # on default_fr_directory_line_id
    def _peppol_eas_endpoint_depends(self):
        return super()._peppol_eas_endpoint_depends() + ["default_fr_directory_line_id"]

    @api.depends("peppol_eas")
    def _compute_peppol_endpoint(self):
        fr_pdp_partners = self.filtered("default_fr_directory_line_id")
        for partner in fr_pdp_partners:
            partner.peppol_endpoint = partner.default_fr_directory_line_id.identifier
        return super(ResPartner, self - fr_pdp_partners)._compute_peppol_endpoint()

    @api.depends(lambda self: self._peppol_eas_endpoint_depends())
    def _compute_peppol_eas(self):
        fr_pdp_partners = self.filtered("default_fr_directory_line_id")
        for partner in fr_pdp_partners:
            partner.peppol_eas = "0225"
        return super(ResPartner, self - fr_pdp_partners)._compute_peppol_eas()

    def _get_siren(self, raise_if_none=False):
        # Bypass invalid siren for superPDP test
        if self.siren in ["000000001", "000000002"]:
            return self.siren
        else:
            return super()._get_siren(raise_if_none=raise_if_none)
