# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, fields, models

logger = logging.getLogger(__name__)


class ChorusDirectoryLineMigration(models.TransientModel):
    _name = "chorus.directory.line.migration"
    _description = "Migrate Chorus Services to Directory Lines"

    def migrate_button(self):
        today = fields.Date.context_today(self)
        logger.info("Start Chorus Pro directory line migration")
        partners_to_mig = self.env["res.partner"].search(
            [
                ("parent_id", "=", False),
                ("invoice_sending_method", "=", "fr_chorus"),
                ("siren", "!=", False),
                ("nic", "!=", False),
            ]
        )
        logger.info(f"Found {len(partners_to_mig)} Chorus partners to migrate")
        partner_ids = []
        for partner in partners_to_mig:
            logger.info(
                f"Migrating partner {partner.display_name} ID {partner.id} that has "
                f"fr_chorus_required={partner.fr_chorus_required}"
            )
            if (
                not partner.fr_directory_last_sync_date
                or partner.fr_directory_last_sync_date < (today - timedelta(5))
            ):
                partner._fr_directory_sync_logs(
                    self.env.company, "Chorus Directory Line Migration"
                )
            if not partner.fr_directory_entity_type:
                logger.error(
                    f"Skipping partner {partner.display_name} because "
                    "fr_directory_entity_type is not set"
                )
                continue
            if partner.fr_directory_entity_type != "public":
                logger.warning(
                    f"Skipping partner {partner.display_name} because "
                    f"fr_directory_entity_type={partner.fr_directory_entity_type} "
                    "(expected value was 'public')"
                )
                continue
            partner_ids.append(partner.id)
            active_srv_count = partner.fr_chorus_service_count
            logger.info(
                f"This partner has {active_srv_count} active chorus services and "
                f"{partner.fr_directory_line_active_count} active directory lines"
            )
            if active_srv_count:
                service_code2id = {}
                for service in partner.fr_chorus_service_ids:
                    if service.active:
                        service_code2id[service.code] = service.id
                routing_code2dir_line = {}
                for dir_line in partner.fr_directory_line_ids:
                    if (
                        dir_line.state == "active"
                        and dir_line.type == "routing_code"
                        and dir_line.routing_code
                    ):
                        routing_code2dir_line[dir_line.routing_code] = dir_line
                service_id2dir_line = {}
                for service_code, service_id in service_code2id.items():
                    if service_code in routing_code2dir_line:
                        service_id2dir_line[service_id] = routing_code2dir_line[
                            service_code
                        ]
                for child_partner in partner.child_ids.filtered(
                    lambda x: x.fr_chorus_service_id
                ):
                    if not child_partner.fr_chorus_service_id.active:
                        logger.info(
                            f"Contact {child_partner.display_name} "
                            f"ID {child_partner.id} is configured with Chorus Service "
                            f"{child_partner.fr_chorus_service_id.display_name} which "
                            "is inactive. Nothing done on this contact."
                        )
                        continue
                    if child_partner.type != "invoice":
                        logger.warning(
                            f"Contact {child_partner.display_name} "
                            f"ID {child_partner.id} is configured with Chorus Service "
                            f"{child_partner.fr_chorus_service_id.display_name} but "
                            f"it is not an invoicing contact "
                            f"(type={child_partner.type}). Nothing done on this "
                            f"contact."
                        )
                        continue
                    if child_partner.fr_chorus_service_id.id not in service_id2dir_line:
                        logger.error(
                            f"Contact {child_partner.display_name} "
                            f"ID {child_partner.id} is configured with Chorus Service "
                            f"{child_partner.fr_chorus_service_id.display_name} but "
                            f"this Chorus Service Code has no equivalent directory line"
                        )
                        child_partner.message_post(
                            body=Markup(
                                self.env._(
                                    "<strong>Failed</strong> to migrate Chorus "
                                    "Service <strong>%(service)s</strong> to a "
                                    "directory line because there is no active "
                                    "directory line with the same Chorus service code.",
                                    service=child_partner.fr_chorus_service_id.display_name,
                                )
                            )
                        )
                        continue
                    dir_line = service_id2dir_line[
                        child_partner.fr_chorus_service_id.id
                    ]
                    child_partner.write({"default_fr_directory_line_id": dir_line.id})
                    logger.info(
                        f"Contact {child_partner.display_name} ID {child_partner.id} "
                        f"with chorus service code "
                        f"{child_partner.fr_chorus_service_id.code} successfully "
                        f"migrated to default dir line {dir_line.display_name}"
                    )
                    child_partner.message_post(
                        body=Markup(
                            self.env._(
                                "Successful migration from Chorus Service "
                                "<strong>%(service)s</strong> to Default "
                                "Directory line <strong>%(directory_line)s</strong>.",
                                service=child_partner.fr_chorus_service_id.display_name,
                                directory_line=dir_line.display_name,
                            )
                        )
                    )
                    partner_ids.append(child_partner.id)

        logger.info("End of Chorus Pro directory line migration")
        self._migrate_invoice_attachments()
        action = {
            "type": "ir.actions.act_window",
            "name": self.env._("Updated Partners"),
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("id", "in", partner_ids)],
        }
        return action

    def _migrate_invoice_attachments(self):
        logger.info("Start Chorus Pro invoice attachment migration")
        # use sudo() to migrate in all companies
        invoices = (
            self.env["account.move"]
            .sudo()
            .search(
                [
                    ("move_type", "in", ("out_invoice", "out_refund")),
                    ("chorus_attachment_ids", "!=", False),
                ]
            )
        )
        for invoice in invoices:
            invoice_attachment_ids = [
                Command.link(x.id) for x in invoice.chorus_attachment_ids
            ]
            chorus_attachment_ids = [
                Command.unlink(x.id) for x in invoice.chorus_attachment_ids
            ]
            invoice.sudo().write(
                {
                    "invoice_attachment_ids": invoice_attachment_ids,
                    "chorus_attachment_ids": chorus_attachment_ids,
                }
            )
            logger.info(
                f"{len(invoice_attachment_ids)} attachments transfered from "
                f"chorus_attachment_ids to invoice_attachment_ids on "
                f"invoice {invoice.display_name} ID {invoice.id}"
            )
        logger.info("End Chorus Pro invoice attachment migration")
