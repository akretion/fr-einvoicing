# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import mimetypes
from datetime import datetime

from odoo import api, fields, models, tools
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class FrEinvoicingEvent(models.Model):
    _name = "fr.einvoicing.event"
    _description = "Invoice Event"
    _order = "move_id, datetime desc"
    _check_company_auto = True

    move_id = fields.Many2one(
        "account.move", string="Invoice", readonly=True, check_company=True
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    datetime = fields.Datetime(
        readonly=True,
        string="Issue Date and Time",
        copy=False,
        default=fields.Datetime.now,
    )
    date = fields.Date(
        required=True,
        readonly=True,
        string="Issue Date",
        copy=False,
        default=fields.Date.context_today,
    )
    status = fields.Selection("_status_selection", required=True, readonly=True)
    status_decoration = fields.Char(compute="_compute_status_decoration", store=True)
    flow_id = fields.Many2one(
        "fr.einvoicing.flow", readonly=True, copy=False, check_company=True
    )
    flow_state = fields.Selection(
        related="flow_id.state", store=True, string="Flow State"
    )
    infos = fields.Html(compute="_compute_details", store=True)
    currency_id = fields.Many2one(
        "res.currency", compute="_compute_payments", store=True
    )
    amount = fields.Monetary(compute="_compute_payments", store=True)
    direction = fields.Selection(
        [
            ("in", "In"),
            ("out", "Out"),
        ],
        required=True,
        readonly=True,
    )
    detail_ids = fields.One2many(
        "fr.einvoicing.event.detail", "event_id", string="Reasons and Actions"
    )
    payment_ids = fields.One2many(
        "fr.einvoicing.event.payment", "event_id", string="Payments"
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "fr_einvoicing_event_attachment_rel",
        string="Attachments",
        readonly=True,
    )

    @api.model
    def _prepare_flow(self, event_vals):
        move_id = event_vals["move_id"]
        invoice = self.env["account.move"].browse(move_id)
        if invoice.is_sale_document():
            flow_type = "CustomerInvoiceLC"
        elif invoice.is_purchase_document():
            flow_type = "SupplierInvoiceLC"
        else:
            raise UserError(
                self.env._(
                    "An event must be linked to a customer invoice/refund "
                    "or a vendor bill/refund. This should never happen."
                )
            )
        partner_entity_type = invoice.commercial_partner_id.fr_directory_entity_type
        if partner_entity_type == "private":
            processing_rule = "B2B"
        elif partner_entity_type == "public":
            processing_rule = "B2G"
        else:
            processing_rule = "OutOfScope"
        flow_vals = {
            "direction": "out",
            "type": flow_type,
            "company_id": invoice.company_id.id,
            "syntax": "CDAR",
            "processing_rule": processing_rule,
        }
        return flow_vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("direction") == "out":
                flow_vals = self._prepare_flow(vals)
                flow = self.env["fr.einvoicing.flow"].sudo().create(flow_vals)
                vals["flow_id"] = flow.id
        events = super().create(vals_list)
        events._auto_process()
        return events

    def _auto_process(self):
        if tools.config.get("running_env") in ("dev", "test"):
            result = {"logs": []}
            company = self[0].company_id
            try:
                session = company._fr_ctc_get_session()
            except Exception:
                logger.warning("Failed to get session")
                return
            for event in self.filtered(lambda x: x.direction == "out"):
                assert event.company_id == company
                flow = event.flow_id
                flow._generate(result)
                if flow.state == "generated":
                    flow._send(session, result)

    @api.depends("detail_ids.reason", "detail_ids.comment")
    def _compute_details(self):
        reason2label = dict(
            self.env["fr.einvoicing.event.detail"]
            ._fields["reason"]
            ._description_selection(self.env)
        )
        for event in self:
            info_list = [det._display_html(reason2label) for det in event.detail_ids]
            if event.attachment_ids:
                if len(event.attachment_ids) == 1:
                    prefix = self.env._("1 attachment:")
                else:
                    prefix = self.env._("%s attachments:", len(event.attachment_ids))
                info_list.append(
                    f"<strong>{prefix}</strong> "
                    f"{', '.join([x.name for x in event.attachment_ids])}"
                )
            event.infos = "<br/>".join([x for x in info_list if x])

    @api.depends("payment_ids.amount", "payment_ids.currency_id")
    def _compute_payments(self):
        for event in self:
            currency_ids = set()
            amount = 0.0
            for payment in event.payment_ids:
                currency_ids.add(payment.currency_id.id)
                amount += payment.amount
            if len(currency_ids) == 1:
                currency_id = currency_ids.pop()
            else:
                currency_id = False
                amount = 0.0
            event.currency_id = currency_id
            event.amount = amount

    @api.depends("status")
    def _compute_status_decoration(self):
        all_status_dict = self._get_all_status()
        for event in self:
            decoration = False
            if event.status:
                decoration = all_status_dict[event.status].get("decoration")
            event.status_decoration = decoration

    @api.model
    def _get_all_status(self):
        # Info for MDT-88 is in XP_Z12-012_Annexe_A_2026_V1.3.xlsx
        # tab "CDV FE - CDAR", line MDT-88, column "Règles de gestion entre PA"
        res = {
            "submitted": {
                "label": self.env._("Submitted"),  # Déposée
                "code": "200",
                "decoration": "muted",
            },
            "ap_sent": {
                "label": self.env._(
                    "Issued by the Platform"
                ),  # Emise par la plateforme (PAe)
                "code": "201",
                "decoration": "muted",
            },
            "ap_received": {
                "label": self.env._(
                    "Received by the Platform"
                ),  # Reçue par la plateforme (PAr)
                "code": "202",
                "decoration": "muted",
            },
            "ap_available": {
                "label": self.env._("Made Available"),  # Mise à disposition  (PAr)
                "str_code": "ap_available",
                "code": "203",
                "decoration": "muted",
            },
            "in_hand": {
                "label": self.env._("In Hand"),  # Prise en charge
                # In Invoice: auto-set by Odoo when creating the draft supplier invoice
                "code": "204",
                "MDT-88": "45",
                "decoration": "info",
            },
            "approved": {
                "label": self.env._("Approved"),  # Approuvée
                "manual": "purchase",
                "code": "205",
                "MDT-88": "1",
                "decoration": "success",
            },
            "partially_approved": {
                "label": self.env._("Partially Approved"),  # Approuvée partiellement
                "manual": "purchase",
                "code": "206",
                "detail_required": True,
                "MDT-88": "49",
                "decoration": "warning",
            },
            "dispute": {
                "label": self.env._("Disputed"),  # En litige
                "manual": "purchase",
                "code": "207",
                "detail_required": True,
                "MDT-88": "46",
                "decoration": "warning",
            },
            "suspended": {
                "label": self.env._("Suspended"),  # Suspendue
                "manual": "purchase",
                "code": "208",
                "detail_required": True,
                "MDT-88": "39",
                "decoration": "warning",
            },
            "completed": {
                "label": self.env._("Completed"),  # Complétée
                "manual": "sale",
                "code": "209",
                "MDT-88": "37",
                "decoration": "info",
            },
            "refused": {
                "label": self.env._("Refused"),
                "manual": "purchase",
                "code": "210",
                "detail_required": True,
                "confirm_required": True,
                "MDT-88": "50",
                "decoration": "danger",
            },
            "payment_sent": {
                "label": self.env._("Payment Sent"),
                "code": "211",
                "MDT-88": "47",
                "decoration": "success",
            },
            "payment_received": {
                "label": self.env._("Payment Received"),
                "code": "212",
                "MDT-88": "47",
                "decoration": "success",
            },
            "rejected": {
                "label": self.env._("Rejected"),  # Rejeté
                # Technical status set by PA
                "code": "213",
                "decoration": "danger",
            },
            "stamped": {
                "label": self.env._("Stamped"),  # Visée
                "code": "214",
                "decoration": "success",
            },
            "cancelled": {
                "label": self.env._("Cancelled"),  # Annulée (pour facture rectif)
                "code": "220",
                "decoration": "danger",
            },
            "routing_error": {  # we're not supposed to reveive it... only between PAs
                "label": self.env._("Routing Error"),  # Erreur routage
                "code": "221",
                "decoration": "danger",
            },
            "direct_payment_query": {
                "label": self.env._(
                    "Direct Payment Query"
                ),  # Demande de paiement direct
                "code": "224",
                "decoration": "info",
            },
            "factored": {
                "label": self.env._("Factored"),  # Affacturée
                "code": "225",
                "decoration": "info",
            },
            "undisclosed_factored": {  # alternative term : non-notification factoring
                "label": self.env._("Undisclosed Factored"),  # Affacturée confidentiel
                "code": "226",
                "decoration": "info",
            },
            "payment_entity_change": {
                "label": self.env._(
                    "Payment Entity Change"
                ),  # Changement de compte à payer
                "code": "227",
                "decoration": "info",
            },
            "not_factored": {
                "label": self.env._("Not Factored"),  # Non affacturée
                "code": "228",
                "decoration": "info",
            },
            "unacceptable": {  # we're not supposed to reveive it... only between PAs
                "label": self.env._("Unacceptable"),  # Irrecevable
                "code": "501",
                "decoration": "danger",
            },
        }
        unique_code = set()
        required_values = ("label", "code")
        for key, vals in res.items():
            for required_value in required_values:
                if not vals.get(required_value):
                    raise RuntimeError(
                        f"Error in status database: missing '{required_value}' "
                        f"for code '{key}'"
                    )
            code = vals["code"]
            if code in unique_code:
                raise RuntimeError(
                    f"Error in status database: code {code} is not unique."
                )
            unique_code.add(code)
        return res

    @api.model
    def _status_selection(self):
        res = self._get_all_status()
        sel = [(key, vals["label"]) for key, vals in res.items()]
        return sel

    @api.model
    def _status_selection_manual(self, sale_or_purchase):
        res = self._get_all_status()
        sel = [
            (key, vals["label"])
            for key, vals in res.items()
            if vals.get("manual") == sale_or_purchase
        ]
        return sel

    @api.model
    def _get_status_key(self, code, raise_if_not_found=True):
        assert isinstance(code, str)
        code = code.strip()
        res = self._get_all_status()
        for key, vals in res.items():
            if vals["code"] == code:
                return key
        if raise_if_not_found:
            raise UserError(
                self.env._(
                    "Status code '%s' is unknown. This should never happen.", code
                )
            )
        return None

    def _convert_datetime2str(self, utc_datetime_naive, date_format):
        """The specs don't say anything about the timezone of the datetime
        nodes. Initially, I thought it would be more common to put
        it in the company's timezone, but I now think that it is better
        to set to UTC"""
        self.ensure_one()
        # if self.company_id.partner_id.tz:
        #    company_tz = pytz.timezone(self.company_id.partner_id.tz)
        # else:
        #    company_tz = pytz.utc
        # utc_datetime_aware = pytz.utc.localize(utc_datetime_naive)
        # companytz_datetime_aware = utc_datetime_aware.astimezone(company_tz)
        # companytz_datetime_naive = companytz_datetime_aware.replace(tzinfo=None)
        res = utc_datetime_naive.strftime(date_format)
        return res

    def _prepare_xml_data(self):  # noqa: C901
        self.ensure_one()
        assert self.status
        status = self.status
        invoice = self.move_id
        logger.info(
            "Preparing XML for event %s linked to invoice %s",
            self.display_name,
            invoice.display_name,
        )
        company_siren = invoice.company_id.partner_id._get_siren(raise_if_none=True)
        company_name = invoice.company_id.name
        partner_siren = invoice.commercial_partner_id._get_siren(raise_if_none=True)
        partner_name = invoice.commercial_partner_id.name
        if not invoice.invoice_date:
            assert invoice.is_purchase_document()
            raise UserError(
                self.env._(
                    "Bill date is not set on '%s'. As this vendor bill has been "
                    "imported from the accredited plateform, it was certainly set "
                    "during the import. Maybe a user has removed the bill date "
                    "afterwards. You must set it back to it's original value.",
                    invoice.display_name,
                )
            )
        inv_date_dt = invoice.invoice_date

        if invoice.is_sale_document():
            sender_role_code = "SE"  # seller
            recipient_role_code = "BY"  # buyer
            inv_number = invoice.name
            issuer_siren = company_siren
        elif invoice.is_purchase_document():
            sender_role_code = "BY"
            recipient_role_code = "SE"
            inv_number = invoice.ref
            if not inv_number:
                raise UserError(
                    self.env._(
                        "Bill reference is not set on vendor bill '%s'. As this "
                        "vendor bill has been imported from the accredited plateform, "
                        "it was certainly set during the import. Maybe a user has "
                        "removed the bill reference afterwards. You must set it back "
                        "to it's original value.",
                        invoice.display_name,
                    )
                )
            issuer_siren = partner_siren
        else:
            raise
        inv_type_code = "380"  # TODO save imported value
        if invoice.move_type in ("out_refund", "in_refund"):
            inv_type_code = "381"
        if not invoice.partner_id:
            raise UserError(
                self.env._("Partner is not set on invoice '%s'.", invoice.display_name)
            )
        if not invoice.fr_directory_line_identifier:
            raise UserError(
                self.env._(
                    "Directory line identifier is not set on invoice '%s'.",
                    invoice.display_name,
                )
            )

        now_utc = datetime.utcnow()

        status_dict = self._get_all_status()[status]
        mdt_88 = status_dict.get("MDT-88")
        if not mdt_88:
            raise UserError(
                self.env._("MDT-88 key is not set for status '%s'.", status)
            )
        identifier = (
            f"{inv_number}_{inv_type_code}_{inv_date_dt}#"
            f"{status_dict['code']}_{now_utc.strftime('%Y%m%d%H%M%S')}"
        )
        reception_datetime = invoice.fr_einvoicing_flow_id.create_date
        data_dict = {
            "MDT-2": "REGULATED",
            "MDT-3": "urn.cpro.gouv.fr:1p0:CDV:invoice",
            "MDT-4": identifier,
            "MDT-8": now_utc,  # timezone
            "MDT-21": sender_role_code,  # Sender Trade Party/Role Code
            "MDT-38": {"0002": company_siren},  # SIREN Issuer
            "MDT-39": company_name,
            "MDT-40": sender_role_code,  # Issuer Trade Party/Role Code
            "MDT-57": {"0002": partner_siren},
            "MDT-58": partner_name,  # name of the destinee
            "MDT-59": recipient_role_code,
            "MDT-73": invoice.fr_directory_line_identifier,
            "MDT-73-1": "0225",
            "MDT-74": False,
            "MDT-77": 23,  # 23 : Information - pour les statuts après transmission
            "MDT-78": now_utc,  # deposit date, but we write creation date
            "MDT-87": inv_number,
            "MDT-95": reception_datetime,  # object reception datetime
            "MDT-88": mdt_88,
            "MDT-91": inv_type_code,
            "MDT-100": inv_date_dt,
            "MDT-105": status_dict["code"],
            "MDT-106": status_dict["label"],
            "MDT-129": {"0002": issuer_siren},
            "MDG-37": [],  # doc_status
        }
        reason2label = dict(
            self.env["fr.einvoicing.event.detail"]
            ._fields["reason"]
            ._description_selection(self.env)
        )
        action2label = dict(
            self.env["fr.einvoicing.event.detail"]
            ._fields["action"]
            ._description_selection(self.env)
        )
        for detail in self.detail_ids:
            detailed_data = {
                "MDT-113": detail.reason,
                "MDT-114": reason2label[detail.reason],
            }
            if detail.action:
                detailed_data.update(
                    {
                        "MDT-121": detail.action,
                        "MDT-122": action2label[detail.action],
                    }
                )
            if detail.comment:
                detailed_data["MDT-126"] = detail.comment
            data_dict["MDG-37"].append(detailed_data)
        if status == "payment_sent":
            # PB LISTE
            doc_characteristics = []
            for payment in self.payment_ids:
                amount_round = payment.currency_id.round(payment.amount)
                fmt = f"%.{self.currency_id.decimal_places}f"
                amount_str = fmt % amount_round
                doc_characteristics.append(
                    {
                        "MDT-207": "MPA",
                        "MDT-209": False,
                        "MDT-215": {
                            "float": amount_str,
                            "currency": payment.currency_id.name,
                        },
                        "MDT-219": payment.date,
                    }
                )
            if doc_characteristics:
                data_dict["MDG-37"].append({"MDG-43": doc_characteristics})
        MDT96 = []
        for attachment in self.attachment_ids:
            mime_res = mimetypes.guess_type(attachment.name)
            MDT96.append(
                {
                    "bin": attachment.raw,
                    "filename": attachment.name,
                    "mime_type": mime_res and mime_res[0] or "unknown",
                }
            )
        if MDT96:
            data_dict["MDT-96"] = MDT96
        # from pprint import pprint
        # pprint(data_dict)
        return data_dict

    def _compute_display_name(self):
        status2label = dict(self._fields["status"]._description_selection(self.env))
        for event in self:
            event.display_name = status2label.get(event.status)


class FrEinvoicingEventDetail(models.Model):
    _name = "fr.einvoicing.event.detail"
    _description = "Invoice Event Detail"

    event_id = fields.Many2one(
        "fr.einvoicing.event",
        string="Event",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    # reasons and comment are required in the view,
    # to avoid errors if they are not set on an incoming event
    reason = fields.Selection("_reason_selection", readonly=True)
    action = fields.Selection("_action_selection", readonly=True)
    comment = fields.Text(readonly=True)

    @api.model
    def _get_all_reasons(self):
        res = {
            "NON_TRANSMISE": {"label": "Destinataire non connecté"},
            "JUSTIF_ABS": {
                "label": "Justificatif absent ou insuffisant",
                "manual_status": ["suspended"],
            },
            "ROUTAGE_ERR": {
                "label": "Erreur de routage",
            },
            "AUTRE": {
                "label": "Autre",
                "manual_status": ["dispute", "partially_approved"],
            },
            "COORD_BANC_ERR": {
                "label": "Erreur de coordonnées bancaires",
                "manual_status": ["dispute", "suspended"],
            },
            "TX_TVA_ERR": {
                "label": "Taux de TVA erroné",
                "manual_status": ["refused", "dispute"],
            },
            "MONTANTTOTAL_ERR": {
                "label": "Montant total érroné",
                "manual_status": ["refused", "dispute"],
            },
            "CALCUL_ERR": {
                "label": "Erreur de calcul de la facture",
                "manual_status": ["refused", "dispute"],
            },
            "NON_CONFORME": {
                "label": "Mention légale manquante",
                "manual_status": ["refused", "dispute"],
            },
            "DOUBLON": {
                "label": "Facture en doublon (déjà émise / reçue)",
                "manual_status": ["refused", "dispute"],
            },
            "DEST_INC": {
                "label": "Destinataire inconnu",
            },
            "DEST_ERR": {
                "label": "Erreur de destinataire",
                "manual_status": ["refused", "dispute"],
            },
            "TRANSAC_INC": {
                "label": "Transaction inconnue",
                "manual_status": ["refused", "dispute"],
            },
            "EMMET_INC": {
                "label": "Émetteur inconnu",
                "manual_status": ["refused", "dispute"],
            },
            "CONTRAT_TERM": {
                "label": "Contrat terminé",
                "manual_status": ["refused", "dispute"],
            },
            "DOUBLE_FACT": {
                "label": "Déjà facturé sur autre facture",
                "manual_status": ["refused", "dispute"],
            },
            "CMD_ERR": {
                "label": "N° de commande incorrect ou manquant",
                "manual_status": [
                    "refused",
                    "dispute",
                    "partially_approved",
                    "suspended",
                ],
            },
            "ADR_ERR": {
                "label": "Adresse de facturation électronique erronée",
                "manual_status": ["refused", "dispute"],
            },
            "SIRET_ERR": {
                "label": "SIRET Erroné ou absent",
                "manual_status": ["dispute", "partially_approved", "suspended"],
            },
            "CODE_ROUTAGE_ERR": {
                "label": "Code routage absent ou erroné",
                "manual_status": ["dispute", "partially_approved", "suspended"],
            },
            "REF_CT_ABSENT": {
                "label": "Référence contractuelle nécessaire pour le traitement "
                "de la facture manquante",
                "manual_status": [
                    "refused",
                    "dispute",
                    "partially_approved",
                    "suspended",
                ],
            },
            "REF_ERR": {
                "label": "Référence incorrecte",
                "manual_status": ["dispute", "partially_approved", "suspended"],
            },
            "PU_ERR": {
                "label": "Prix unitaires incorrects",
                "manual_status": ["dispute", "partially_approved"],
            },
            "REM_ERR": {
                "label": "Remise erronée",
                "manual_status": ["dispute", "partially_approved"],
            },
            "QTE_ERR": {
                "label": "Quantité facturée incorrecte",
                "manual_status": ["dispute", "partially_approved"],
            },
            "ART_ERR": {
                "label": "Article facturé incorrect",
                "manual_status": ["dispute", "partially_approved"],
            },
            "MODPAI_ERR": {
                "label": "Modalités de paiement incorrectes",
                "manual_status": ["dispute", "partially_approved"],
            },
            "QUALITE_ERR": {
                "label": "Qualité d'article livré incorrecte",
                "manual_status": ["dispute", "partially_approved"],
            },
            "LIVR_INCOMP": {
                "label": "Problème de livraison",
                "manual_status": ["dispute", "partially_approved"],
            },
            "REJ_SEMAN": {"label": "Rejet pour erreur sémantique"},
            "REJ_UNI": {"label": "Rejet sur contrôle unicité"},
            "REJ_COH": {"label": "Rejet sur contrôle Cohérence de données"},
            "REJ_ADR": {"label": "Rejet sur Contrôle d'adressage"},
            "REJ_CONT_B2G": {"label": "Rejet sur Contrôles métier B2G"},
            "REJ_REF_PJ": {"label": "Rejet sur Référence de PJ"},
            "REJ_ASS_PJ": {"label": "Rejet sur Erreur d'association de la PJ"},
            "IRR_VIDE_F": {"label": "Contrôle de non vide sur les fichiers du flux"},
            "IRR_TYPE_F": {
                "label": "Contrôle de type et extension des fichiers du flux"
            },
            "IRR_SYNTAX": {"label": "Contrôle syntaxique des fichiers du flux"},
            "IRR_TAILLE_PJ": {
                "label": "Contrôle de taille des PJ de chaque fichier du flux"
            },
            "IRR_NOM_PJ": {
                "label": "Contrôle du nom des PJ de chaque fichier du flux "
                "(absence de caractères interdits)"
            },
            "IRR_VID_PJ": {
                "label": "Contrôle de PJ non vide de chaque fichier du flux"
            },
            "IRR_EXT_DOC": {
                "label": "Contrôle de l'extension des PJ de chaque fichier du flux"
            },
            "IRR_TAILLE_F": {
                "label": "Contrôle de taille max des fichiers contenus dans le flux"
            },
            "IRR_ANTIVIRUS": {"label": "Contrôle anti-virus"},
        }
        return res

    @api.model
    def _reason_selection(self):
        all_res = self._get_all_reasons()
        res = [(key, values["label"]) for key, values in all_res.items()]
        return res

    @api.model
    def _action_selection(self):
        res = [
            # list available in English
            ("NOA", "Aucune Action Requise"),
            ("PIN", "Information complémentaire requise"),
            ("NIN", "Créer une Facture Rectificative"),
            ("CNF", "Créer un Avoir total"),
            ("CNP", "Créer un Avoir Partiel"),
            ("CNA", "Rembourser le paiement de la facture"),
            ("OTH", "Autre"),
        ]
        return res

    def _display_html(self, reason2label):
        self.ensure_one()
        res = []
        if self.reason:
            reason2label = dict(self._fields["reason"]._description_selection(self.env))
            reason_field_label = self.env._("Reason:")
            res.append(
                f"<strong>{reason_field_label}</strong> {reason2label[self.reason]}"
            )
        if self.comment:
            comment_field_label = self.env._("Comment:")
            res.append(f"<strong>{comment_field_label}</strong> {self.comment}")
        return " ".join(res)


class FrEinvoicingEventPayment(models.Model):
    _name = "fr.einvoicing.event.payment"
    _description = "Invoice Event Payment"

    event_id = fields.Many2one(
        "fr.einvoicing.event",
        string="Event",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one("res.currency", readonly=True, required=True)
    amount = fields.Monetary(readonly=True)
    date = fields.Date(readonly=True)
