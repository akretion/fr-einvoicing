# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import http
from odoo.http import request

logger = logging.getLogger(__name__)

try:
    from facturx import facturx_schematron_get_codedb_xml_file
except (OSError, ImportError) as err:
    logger.debug("Cannot import facturx. Error details below.")
    logger.debug(err)


class GetFacturxCodedb(http.Controller):
    @http.route(
        "/en16931/FACTUR-X_EXTENDED_codedb.xml",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def send_facturx_codedb(self, **kwargs):
        codedb_file_bytes = facturx_schematron_get_codedb_xml_file("extended")
        if not isinstance(codedb_file_bytes, bytes):
            return request.not_found()
        return request.make_response(
            codedb_file_bytes, [("Content-Type", "application/xml")]
        )
