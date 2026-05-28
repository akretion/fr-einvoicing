# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from pprint import pprint
from odoo import api, fields, models
from odoo.exceptions import UserError
from datetime import timedelta
import logging
logger = logging.getLogger(__name__)

DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS = 30
DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS = 5

try:
    from pyfrctc import get_directory_lines_parsed, get_directory_siren_parsed, get_directory_siret_parsed
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    fr_directory_line_ids = fields.One2many(
        "fr.directory.line", "partner_id", string="Directory Lines", readonly=True,
        help="E-invoicing Directory Lines for France")
    fr_directory_line_active_count = fields.Integer(
        compute="_compute_fr_directory_line_active_count",
        string="# of Active Directory Lines")
    fr_directory_name = fields.Char(
        string="Entity Name in Directory",
        help="Name of the legal entity in the eInvoicing directory for France",
        compute="_compute_fr_directory_reset_parent", store=True, copy=False,
        )
    fr_directory_entity_type = fields.Selection([  # entityType
        ('private_inactive', 'Inactive Private VAT Registered'),
        ('private', 'Private VAT Registered'),  # PrivateVatRegistered
        ('public', 'Public Sector'),  # Public
        ('no', 'Not Present'),
        ], string="Directory Status",
        compute="_compute_fr_directory_reset_parent", store=True,
        copy=False, tracking=150)
    fr_directory_closed = fields.Boolean(
        compute="_compute_fr_directory_reset_parent", store=True,
        tracking=200, string="Entity Closed")  # administrativeStatus = C
    fr_directory_siren = fields.Char(
        string="Query SIREN",
        copy=False, readonly=True,
        help="SIREN used to query the directory. "
        "Field used to check that the SIREN hasn't been changed on the partner.")
    fr_directory_siret = fields.Char(string="Query SIRET", copy=False, readonly=True, help="SIRET used to query the directory. Field used to check that the SIRET hasn't been changed on a public sector entity.")
    fr_directory_entity_changed_warning = fields.Boolean(compute="_compute_fr_directory_entity_changed_warning")
    fr_directory_update_date = fields.Date(  # Do we need datetime ? date is enough...
        string="Directory Last Update",
        compute="_compute_fr_directory_reset_parent", store=True, copy=False)
    default_fr_directory_line_id = fields.Many2one(
        "fr.directory.line", string="Default Directory Line", copy=False,
        domain="[('partner_id', '=', commercial_partner_id), ('state', '=', 'active')]")
    fr_directory_line_show = fields.Boolean(
        compute="_compute_fr_directory_line_show",
        string="Show field Default Directory Line")
    fr_directory_show_warning_missing_siren = fields.Boolean(compute="_compute_fr_directory_show_warning_missing_siren")

    @api.depends('type', 'parent_id', 'fr_directory_entity_type', 'fr_directory_closed')
    def _compute_fr_directory_line_show(self):
        for partner in self:
            show = False
            cpartner = partner.commercial_partner_id
            if (
                    cpartner.fr_directory_entity_type in ('private', 'public') and
                    not cpartner.fr_directory_closed and
                    (not partner.parent_id or partner.type == 'invoice')):
                show = True
            partner.fr_directory_line_show = show

    @api.depends('fr_directory_line_ids')
    def _compute_fr_directory_line_active_count(self):
        rg_res = self.env["fr.directory.line"]._read_group(
            [("partner_id", "in", self.ids), ('state', '=', 'active')],
            groupby=["partner_id"], aggregates=['__count']
        )
        mapped_data = {partner.id: line_count for (partner, line_count) in rg_res}
        for partner in self:
            partner.fr_directory_line_active_count = mapped_data.get(partner.id, 0)

    # TODO tune for public entity with siret changes
    @api.depends('fr_directory_siren', 'siren')
    def _compute_fr_directory_entity_changed_warning(self):
        for partner in self:
            warning = False
            if partner.fr_directory_siren and partner.fr_directory_siren != partner._get_siren():
                warning = True
            partner.fr_directory_entity_changed_warning = warning

    @api.depends('vat', 'siren', 'is_company', 'parent_id', 'is_france_country')
    def _compute_fr_directory_show_warning_missing_siren(self):
        for partner in self:
            show_warning = False
            if partner.is_company and not partner.parent_id and not partner.vat and not partner.siren and partner.is_france_country:
                show_warning = True
            partner.fr_directory_show_warning_missing_siren = show_warning

    @api.depends('parent_id')
    def _compute_fr_directory_reset_parent(self):
        for partner in self:
            if partner.parent_id:
                partner.fr_directory_entity_type = False
                partner.fr_directory_closed = False
                partner.fr_directory_name = False
                partner.fr_directory_update_date = False

    def fr_directory_update_button(self):
        self.ensure_one()
        assert not self.parent_id
        company = self.company_id or self.env.company
        origin = self.env._('Partner Button')
        action = self._fr_directory_update_logs(company, origin)
        return action

    def _fr_directory_update_logs(self, company, origin):
        self.ensure_one()
        assert not self.parent_id
        assert company
        assert origin
        log_obj = self.env['fr.einvoicing.log']
        result = {
            'log_type': 'directory_single',
            'log_origin': origin,
            'company_id': False,
            'logs': [],
            'new_count': 0,
            'updated_count': 0,
            }
        session = company._fr_ctc_get_session()
        action = self._fr_directory_update(session, result)
        self._fr_directory_chatter_log(origin, result)
        log_obj._create_log(result)
        return action

    def _fr_directory_chatter_log(self, origin, result):
        self.ensure_one()
        msg_list = [self.env._("Get/update of directory lines. Origin: %s.", origin)]
        if result['new_count']:
            msg_list.append(self.env._("%s directory lines created.", result['new_count']))
        if result['updated_count']:
            msg_list.append(self.env._("%s directory lines updated.", result['updated_count']))
        if not result['new_count'] and not result['updated_count']:
            msg_list.append(self.env._("No changes."))
        self.message_post(body=" ".join(msg_list))

    @api.model
    def _fr_directory_update_cron(self):
        logger.info('Start FR eInvoicing directory update cron')
        log_obj = self.env['fr.einvoicing.log']
        result = {
            'log_type': 'directory_all',
            'log_origin': 'Cron',
            'company_id': False,
            'logs': [],
            'new_count': 0,
            'updated_count': 0,
            }
        today = fields.Date.context_today(self)
        company = self.company_id or self.env.company
        try:
            session = company._fr_ctc_get_session()
        except Exception as e:
            log_obj._error_log(result, str(e))
            log_obj._create_log(result)
            return
        days_active, days_inactive = self._fr_directory_update_if_old_get_days(result)
        log_obj._info_log(result, f'Start of the directory update cron.')
        log_obj._info_log(result, f'Partners with active directory lines with last update date older than {days_active} days will be updated.')
        log_obj._info_log(result, f'Partners without active directory lines with last update date older than {days_inactive} days will be updated.')
        active_domain = [
            ('parent_id', '=', False),
            ('fr_directory_entity_type', 'in', ('public', 'private')),
            ('fr_directory_closed', '=', False),
            '|', ('fr_directory_update_date', '<', today - timedelta(days_active)), ('fr_directory_update_date', '=', False),
            ]
        self._fr_directory_cron_update_partners(active_domain, "with active directory lines", session, result)
        inactive_domain = [
            ('parent_id', '=', False),
            ('fr_directory_entity_type', '=', 'private_inactive'),
            ('fr_directory_closed', '=', False),
            '|', ('fr_directory_update_date', '<', today - timedelta(days_inactive)), ('fr_directory_update_date', '=', False),
            ]

        self._fr_directory_cron_update_partners(inactive_domain, "without active directory lines", session, result)
        fr_country_codes = self.env["res.company"]._get_france_country_codes()
        fr_domain = [
            ('parent_id', '=', False),
            ('fr_directory_entity_type', '=', False),
            ('country_id', 'in', fr_country_codes),
            '|', ('vat', '!=', False), ('siren', '!=', False),
            ]
        self._fr_directory_cron_update_partners(fr_domain, "from France with SIREN or VAT number", session, result)

        log_obj._info_log(result, 'End of the directory update cron.')
        log_obj._create_log(result)
        logger.info('End of FR eInvoicing directory update cron')

    @api.model
    def _fr_directory_cron_update_partners(self, domain, partner_type, session, result):
        log_obj = self.env['fr.einvoicing.log']
        partners = self.search(domain)
        log_obj._info_log(result, f"Start to update {len(partners)} partners {partner_type}")
        for partner in partners:
            try:
                partner._fr_directory_update(session, result)
            except Exception as e:
                msg = f"Directory update for partner {partner.display_name} ID {partner.id} failed. Error: {str(e)}"
                log_obj._warning_log(result, msg)

    @api.model
    def _fr_directory_update_if_old_get_days(self, result):
        log_obj = self.env['fr.einvoicing.log']
        days_config = [
                {'key': 'fr_directory.update_partner_if_older_than_days',
                 'default': DEFAULT_UPDATE_PARTNER_IF_OLDER_THAN_DAYS,
                 },
                {'key': 'fr_directory.update_private_inactive_partner_if_older_than_days',
                 'default': DEFAULT_UPDATE_PRIVATE_INACTIVE_PARTNER_IF_OLDER_THAN_DAYS,
                 }]
        res = []
        for day_config in days_config:
            key = day_config['key']
            days_str = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key, default=str(day_config['default']))
            )
            try:
                days = int(days_str)
                msg = f"{key} = {days} days"
            except Exception:
                days = day_config['default']
                msg = f"Failed to convert ir.config_parameter {key} ({days_str}) to integer. Using default value {days} days"
                log_obj._warning_log(result, msg)
            res.append(days)
        return res

    def _fr_directory_update_if_old(self, company, origin):
        self.ensure_one()
        assert not self.parent_id
        assert self.fr_directory_entity_type in ('public', 'private')
        log_obj = self.env['fr.einvoicing.log']
        result = {
            'log_type': 'directory_single',
            'log_origin': origin,
            'company_id': False,
            'logs': [],
            'new_count': 0,
            'updated_count': 0,
            }

        update = True
        if self.fr_directory_update_date:
            days, _ = self._fr_directory_update_if_old_get_days(result)
            today = fields.Date.context_today(self)
            if self.fr_directory_update_date + timedelta(days) < today:
                msg = f'Updating directory lines for partner {self.display_name} ID {self.id} because fr_directory_update_date {fields.Date.to_string(self.fr_directory_update_date)} is older than {days} days'
                log_obj._info_log(result, msg)
            else:
                update = False
                logger.info(f'NOT updating directory lines for partner {self.display_name} ID {self.id} because fr_directory_update_date {fields.Date.to_string(self.fr_directory_update_date)} is less than {days} days old.')
        else:
            msg = f'Updating directory lines for partner {self.display_name} ID {self.id} because fr_directory_update_date is null'
            log_obj._info_log(result, msg)
        if update:
            session = company._fr_ctc_get_session()
            self._fr_directory_update(session, result)
            self._fr_directory_chatter_log(origin, result)
            log_obj._create_log(result)

    def _fr_directory_update(self, session, result):
        self.ensure_one()
        assert not self.parent_id
        log_obj = self.env['fr.einvoicing.log']
        dline_obj = self.env['fr.directory.line']
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',  # changed to warning/danger below if needed
                'title': self.env._("Directory Updated"),
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                    },
                },
            }
        siren = self._get_siren(raise_if_none=True)
        if self.fr_directory_siren and self.fr_directory_siren != siren:
            raise UserError(self.env._("SIREN currently configured on partner '%(partner)s' is %(siren)s, which is different from the SIREN previously used to query the directory (%(fr_directory_siren)s). It means that a user changed the SIREN on this partner. This is a big mistake: SIREN should never be changed on partners (a new partner should be created instead)."), partner=self.display_name, siren=siren, fr_directory_siren=self.fr_directory_siren)
        try:
            siren_parsed = get_directory_siren_parsed(session, siren)
        except Exception as e:
            raise UserError(self.env._("Failed to query directory with SIREN '%(siren)s'. Error: %(err)s", siren=siren, err=e))
        logger.debug(f"Result of get_directory_siren_parsed: {siren_parsed}")
        vals = {}
        for key, value in siren_parsed.items():
            vals[f"fr_directory_{key}"] = value
        vals["fr_directory_update_date"] = fields.Date.context_today(self)
        siret_parsed = {}
        if not vals.get('fr_directory_closed'):
            if vals['fr_directory_entity_type'] == "public":
                siret = self._get_siret(raise_if_none=False)
                if not siret:
                    raise UserError(self.env._("SIRET is not set on partner '%(partner)s', which is a public entity. Public entites are identified by SIRET (SIREN is not enough for a public entity).", partner=self.display_name))
                if self.fr_directory_siret and siret != self.fr_directory_siret:
                    raise UserError(self.env._("SIRET currently configured on the public sector partner '%(partner)s' is %(siret)s, which is different from SIRET previously used to query the directory (%(fr_directory_siret)s). SIRET should not be changed on public-sector partners.", partner=self.display_name, siret=siret, fr_directory_siret=self.fr_directory_siret))
                siren_or_siret = siret
                try:
                    siret_parsed = get_directory_siret_parsed(session, siret)
                except Exception as e:
                    raise UserError(self.env._("Failed to query directory with SIRET '%(siret)s'. Error: %(err)s", siret=siret, err=e))
                vals['fr_directory_siret'] = siret
                logger.debug(f"Result of get_directory_siret_parsed: {siret_parsed}")
                if siret_parsed.get('name'):
                    vals['fr_directory_name'] = siret_parsed['name']
                vals['fr_directory_closed'] = siret_parsed['closed']
            elif vals['fr_directory_entity_type'] == "private":
                siren_or_siret = siren
        self.write(vals)
        if vals.get('fr_directory_closed'):
            msg = f"Partner {self.display_name} ID {self.id} is marked as closed in FR directory. Disabling all its directory lines."
            log_obj._warning_log(result, msg)
            self.fr_directory_line_ids.filtered(lambda x: x.state != 'disabled').write({'state': 'disabled'})
            action['params'].update({
                'type': 'danger',
                'sticky': True,
                'message': self.env._("Partner '%(partner)s' SIREN %(siren)s is marked as closed in the directory.", partner=self.display_name, siren=siren)
                })
            return action
        if vals['fr_directory_entity_type'] == "no":
            msg = f"Partner {self.display_name} SIREN {siren} is not in the directory."
            log_obj._info_log(result, msg)
            action['params'].update({
                'type': 'warning',
                'message': self.env._("Partner '%(partner)s' SIREN %(siren)s is not in the directory.", partner=self.display_name, siren=siren),  # TODO improve message ?
                })
            return action
        assert siren_or_siret
        try:
            api_dir_lines_dict = get_directory_lines_parsed(session, siren_or_siret, siret_parsed=siret_parsed)
        except Exception as e:
            raise UserError(self.env._("Failed to query directory with SIREN or SIRET '%(siren_or_siret)s'. Error: %(err)s", siren_or_siret=siren_or_siret, err=e))
        msg = f"{len(api_dir_lines_dict)} directory lines retreived by API for partner {self.display_name} ID {self.id}"
        log_obj._info_log(result, msg)
        # Compare with existing lines: create/update/archive
        existing_dir_lines_sr = dline_obj.with_context(active_test=False).search_read([('partner_id', '=', self.id)], ['identifier', 'state', 'type', 'routing_code_name', 'commitment_required'])
        existing_identifier2vals = {line['identifier']: line for line in existing_dir_lines_sr}
        to_archive_line_ids = {line['id'] for line in existing_dir_lines_sr}
        to_create_vals_list = []
        diff_fields = ['state', 'routing_code_name', 'commitment_required']
        msgs = []
        updated_line_count = 0
        for identifier, dir_line_vals in api_dir_lines_dict.items():
            if identifier in existing_identifier2vals:
                dline_id = existing_identifier2vals[identifier]['id']
                to_archive_line_ids.remove(dline_id)
                # fields_to_check
                wvals = {}
                for dfield in diff_fields:
                    if dir_line_vals[dfield] != existing_identifier2vals[identifier][dfield]:
                        wvals[dfield] = dir_line_vals[dfield]
                if wvals:
                    dir_line = dline_obj.browse(dline_id)
                    logger.debug(f"Updating directory line {identifier} ID {dline_id} with vals={wvals}")
                    dir_line.sudo().write(wvals)
                    updated_line_count += 1
            else:
                cvals = dict(dir_line_vals, partner_id=self.id, identifier=identifier)
                to_create_vals_list.append(cvals)

        if to_create_vals_list:
            dline_obj.sudo().create(to_create_vals_list)
            msgs.append(self.env._("%d directory lines created.", len(to_create_vals_list)))
            result['new_count'] += len(to_create_vals_list)
        if updated_line_count:
            msgs.append(self.env._("%d directory lines updated.", updated_line_count))
            result['updated_count'] += updated_line_count
        if to_archive_line_ids:
            to_archive_lines = dline_obj.browse(list(to_archive_line_ids))
            to_archive_lines.sudo().write({'state': 'disabled'})
            msgs.append(self.env._("%d directory lines archived.", len(to_archive_line_ids)))
            result['updated_count'] += len(to_archive_line_ids)
        if not self.fr_directory_line_ids.filtered(lambda x: x.state == 'active'):
            if self.fr_directory_entity_type == "private":
                self.write({'fr_directory_entity_type': 'private_inactive'})
            elif self.fr_directory_entity_type == "public":
                raise UserError(self.env._("Public sector partner '%s' doesn't have any active directory line. This should never happen.", self.display_name))
        message = msgs and ' '.join(msgs) or self.env._("Directory line(s) unchanged.")
        log_obj._info_log(result, f"Directory lines of partner {self.display_name} ID {self.id}: {len(to_create_vals_list)} created, {updated_line_count} updated and {len(to_archive_line_ids)} archived.")
        action['params']['message'] = message
        return action
