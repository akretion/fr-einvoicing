# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urljoin

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.http import request

logger = logging.getLogger(__name__)
try:
    from pyfrctc import (
        get_authorization_url,
        get_session,
        healthcheck,
        search_flows_parsed,
    )
except (OSError, ImportError) as err:
    logger.debug("Cannot import pyfrctc. Error details below.")
    logger.debug(err)

TIMEOUT = 30
CALLBACK_PATH = "/fr_ctc_onboarding_callback"


class ResCompany(models.Model):
    _inherit = "res.company"

    fr_ctc_accredited_platform = fields.Selection(
        [
            ("superpdp", "SUPER PDP"),
        ],
        default="superpdp",
        string="Accredited Platform",
    )
    fr_ctc_auth_method = fields.Selection(
        [
            ("client_credentials", "Client Credentials"),
            ("authorization_code", "Authorization Code"),
        ],
        string="Authentication Method for AP",
    )
    fr_ctc_client_id = fields.Char(
        groups="base.group_system",
        string="Client ID for AP",
        compute="_compute_fr_ctc_credentials",
        store=True,
        readonly=False,
        precompute=True,
    )
    fr_ctc_client_secret = fields.Char(
        groups="base.group_system",
        string="Client Secret for AP",
        compute="_compute_fr_ctc_credentials",
        store=True,
        readonly=False,
        precompute=True,
    )
    fr_ctc_last_flow_import_datetime = fields.Datetime(
        string="Last Flow Import from Accredited Platform"
    )
    fr_ctc_send_invoice_format = fields.Selection(
        [
            ("facturx", "Factur-X"),
            ("ubl_pdf", "UBL XML with embedded PDF file"),
            ("ubl", "UBL XML"),
            ("cii_pdf", "CII XML with embedded PDF file"),
            ("cii", "CII XML"),
        ],
        default="facturx",
        string="Send Invoice Format",
    )
    fr_ctc_auto_reverse = fields.Boolean(
        string="Auto Reverse Invoice if Refused/Rejected",
        default=True,
    )
    fr_ctc_event_auto_send_in_hand = fields.Boolean(
        string="Auto Send In Hand Event",
        default=True,
        help="Automatically send 'In Hand' event when vendor bill/refund "
        "is imported in Odoo",
    )
    fr_ctc_event_auto_send_approved = fields.Boolean(
        string="Auto Send Approved Event",
        default=True,
        help="Automatically send 'Approved' event when vendor bill/refund is "
        "confirmed in Odoo",
    )
    # Maybe we will use the OCA module mail_activity_team ? in a separate module ?
    fr_ctc_activity_warning_event_user_ids = fields.Many2many(
        "res.users",
        "fr_ctc_activity_warning_event_company_user_rel",
        string="Users that will get an Activity when a Warning Event is received",
    )
    fr_ctc_activity_warning_event_invoice_creator = fields.Boolean(
        string="Activity for the Creator of the Invoice when a Warning Event "
        "is received",
        default=True,
    )
    fr_ctc_activity_warning_event_salesman = fields.Boolean(
        string="Activity for the Salesman of the Invoice when a Warning Event "
        "is received",
        default=True,
    )
    fr_ctc_directory_sync_on_invoice_post = fields.Selection(
        [
            ("blocking", "Yes, always"),
            ("not_blocking", "Yes, if directory is reachable"),
            ("no", "No"),
        ],
        default="not_blocking",
        string="Directory Sync on Invoice Confirmation",
    )
    fr_ctc_send_out_invoice = fields.Selection(
        [
            ("all", "All"),
            ("b2g", "B2G only"),
            ("b2b", "B2B only"),
            ("none", "No"),
        ],
        string="Send Customer Invoices/Refunds via AP",
        default="all",
    )
    fr_ctc_get_in_invoice = fields.Boolean(
        default=True, string="Get Vendor Bills from AP"
    )

    @api.depends("fr_ctc_auth_method")
    def _compute_fr_ctc_credentials(self):
        for company in self:
            if company.fr_ctc_auth_method == "authorization_code":
                company.fr_ctc_client_id = False
                company.fr_ctc_client_secret = False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        platform = res.get("fr_ctc_accredited_platform")
        if platform:
            client_id_key = f"fr_ctc_{platform}_client_id"
            client_id = tools.config.get(client_id_key)
            if client_id:
                res["fr_ctc_auth_method"] = "authorization_code"
        return res

    def _fr_ctc_credentials(self):
        """Return (client_id, client_secret)"""
        self.ensure_one()
        platform = self.fr_ctc_accredited_platform
        if not platform:
            raise UserError(
                _(
                    "No accredited platform selected for company '%s'.",
                    self.display_name,
                )
            )
        if not self.fr_ctc_auth_method:
            raise UserError(
                _(
                    "The authentication method for the accredited platform is "
                    "not configured on company '%s'.",
                    self.display_name,
                )
            )
        if self.fr_ctc_auth_method == "client_credentials":
            client_id = self.sudo().fr_ctc_client_id
            if not client_id:
                raise UserError(
                    _(
                        "The Client ID of the accredited platform is not configured "
                        "on company '%s'.",
                        self.display_name,
                    )
                )
            client_secret = self.sudo().fr_ctc_client_secret
            if not client_secret:
                raise UserError(
                    _(
                        "The Client Secret of the accredited platform is not "
                        "configured on company '%s'.",
                        self.display_name,
                    )
                )
        elif self.fr_ctc_auth_method == "authorization_code":
            client_secret = False
            client_id_key = f"fr_ctc_{platform}_client_id"
            client_id = tools.config.get(client_id_key)
            if not client_id:
                raise UserError(
                    _(
                        "Missing key '%s' in the Odoo server configuration file.",
                        client_id_key,
                    )
                )
        else:
            raise UserError(
                _("No auth method configured on company %s.", self.display_name)
            )
        return (client_id, client_secret)

    def _fr_ctc_get_token(self, auth_method):
        self.ensure_one()
        company_id = self.id
        with self.pool.cursor() as new_cr:
            # Flush the pending operations to avoid a deadlock (inspired by iap module)
            # self.env.flush_all()
            token_obj = self.with_env(self.env(cr=new_cr)).env["fr.einvoicing.token"]
            token_rec = token_obj.sudo().search(
                [("company_id", "=", company_id)], limit=1
            )
            if token_rec:
                token = {
                    "access_token": token_rec.access_token,
                    "expires_at": token_rec.expires_at,
                    "token_type": "bearer",
                }
            else:
                token = {
                    "access_token": False,
                    "expires_at": False,
                    "token_type": "bearer",
                }

            if auth_method == "authorization_code" and token_rec:
                token["refresh_token"] = token_rec.refresh_token
                if not token["refresh_token"]:
                    raise UserError(
                        _("Missing refresh token. You must run the onboarding wizard.")
                    )
            if token["expires_at"]:
                expiry_dt = datetime.fromtimestamp(token["expires_at"])
                logger.info(
                    "Current access_token expires on %s UTC",
                    fields.Datetime.to_string(expiry_dt),
                )
        return token

    def _fr_ctc_write_token(self, new_token):
        self.ensure_one()
        company_id = self.id
        company_name = self.name
        vals = {
            "access_token": new_token.get("access_token"),
            "refresh_token": new_token.get("refresh_token"),
            "expires_at": new_token.get("expires_at"),
        }
        with self.pool.cursor() as new_cr:
            # Flush the pending operations to avoid a deadlock (inspired by iap module)
            # self.env.flush_all()
            token_obj = self.with_env(self.env(cr=new_cr)).env["fr.einvoicing.token"]
            token_rec = token_obj.sudo().search(
                [("company_id", "=", company_id)], limit=1
            )
            if token_rec:
                token_rec.write(vals)
                logger.info(
                    f"New token saved for company {company_name}: "
                    f"token ID {token_rec.id} updated"
                )
            else:
                token_rec = token_obj.create(dict(vals, company_id=company_id))
                logger.info(
                    f"New token saved for company {company_name}: "
                    f"token ID {token_rec.id} created"
                )

    def _fr_ctc_get_session(self):
        self.ensure_one()
        client_id, client_secret = self._fr_ctc_credentials()
        company_ident4log = f"{self.display_name} ID {self.id}"
        return get_session(
            self.fr_ctc_accredited_platform,
            self.fr_ctc_auth_method,
            company_ident4log,
            self._fr_ctc_get_token,
            self._fr_ctc_write_token,
            client_id,
            client_secret=client_secret,
        )

    def fr_ctc_run_import_log_action(self, origin):
        _flows, result = self.fr_ctc_run_import_log(origin)
        msg_list = []
        notif_type = "success"
        if result["new_count"]:
            msg_list.append(
                _("%(count)s flow(s) successfully created.", count=result["new_count"])
            )
        else:
            msg_list.append(_("No flow imported.", count=result["new_count"]))

        if result["warning_count"]:
            notif_type = "warning"
            msg_list.append(_("%(count)s warning(s).", count=result["warning_count"]))
        if result["error_count"]:
            notif_type = "danger"
            msg_list.append(
                _(
                    "%(count)s error(s): see logs for error.",
                    count=result["error_count"],
                )
            )

        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notif_type,
                "title": _("Import from AP"),
                "message": " ".join(msg_list),
            },
        }
        return action

    def fr_ctc_run_import_log(self, origin):
        log_obj = self.env["fr.einvoicing.log"]
        result = {
            "log_type": "flow_import_single",
            "log_origin": origin,
            "company_id": self.id,
            "logs": [],
            "new_count": 0,
        }
        session = self._fr_ctc_get_session()
        flows = self._fr_ctc_run_import(session, result)
        log_obj._create_log(result)
        return (flows, result)

    def _fr_ctc_import_updated_after(self):
        self.ensure_one()
        updated_after = self.fr_ctc_last_flow_import_datetime
        if updated_after:
            # rewind 1h, just in case
            updated_after -= timedelta(hours=1)
        else:
            updated_after = fields.Datetime.now() - timedelta(days=30)
        return updated_after

    def _fr_ctc_run_import(self, session, result, download_and_process=True):
        """
        Implementation strategy:
        all errors should be catched and logged in result dict. Not via large
        catch-all try/except, but by small try/except that target methods
        that call external APIs or 'external' methods. No try/except for
        regular code that we control that is not supposed to raise an exception
        (unless there is a coding mistake...
        but we don't want to catch our coding mistakes !)
        """
        self.ensure_one()
        flow_obj = self.env["fr.einvoicing.flow"]
        log_obj = self.env["fr.einvoicing.log"]
        updated_after = self._fr_ctc_import_updated_after()
        now_dt = fields.Datetime.now()
        msg = (
            f"Start to import new flows in company {self.display_name} "
            f"from {updated_after}"
        )
        log_obj._info_log(result, msg)
        types_to_get = [
            "CustomerInvoiceLC",
            "SupplierInvoiceLC",
            # "StateCustomerInvoiceLC",  gives error :
            #  RuntimeError: POST request on
            #  https://api.superpdp.tech/afnor-flow/v1/flows/search failed (400).
            #  Error code: PARAMS_ERROR. Error message: json: cannot unmarshal
            #  into Go model.AfnorFlowType within "/where/flowType/3":
            #  invalid flowType : 'StateCustomerInvoiceLC'
            # "StateSupplierInvoiceLC",
        ]
        if self.fr_ctc_get_in_invoice:
            types_to_get.append("SupplierInvoice")
        logger.debug(f"types_to_get for search flows: {types_to_get}")
        res_search = search_flows_parsed(session, updated_after, ["in"], types_to_get)
        msg = f"Got {len(res_search)} flows updated after {updated_after} UTC"
        log_obj._info_log(result, msg)
        # from pprint import pprint
        # pprint(res_search)

        limit_create_date = updated_after - timedelta(90)
        already_imported_flows_sr = flow_obj.search_read(
            [
                ("company_id", "=", self.id),
                ("identifier", "!=", False),
                ("create_date", ">=", limit_create_date),
            ],
            ["identifier"],
        )
        already_imported_flows = [x["identifier"] for x in already_imported_flows_sr]

        to_create_flows = []
        for flow_entry in res_search:
            # print("flow_entry============")
            # pprint(flow_entry)
            flow_id = flow_entry.get("flowId")
            if not flow_id:
                continue
            if (
                flow_entry.get("flow_direction")
                and flow_entry["flow_direction"] != "in"
            ):
                msg = (
                    f"Flow {flow_entry} has direction "
                    f"'{flow_entry['flow_direction']}': it should be 'in'"
                )
                log_obj._error_log(result, msg)
                continue
            if flow_entry.get("type"):
                if flow_entry["type"] not in types_to_get:
                    msg = (
                        f"Flow {flow_entry} has type '{flow_entry['type']}': "
                        f"it should be part of {types_to_get}"
                    )
                    logger.error(result, msg)
                    continue
            if flow_id in already_imported_flows:
                msg = f"Flow {flow_id} skipped because it has already been imported"
                log_obj._info_log(result, msg)
                continue
            to_create_flows.append(self._fr_ctc_prepare_in_flow(flow_entry))
        self.sudo().write({"fr_ctc_last_flow_import_datetime": now_dt})
        flows = flow_obj.sudo().create(to_create_flows)
        result["new_count"] += len(flows)
        if download_and_process:
            for flow in flows:
                flow._download(session, result)
                if flow.state == "downloaded":
                    flow._process(result)
        return flows

    def _fr_ctc_prepare_in_flow(self, flow_dict):
        self.ensure_one()
        flow_vals = {
            "direction": "in",
            "identifier": flow_dict.get("flowId"),
            "syntax": flow_dict.get("flowSyntax"),
            "type": flow_dict.get("flowType"),
            "processing_rule": flow_dict.get("processingRule"),
            "updated_at": flow_dict.get("updated_at"),
            "submitted_at": flow_dict.get(
                "submitted_at"
            ),  # I don't know what it means on In
            "ap_error_details": flow_dict.get("ap_error_details"),
            "company_id": self.id,
        }
        return flow_vals

    def _fr_ctc_is_vat_registered(self, raise_if_misconfigured=False):
        if not self.country_id and raise_if_misconfigured:
            raise UserError(
                _("Country is not set on company '%s'.", company=self.display_name)
            )
        if not self.is_france_country:
            return False
        if not self.fr_ctc_accredited_platform:
            # we don't raise if misconfigured here because we need this solution
            # to by-pass the checks on invoice/SO confirmation for an FR company
            # that is not onboarded yet
            logger.info(f"No AP selected for company {self.display_name}")
            return False
        cpartner = self.partner_id
        if not cpartner.fr_directory_entity_type:
            if raise_if_misconfigured:
                raise UserError(
                    _(
                        "Entity type is not set on partner '%s'. On that partner, "
                        "click on the button 'Directory Sync'.",
                        cpartner.display_name,
                    )
                )
        elif cpartner.fr_directory_entity_type == "public":
            if raise_if_misconfigured:
                raise UserError(
                    _(
                        "Partner '%s' is a public entity. This scenario is "
                        "not supported.",
                        cpartner.display_name,
                    )
                )
        elif cpartner.fr_directory_entity_type == "private":
            if not cpartner._get_siren() and raise_if_misconfigured:
                raise UserError(
                    _("SIREN is not set on partner '%s'.", cpartner.display_name)
                )
            return True
        return False

    def _fr_ctc_test_api(self):
        self.ensure_one()
        platform = self.fr_ctc_accredited_platform
        platform_label = dict(
            self._fields["fr_ctc_accredited_platform"]._description_selection(self.env)
        )[platform]
        try:
            session = self._fr_ctc_get_session()
            healthcheck(session)
        except Exception as err:
            raise UserError(
                _(
                    "Odoo failed to connect to the API of %(platform)s. "
                    "Error: %(error)s",
                    error=err,
                    platform=platform_label,
                )
            ) from err
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _(
                    "Successful connection to the API of %(platform)s.",
                    platform=platform_label,
                ),
                "type": "success",
                "sticky": False,
            },
        }
        return action

    def _fr_ctc_redirect_uri(self):
        base_url = self.env["ir.config_parameter"].get_param("web.base.url")
        if base_url.startswith("http://"):
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        return urljoin(base_url, CALLBACK_PATH)

    def _fr_ctc_authorization_code_redirect(self):
        self.ensure_one()
        client_id, _client_secret = self._fr_ctc_credentials()
        assert self.fr_ctc_auth_method == "authorization_code"
        optional_uri_params = {}
        if self.fr_ctc_accredited_platform == "superpdp":
            running_env = tools.config.get("running_env")
            siren = self.partner_id._get_siren(raise_if_none=True)
            optional_uri_params = {"superpdp_company_number": siren}
            if running_env in ("test", "dev"):
                optional_uri_params["superpdp_company_number_scheme"] = "sandbox"
            else:
                optional_uri_params["superpdp_company_number_scheme"] = "fr_siren"
        redirect_uri = self._fr_ctc_redirect_uri()
        logger.info(f"Redirect URI sent to the accredited platform: {redirect_uri}")
        authorization_url, state, code_verifier = get_authorization_url(
            self.fr_ctc_accredited_platform,
            client_id,
            redirect_uri,
            optional_uri_params=optional_uri_params,
        )

        if request:
            request.session["fr_ctc_company_id"] = self.id
            request.session["fr_ctc_code_verifier"] = code_verifier
            request.session["fr_ctc_state"] = state
            request.session.is_dirty = True

        logger.info("Redirecting to URL %s", authorization_url)
        action = {
            "type": "ir.actions.act_url",
            "url": authorization_url,
            "target": "new",
        }
        return action

    def _fr_ctc_compute_invoice_company_dir_line(self):
        self.ensure_one()
        domain = [
            ("move_type", "in", ("out_invoice", "out_refund")),
            ("company_id", "=", self.id),
            ("company_fr_directory_line_id", "=", False),
        ]
        if self.fiscalyear_lock_date:
            domain.append(("date", ">", self.fiscalyear_lock_date))
        invoices = self.env["account.move"].search(domain)
        logger.info(
            "Recomputing field company_fr_directory_line_id on %d invoices "
            "in company %s",
            len(invoices),
            self.display_name,
        )
        invoices._compute_company_fr_directory_line_id()
        logger.info(
            "Recomputation of field company_fr_directory_line_id in company %s "
            "finished",
            self.display_name,
        )

    def _fr_ctc_superpdp_sandbox_create(
        self, burger_queen_suffix="1242", tricatel_suffix="1243"
    ):
        # WARNING: Burger Queen and Tricatel suffixes are different in earch sandbox
        # so you MUST customize the 2 arguments
        logger.info("Start to create a SUPER PDP sandbox")
        if tools.config.get("running_env") not in ("test", "dev"):
            logger.warning(
                "You are trying to create a SUPER PDP sandbox but running_env is not "
                "test/dev. Aborting."
            )
            return False
        last_sync_date = fields.Date.context_today(self) - timedelta(1)
        burger_queen = self.env["res.company"].create(
            {
                "name": "Burger Queen",
                "street": "809 avenue du Languedoc",
                "zip": "12100",
                "city": "Millau",
                "country_id": self.env.ref("base.fr").id,
                "fr_ctc_auth_method": "authorization_code",
            }
        )
        burger_queen_partner = burger_queen.partner_id
        # Set VAT and SIREN by SQL to by-pass constraints
        self.env.cr.execute(
            """
            UPDATE res_partner
            SET vat='FR18000000002',
            siren='000000002',
            siret='000000002*****',
            fr_directory_entity_type='private',
            fr_directory_name='Burger Queen',
            fr_directory_siren='000000002',
            fr_directory_last_sync_date=%s
            WHERE id=%s
            """,
            (last_sync_date, burger_queen_partner.id),
        )
        self.env.cr.execute(
            "UPDATE res_company SET siren='000000002' WHERE id=%s", (burger_queen.id,)
        )
        self.env["fr.directory.line"].create(
            {
                "partner_id": burger_queen_partner.id,
                "identifier": f"315143296_{burger_queen_suffix}",
                "type": "suffix",
                "siren": "315143296",
                "suffix": burger_queen_suffix,
                "state": "active",
            }
        )
        logger.info("Company Burger Queen created ID %s", burger_queen.id)
        tricatel = self.env["res.company"].create(
            {
                "name": "Tricatel",
                "street": "Avenue de la République",
                "zip": "37170",
                "city": "Chambray-lès-Tours",
                "country_id": self.env.ref("base.fr").id,
                "fr_ctc_auth_method": "authorization_code",
            }
        )
        tricatel_partner = tricatel.partner_id
        # Set VAT and SIREN by SQL to by-pass constraints
        self.env.cr.execute(
            """
            UPDATE res_partner
            SET vat='FR15000000001',
            siren='000000001',
            siret='000000001*****',
            fr_directory_entity_type='private',
            fr_directory_name='Tricatel',
            fr_directory_siren='000000001',
            fr_directory_last_sync_date=%s
            WHERE id=%s
            """,
            (last_sync_date, tricatel_partner.id),
        )
        self.env.cr.execute(
            "UPDATE res_company SET siren='000000001' WHERE id=%s", (tricatel.id,)
        )
        self.env["fr.directory.line"].create(
            {
                "partner_id": tricatel_partner.id,
                "identifier": f"315143296_{tricatel_suffix}",
                "type": "suffix",
                "siren": "315143296",
                "suffix": tricatel_suffix,
                "state": "active",
            }
        )
        logger.info("Company Tricatel created ID %s", tricatel.id)

    def _fr_ctc_superpdp_sandbox_setup(self):
        logger.info("Start to setup an existing SUPER PDP sandbox")
        companies = self.env["res.company"].search(
            [
                ("partner_id.country_id", "=", self.env.ref("base.fr").id),
                ("siren", "in", ("000000001", "000000002")),
            ]
        )
        if len(companies) != 2:
            logger.warning(
                "Aborting setup: could not find Burger Queen and/or Tricatel"
            )
            return False
        tax_domain = [
            ("type_tax_use", "=", "sale"),
            ("unece_type_code", "=", "VAT"),
            ("unece_categ_code", "=", "E"),
            ("unece_vatex_id", "=", False),
            ("active", "=", True),
        ]
        sample_vatex_id = self.env.ref("account_tax_unece.tax_vatex_fr_cgi261c_3").id
        exempt_vat_taxes = (
            self.env["account.tax"]
            .sudo()
            .search([("company_id", "in", companies.ids)] + tax_domain)
        )
        if exempt_vat_taxes:
            exempt_vat_taxes.write({"unece_vatex_id": sample_vatex_id})
            logger.info("VATEX set on taxes IDs %s", exempt_vat_taxes.ids)
