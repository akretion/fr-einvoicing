# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from markupsafe import Markup
from stdnum.fr.siren import is_valid as siren_is_valid
from stdnum.fr.siret import is_valid as siret_is_valid
from stdnum.vatin import is_valid as vat_is_valid

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS = 30
DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS = 5
SUPERPDP_SANDBOX_SIREN = ("000000001", "000000002")

try:
    from pyfrctc import (
        get_directory_lines_parsed,
        get_directory_siren_parsed,
        get_directory_siret_parsed,
    )
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)


class ResPartner(models.Model):
    _inherit = "res.partner"

    fr_directory_line_ids = fields.One2many(
        "fr.directory.line",
        "partner_id",
        string="Directory Lines",
        readonly=True,
        help="E-invoicing Directory Lines for France",
    )
    fr_directory_line_active_count = fields.Integer(
        compute="_compute_fr_directory_line_active_count",
        string="# of Active Directory Lines",
    )
    fr_directory_name = fields.Char(
        string="Entity Name in Directory",
        help="Name of the legal entity in the eInvoicing directory for France",
        compute="_compute_fr_directory_reset_parent",
        store=True,
        copy=False,
    )
    fr_directory_entity_type = fields.Selection(
        [  # entityType
            ("private_inactive", "Inactive Private VAT Registered"),
            ("private", "Private VAT Registered"),  # PrivateVatRegistered
            ("public", "Public Sector"),  # Public
            ("no", "Not Present"),
        ],
        string="Directory Status",
        compute="_compute_fr_directory_reset_parent",
        store=True,
        copy=False,
        tracking=150,
    )
    fr_directory_closed = fields.Boolean(
        compute="_compute_fr_directory_reset_parent",
        store=True,
        tracking=200,
        string="Entity Closed",
    )  # administrativeStatus = C
    fr_directory_siren = fields.Char(
        string="Query SIREN",
        copy=False,
        readonly=True,
        help="SIREN used to query the directory. "
        "Field used to check that the SIREN hasn't been changed on the partner.",
    )
    fr_directory_siret = fields.Char(
        string="Query SIRET",
        copy=False,
        readonly=True,
        help="SIRET used to query the directory. Field used to check that the "
        "SIRET hasn't been changed on a public sector entity.",
    )
    fr_directory_entity_changed_warning = fields.Html(
        compute="_compute_fr_directory_entity_changed_warning"
    )
    fr_directory_last_sync_date = fields.Date(  # no need for datetime, date is enough.
        string="Directory Last Sync",
        compute="_compute_fr_directory_reset_parent",
        store=True,
        copy=False,
    )
    default_fr_directory_line_id = fields.Many2one(
        "fr.directory.line",
        string="Default Directory Line",
        copy=False,
        domain="[('partner_id', '=', commercial_partner_id), ('state', '=', 'active')]",
    )
    fr_directory_line_show = fields.Boolean(
        compute="_compute_fr_directory_line_show",
        string="Show field Default Directory Line",
    )
    fr_directory_show_warning_missing_siren = fields.Boolean(
        compute="_compute_fr_directory_show_warning_missing_siren"
    )
    fr_directory_show_warning_closed = fields.Boolean(
        related="commercial_partner_id.fr_directory_closed",
        string="Show warning if entity closed",
    )

    @api.depends("type", "parent_id", "fr_directory_entity_type", "fr_directory_closed")
    def _compute_fr_directory_line_show(self):
        for partner in self:
            show = False
            cpartner = partner.commercial_partner_id
            if (
                cpartner.fr_directory_entity_type in ("private", "public")
                and not cpartner.fr_directory_closed
                and (not partner.parent_id or partner.type == "invoice")
            ):
                show = True
            partner.fr_directory_line_show = show

    @api.depends("fr_directory_line_ids")
    def _compute_fr_directory_line_active_count(self):
        rg_res = self.env["fr.directory.line"].read_group(
            [("partner_id", "in", self.ids), ("state", "=", "active")],
            ["partner_id"],
            ["partner_id"],
        )
        mapped_data = {x["partner_id"][0]: x["partner_id_count"] for x in rg_res}
        for partner in self:
            partner.fr_directory_line_active_count = mapped_data.get(partner.id, 0)

    @api.depends(
        "fr_directory_siren",
        "siren",
        "fr_directory_siret",
        "fr_directory_entity_type",
        "siret",
    )
    def _compute_fr_directory_entity_changed_warning(self):
        for partner in self:
            warn_msg = None
            if (
                partner.fr_directory_entity_type == "public"
                and partner.fr_directory_siret
                and partner.fr_directory_siret != partner._get_siret()
            ):
                warn_msg = Markup(
                    _(
                        "<strong>SIRET has been changed</strong> on this public-sector "
                        "partner. SIRET should never be changed on public sector "
                        "partners: create a new partner instead."
                    )
                )
            elif (
                partner.fr_directory_siren
                and partner.fr_directory_siren != partner._get_siren()
            ):
                warn_msg = Markup(
                    _(
                        "<strong>SIREN has been changed</strong> on this partner ! "
                        "You should create a new partner instead."
                    )
                )
            partner.fr_directory_entity_changed_warning = warn_msg

    @api.depends("vat", "siren", "is_company", "parent_id", "is_france_country")
    def _compute_fr_directory_show_warning_missing_siren(self):
        for partner in self:
            show_warning = False
            if (
                partner.is_company
                and not partner.parent_id
                and (not partner.vat or partner.vat == "/")
                and not partner.siren
                and partner.is_france_country
            ):
                show_warning = True
            partner.fr_directory_show_warning_missing_siren = show_warning

    @api.depends("parent_id")
    def _compute_fr_directory_reset_parent(self):
        for partner in self:
            if partner.parent_id:
                partner.fr_directory_entity_type = False
                partner.fr_directory_closed = False
                partner.fr_directory_name = False
                partner.fr_directory_last_sync_date = False

    @api.constrains("fr_directory_entity_type", "fr_directory_last_sync_date")
    def _fr_directory_check(self):
        for partner in self:
            if (
                partner.fr_directory_entity_type
                and not partner.fr_directory_last_sync_date
            ):
                raise ValidationError(
                    _(
                        "Partner '%s' has a Directory Status but no "
                        "Directory Last Sync Date.",
                        partner.display_name,
                    )
                )

    def fr_directory_sync_button(self):
        self.ensure_one()
        assert not self.parent_id
        company = self.company_id or self.env.company
        origin = _("Partner Button")
        action = self._fr_directory_sync_logs(company, origin)
        return action

    def _fr_directory_sync_logs(self, company, origin):
        self.ensure_one()
        assert not self.parent_id
        assert company
        assert origin
        log_obj = self.env["fr.einvoicing.log"]
        result = {
            "log_type": "directory_single",
            "log_origin": origin,
            "company_id": False,
            "logs": [],
            "new_count": 0,
            "updated_count": 0,
        }
        session = company._fr_ctc_get_session()
        action = self._fr_directory_sync(session, result)
        self._fr_directory_chatter_log(origin, result)
        log_obj._create_log(result)
        return action

    def _fr_directory_chatter_log(self, origin, result):
        self.ensure_one()
        msg_list = [_("Directory sync. Origin: %s.", origin)]
        if result["new_count"]:
            msg_list.append(_("%s directory lines created.", result["new_count"]))
        if result["updated_count"]:
            msg_list.append(_("%s directory lines updated.", result["updated_count"]))
        if not result["new_count"] and not result["updated_count"]:
            msg_list.append(_("No changes."))
        self.message_post(body=" ".join(msg_list))

    @api.model
    def _fr_directory_sync_cron(self):
        logger.info("Start FR eInvoicing directory sync cron")
        log_obj = self.env["fr.einvoicing.log"]
        result = {
            "log_type": "directory_all",
            "log_origin": "Cron",
            "company_id": False,
            "logs": [],
            "new_count": 0,
            "updated_count": 0,
        }
        today = fields.Date.context_today(self)
        company = self.company_id or self.env.company
        try:
            session = company._fr_ctc_get_session()
        except Exception as e:
            log_obj._error_log(result, str(e))
            log_obj._create_log(result)
            return
        days_active, days_inactive = self._fr_directory_sync_if_old_get_days(result)
        log_obj._info_log(result, "Start of the directory sync cron.")
        log_obj._info_log(
            result,
            f"Partners with active directory lines with last update date older "
            f"than {days_active} days will be updated.",
        )
        log_obj._info_log(
            result,
            f"Partners without active directory lines with last update date older "
            f"than {days_inactive} days will be updated.",
        )
        active_domain = [
            ("parent_id", "=", False),
            ("fr_directory_entity_type", "in", ("public", "private")),
            ("fr_directory_closed", "=", False),
            "|",
            ("fr_directory_last_sync_date", "<", today - timedelta(days_active)),
            ("fr_directory_last_sync_date", "=", False),
        ]
        self._fr_directory_cron_sync_partners(
            active_domain, "with active directory lines", session, result
        )
        inactive_domain = [
            ("parent_id", "=", False),
            ("fr_directory_entity_type", "=", "private_inactive"),
            ("fr_directory_closed", "=", False),
            "|",
            ("fr_directory_last_sync_date", "<", today - timedelta(days_inactive)),
            ("fr_directory_last_sync_date", "=", False),
        ]

        self._fr_directory_cron_sync_partners(
            inactive_domain, "without active directory lines", session, result
        )
        fr_country_codes = self.env["res.company"]._get_france_country_codes()
        fr_domain = [
            ("parent_id", "=", False),
            ("fr_directory_entity_type", "=", False),
            ("country_id.code", "in", fr_country_codes),
            "|",
            ("vat", "not in", ("/", False)),
            ("siren", "!=", False),
        ]
        self._fr_directory_cron_sync_partners(
            fr_domain, "from France with SIREN or VAT number", session, result
        )

        log_obj._info_log(result, "End of the directory sync cron.")
        log_obj._create_log(result)
        logger.info("End of FR eInvoicing directory sync cron")

    @api.model
    def _fr_directory_cron_sync_partners(self, domain, partner_type, session, result):
        log_obj = self.env["fr.einvoicing.log"]
        partners = self.search(domain)
        log_obj._info_log(
            result, f"Start to update {len(partners)} partners {partner_type}"
        )
        for partner in partners:
            try:
                partner._fr_directory_sync(session, result)
            except Exception as e:
                msg = (
                    f"Directory sync for partner {partner.display_name} "
                    f"ID {partner.id} failed. Error: {str(e)}"
                )
                log_obj._warning_log(result, msg)

    @api.model
    def _fr_directory_sync_if_old_get_days(self, result):
        log_obj = self.env["fr.einvoicing.log"]
        prefix = "fr_directory"
        days_config = [
            {
                "key": f"{prefix}.update_partner_if_older_than_days",
                "default": DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS,
            },
            {
                "key": f"{prefix}.update_private_inactive_partner_if_older_than_days",
                "default": DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS,
            },
        ]
        res = []
        for day_config in days_config:
            key = day_config["key"]
            days_str = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key, default=str(day_config["default"]))
            )
            try:
                days = int(days_str)
                msg = f"{key} = {days} days"
            except Exception:
                days = day_config["default"]
                msg = (
                    f"Failed to convert ir.config_parameter {key} ({days_str}) "
                    f"to integer. Using default value {days} days"
                )
                log_obj._warning_log(result, msg)
            if days < 0:
                days = day_config["default"]
                msg = (
                    f"ir.config_parameter {key} ({days}) is negative. "
                    f"Using default value: {days} days"
                )
                log_obj._warning_log(result, msg)
            res.append(days)
        return res

    def _fr_directory_sync(self, session, result):  # noqa: C901
        self.ensure_one()
        assert not self.parent_id
        log_obj = self.env["fr.einvoicing.log"]
        dline_obj = self.env["fr.directory.line"]
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",  # changed to warning/danger below if needed
                "title": _("Directory Synced"),
                "next": {
                    "type": "ir.actions.client",
                    # Due to https://github.com/odoo/odoo/issues/256020 on odoo 16
                    # we can't use soft_reload, we have to use "reload"
                    # which is not as good because we go back to the first tab
                    "tag": "reload",
                },
            },
        }
        siren = self._get_siren(raise_if_none=True)
        err_msg = self._fr_directory_siren_change_error(siren=siren)
        if err_msg:
            raise UserError(err_msg)
        if siren in SUPERPDP_SANDBOX_SIREN:
            msg = (
                f"SUPER PDP demo partner {self.display_name} SIREN {siren} "
                "is not in the directory"
            )
            log_obj._info_log(result, msg)
            return
        try:
            siren_parsed = get_directory_siren_parsed(session, siren)
        except Exception as err:
            raise UserError(
                _(
                    "Failed to query directory with SIREN '%(siren)s'. Error: %(err)s",
                    siren=siren,
                    err=err,
                )
            ) from err
        logger.debug(f"Result of get_directory_siren_parsed: {siren_parsed}")
        vals = {}
        for key, value in siren_parsed.items():
            vals[f"fr_directory_{key}"] = value
        vals["fr_directory_last_sync_date"] = fields.Date.context_today(self)
        siret_parsed = {}
        if not vals.get("fr_directory_closed"):
            if vals["fr_directory_entity_type"] == "public":
                siret = self._get_siret(raise_if_none=False)
                if not siret:
                    raise UserError(
                        _(
                            "SIRET is not set on partner '%(partner)s', "
                            "which is a public entity. Public entites are "
                            "identified by SIRET (SIREN is not enough for "
                            "a public entity).",
                            partner=self.display_name,
                        )
                    )
                err_msg = self._fr_directory_siret_change_error(siret=siret)
                if err_msg:
                    raise UserError(err_msg)
                siren_or_siret = siret
                try:
                    siret_parsed = get_directory_siret_parsed(session, siret)
                except Exception as err:
                    raise UserError(
                        _(
                            "Failed to query directory with SIRET '%(siret)s'. "
                            "Error: %(err)s",
                            siret=siret,
                            err=err,
                        )
                    ) from err
                vals["fr_directory_siret"] = siret
                logger.debug(f"Result of get_directory_siret_parsed: {siret_parsed}")
                if siret_parsed.get("name"):
                    vals["fr_directory_name"] = siret_parsed["name"]
                vals["fr_directory_closed"] = siret_parsed["closed"]
            elif vals["fr_directory_entity_type"] == "private":
                siren_or_siret = siren
        self.write(vals)
        if vals.get("fr_directory_closed"):
            msg = (
                f"Partner {self.display_name} ID {self.id} is marked as closed "
                "in FR directory. Disabling all its directory lines."
            )
            log_obj._warning_log(result, msg)
            self.fr_directory_line_ids.filtered(lambda x: x.state != "disabled").write(
                {"state": "disabled"}
            )
            action["params"].update(
                {
                    "type": "danger",
                    "sticky": True,
                    "message": _(
                        "Partner '%(partner)s' SIREN %(siren)s is marked as closed "
                        "in the directory.",
                        partner=self.display_name,
                        siren=siren,
                    ),
                }
            )
            return action
        if vals["fr_directory_entity_type"] == "no":
            msg = f"Partner {self.display_name} SIREN {siren} is not in the directory."
            log_obj._info_log(result, msg)
            action["params"].update(
                {
                    "type": "warning",
                    "message": _(
                        "Partner '%(partner)s' SIREN %(siren)s is not in "
                        "the directory.",
                        partner=self.display_name,
                        siren=siren,
                    ),
                }
            )
            return action
        assert siren_or_siret
        try:
            api_dir_lines_dict = get_directory_lines_parsed(
                session, siren_or_siret, siret_parsed=siret_parsed
            )
        except Exception as err:
            raise UserError(
                _(
                    "Failed to query directory with SIREN or SIRET "
                    "'%(siren_or_siret)s'. Error: %(err)s",
                    siren_or_siret=siren_or_siret,
                    err=err,
                )
            ) from err
        msg = (
            f"{len(api_dir_lines_dict)} directory lines retreived by API for "
            f"partner {self.display_name} ID {self.id}"
        )
        log_obj._info_log(result, msg)
        # Compare with existing lines: create/update/archive
        existing_dir_lines_sr = dline_obj.with_context(active_test=False).search_read(
            [("partner_id", "=", self.id)],
            ["identifier", "state", "type", "routing_code_name", "commitment_required"],
        )
        existing_identifier2vals = {
            line["identifier"]: line for line in existing_dir_lines_sr
        }
        to_archive_line_ids = {line["id"] for line in existing_dir_lines_sr}
        to_create_vals_list = []
        diff_fields = ["state", "routing_code_name", "commitment_required"]
        msgs = []
        updated_line_count = 0
        for identifier, dir_line_vals in api_dir_lines_dict.items():
            if identifier in existing_identifier2vals:
                dline_id = existing_identifier2vals[identifier]["id"]
                to_archive_line_ids.remove(dline_id)
                # fields_to_check
                wvals = {}
                for dfield in diff_fields:
                    if (
                        dir_line_vals[dfield]
                        != existing_identifier2vals[identifier][dfield]
                    ):
                        wvals[dfield] = dir_line_vals[dfield]
                if wvals:
                    dir_line = dline_obj.browse(dline_id)
                    logger.debug(
                        f"Updating directory line {identifier} ID {dline_id} "
                        f"with vals={wvals}"
                    )
                    dir_line.sudo().write(wvals)
                    updated_line_count += 1
            else:
                cvals = dict(dir_line_vals, partner_id=self.id, identifier=identifier)
                to_create_vals_list.append(cvals)

        if to_create_vals_list:
            dline_obj.sudo().create(to_create_vals_list)
            msgs.append(_("%d directory lines created.", len(to_create_vals_list)))
            result["new_count"] += len(to_create_vals_list)
        if updated_line_count:
            msgs.append(_("%d directory lines updated.", updated_line_count))
            result["updated_count"] += updated_line_count
        if to_archive_line_ids:
            to_archive_lines = dline_obj.browse(list(to_archive_line_ids))
            to_archive_lines.sudo().write({"state": "disabled"})
            msgs.append(_("%d directory lines archived.", len(to_archive_line_ids)))
            result["updated_count"] += len(to_archive_line_ids)
        if not self.fr_directory_line_ids.filtered(lambda x: x.state == "active"):
            if self.fr_directory_entity_type == "private":
                self.write({"fr_directory_entity_type": "private_inactive"})
            elif self.fr_directory_entity_type == "public":
                raise UserError(
                    _(
                        "Public sector partner '%s' doesn't have any active "
                        "directory line. This should never happen.",
                        self.display_name,
                    )
                )
        message = msgs and " ".join(msgs) or _("Directory line(s) unchanged.")
        log_obj._info_log(
            result,
            f"Directory lines of partner {self.display_name} ID {self.id}: "
            f"{len(to_create_vals_list)} created, {updated_line_count} "
            f"updated and {len(to_archive_line_ids)} archived.",
        )
        action["params"]["message"] = message
        return action

    def _fr_directory_confirm_common_checks(self):
        """This methods returns an error message as string when there is a problem.
        It returns None when everything is OK.
        It is used both at sale.order confirmation and invoice confirmation
        """
        self.ensure_one()
        assert self.fr_directory_entity_type in ("public", "private")
        if self.fr_directory_closed:
            err_msg = _(
                "Partner '%s' is marked as closed in the directory.", self.display_name
            )
            return err_msg
        if self.fr_directory_entity_type == "public":
            return self._fr_directory_siret_change_error()
        elif self.fr_directory_entity_type == "private":
            return self._fr_directory_siren_change_error()

    def _fr_directory_siret_change_error(self, siret=None):
        """This method is designed to avoid duplicate error messages
        between _fr_directory_common_partner_check() and _fr_directory_sync()"""
        self.ensure_one()
        if siret is None:
            siret = self._get_siret(raise_if_none=False)
        if self.fr_directory_siret and siret != self.fr_directory_siret:
            err_msg = _(
                "SIRET currently configured on the public sector partner "
                "'%(partner)s' is %(siret)s, which is different from "
                "SIRET previously used to query the directory "
                "(%(fr_directory_siret)s). SIRET should not be changed "
                "on public-sector partners.",
                partner=self.display_name,
                siret=siret or _("empty"),
                fr_directory_siret=self.fr_directory_siret,
            )
            return err_msg
        return None

    def _fr_directory_siren_change_error(self, siren=None):
        """This method is designed to avoid duplicate error messages
        between _fr_directory_common_partner_check() and _fr_directory_sync()"""
        self.ensure_one()
        if siren is None:
            siren = self._get_siren(raise_if_none=True)
        if self.fr_directory_siren and siren != self.fr_directory_siren:
            err_msg = _(
                "SIREN currently configured on partner '%(partner)s' "
                "is %(siren)s, which is different from the SIREN previously "
                "used to query the directory (%(fr_directory_siren)s). "
                "It means that a user changed the SIREN on this partner. "
                "SIREN should never be changed on "
                "partners: a new partner should be created instead.",
                partner=self.display_name,
                siren=siren or _("empty"),
                fr_directory_siren=self.fr_directory_siren,
            )
            return err_msg
        return None

    def _fr_directory_check_siren_siret_vat(self):  # noqa: C901
        """Called by method of res.config.settings
        Returns True if the partner has been modified.
        Return False if no change occured or it is only the removal of spaces
        This method is pretty complex: the aim is to cleanup all bad data
        that could have accumulated over the years despite the constraints
        and remove spaces (if not done right during upgrades)
        """
        self.ensure_one()
        ini_siren = self.siren
        siren = ini_siren and "".join(x for x in ini_siren if not x.isspace()) or False
        ini_nic = self.nic
        nic = ini_nic and "".join(x for x in ini_nic if not x.isspace()) or False
        ini_vat = self.vat
        ini_siret = self.siret
        siret = ini_siret and "".join(x for x in ini_siret if not x.isspace()) or False
        if ini_siren in ("000000001", "000000002") or ini_vat in (
            "FR42000000001",
            "FR43000000002",
        ):
            logger.info(
                f"Partner {self.display_name} is a SUPERPDP demo "
                f"partner. No change."
            )
            return False
        vals = {}
        msgs = []
        if ini_vat and ini_vat != "/":
            vat = "".join(x for x in ini_vat if not x.isspace()).upper() or False
            if not vat:
                vals["vat"] = False
            else:
                if vat == "/" or vat_is_valid(vat):
                    if ini_vat != vat:
                        vals["vat"] = vat
                        logger.info(
                            f"Spaces removed in VAT {vat} on partner "
                            f"{self.display_name}"
                        )
                else:
                    siren_from_vat = vat[4:]
                    if (
                        vat.startswith("FR")
                        and siren_is_valid(siren_from_vat)
                        and not siren
                    ):
                        vals.update({"siren": siren_from_vat, "vat": False})
                        msgs.append(
                            _(
                                "VAT <strong>%(vat)s</strong> is not valid "
                                "but it contains a valid SIREN "
                                "<strong>%(siren)s</strong>. VAT has been removed "
                                "and SIREN has been set.",
                                vat=vat,
                                siren=siren_from_vat,
                            )
                        )
                        vat = False
                        siren = siren_from_vat
                    else:
                        vals["vat"] = False
                        msgs.append(
                            _(
                                "VAT <strong>%s</strong> is not valid: "
                                "it has been <strong>removed</strong>.",
                                vat,
                            )
                        )
                        vat = False
        if ini_siren:
            if not siren:
                if not siret:
                    vals.update({"siren": False, "nic": False})
                    siren = nic = False
            else:
                if not siren_is_valid(siren):
                    vals.update({"siren": False, "nic": False})
                    msgs.append(
                        _(
                            "SIREN <strong>%s</strong> is invalid: "
                            "it has been removed.",
                            siren,
                        )
                    )
                    siren = nic = False
                elif (
                    ini_vat
                    and ini_vat != "/"
                    and vat
                    and vat != "/"
                    and vat_is_valid(vat)
                ):
                    if vat.startswith("FR"):
                        if not vat.endswith(siren):
                            vals.update({"siren": False, "nic": False})
                            # I decided to reset SIREN rather than VAT.
                            # Anyway, we can't know which of the 2 information
                            # is right. If the SIREN was right and the VAT was
                            # wrong, the user can get the removed SIREN
                            # in the chatter and update the partner.
                            msgs.append(
                                _(
                                    "SIREN <strong>%(siren)s</strong> is not "
                                    "consistent with VAT <strong>%(vat)s</strong>: "
                                    "<strong>SIREN has been removed</strong>.",
                                    siren=siren,
                                    vat=vat,
                                )
                            )
                            siren = nic = False
                    else:
                        vals["vat"] = False
                        msgs.append(
                            _(
                                "The entity has a valid SIREN (%(siren)s)"
                                "but its VAT number (%(vat)s) "
                                "doesn't start with 'FR', so it's VAT "
                                "number has been removed.",
                                siren=siren,
                                vat=vat,
                            )
                        )
                        vat = False

            if siren and siren_is_valid(siren) and ini_siren != siren:
                vals["siren"] = siren
                logger.info(
                    f"Spaces removed in SIREN {siren} on partner {self.display_name}"
                )

            if siren and ini_nic and "nic" not in vals:
                ini_siret = self.siret
                siret = (
                    ini_siret
                    and "".join(x for x in ini_siret if not x.isspace())
                    or False
                )
                if nic:
                    siret_from_siren_nic = siren + nic
                    if not siret_is_valid(siret_from_siren_nic):
                        vals["nic"] = False
                        msgs.append(
                            _(
                                "NIC <strong>%s</strong> has been "
                                "<strong>removed</strong>.",
                                self.nic,
                            )
                        )
                        nic = False
                    elif siret != siret_from_siren_nic:
                        # This will re-build proper siret
                        vals["nic"] = nic
                        msgs.append(
                            _(
                                "SIRET (%(ini_siret)s) was inconsistent with "
                                "SIREN (%(siren)s) and NIC (%(nic)s). "
                                "SIRET has been re-written to "
                                "<strong>%(new_siret)s</strong>.",
                                ini_siret=ini_siret,
                                siren=siren,
                                nic=nic,
                                new_siret=siret_from_siren_nic,
                            )
                        )
                    elif ini_nic != nic:
                        vals["nic"] = nic
                else:
                    vals["nic"] = False
        # now we go from siret to siren/nic
        # but we only have to handle the case where siren and nic
        # are not set (case when you install l10n_fr_siret after
        # go-live and at the time where there was no post-install scripts
        # CAUTION with siret = '792377731*****'
        if ini_siret and "siren" not in vals and "nic" not in vals:
            if not siret:
                vals.update({"siren": False, "nic": False})
            else:
                if siret_is_valid(siret):
                    siren_from_siret = siret[:9]
                    nic_from_siret = siret[9:]
                    if siren and siren != siren_from_siret:
                        # we don't know what is the right value between siren
                        # and siren extracted from siret, so reset both
                        vals.update(
                            {"siren": False, "nic": False}
                        )  # it will update siret
                        msgs.append(
                            _(
                                "SIRET (%(siret)s) was inconsistent with SIREN "
                                "(%(siren)s) and NIC (%(nic)s). "
                                "The 3 fields have been emptied.",
                                siret=siret,
                                siren=siren,
                                nic=nic,
                            )
                        )
                    elif nic and nic != nic_from_siret:
                        vals["nic"] = False
                        msgs.append(
                            _(
                                "SIRET (%(siret)s) was inconsistent with NIC "
                                "(%(nic)s). NIC has been emptied and "
                                "SIRET has been updated.",
                                siret=siret,
                                nic=nic,
                            )
                        )
                    elif not siren and not nic:
                        vals.update({"siren": siren_from_siret, "nic": nic_from_siret})
                        msgs.append(
                            _(
                                "SIREN (%(siren)s) and NIC (%(nic)s) have been "
                                "set from SIRET (%(siret)s).",
                                siren=siren_from_siret,
                                nic=nic_from_siret,
                                siret=siret,
                            )
                        )
                    if (
                        ini_siren
                        and siren == siren_from_siret
                        and nic == nic_from_siret
                        and ini_siret != siret
                    ):
                        # just to regen siret without spaces
                        vals.update({"siren": siren, "nic": nic})
                        logger.info(
                            f"Spaces removed in SIRET {ini_siret} "
                            f"on partner {self.display_name}"
                        )
                else:
                    siren_from_siret = siret[:9]
                    if siren_from_siret and siren_is_valid(siren_from_siret):
                        vals.update({"siren": siren_from_siret, "nic": False})
                        msgs.append(
                            _(
                                "Set SIREN to %(siren)s from SIRET %(siret)s.",
                                siren=siren_from_siret,
                                siret=siret,
                            )
                        )
                    else:
                        vals.update({"siren": False, "nic": False})
                        msgs.append(
                            _(
                                "SIRET %(siret)s is invalid and SIREN extracted from "
                                "it is invalid too. SIRET has been emptied.",
                                siret=siret,
                            )
                        )
        if vals:
            logger.info(f"Writing {vals} on partner {self.display_name} ID {self.id}")
            self.write(vals)
            for msg in msgs:
                self.message_post(body=Markup(msg))
        return bool(msgs)

    def _fr_directory_should_sync_upon_confirmation(self):
        self.ensure_one()
        assert not self.parent_id
        if (
            not self.fr_directory_entity_type
            and self.is_company
            and self.is_france_country
            and self._get_siren()
        ) or self.fr_directory_entity_type == "private_inactive":
            return True
        return False
