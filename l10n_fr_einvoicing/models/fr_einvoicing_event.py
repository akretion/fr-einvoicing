# Copyright 2026 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools, Command
from odoo.exceptions import UserError
import base64
from datetime import datetime
import mimetypes
from pprint import pprint


import logging
logger = logging.getLogger(__name__)

try:
    from pyfrctc import generate_cdar
except (ImportError, IOError) as err:
    logger.debug('Cannot import pyfrctc. Error details below.')
    logger.debug(err)


class FrEinvoicingEvent(models.Model):
    _name = "fr.einvoicing.event"
    _description = "Invoice Event"
    _order = "move_id, datetime desc"
    _check_company_auto = True

    move_id = fields.Many2one("account.move", string="Invoice", readonly=True, check_company=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    datetime = fields.Datetime(readonly=True, string="Issue Date and Time", copy=False, default=fields.Datetime.now)
    date = fields.Date(required=True, readonly=True, string="Issue date", copy=False, default=fields.Date.context_today)
    status = fields.Selection("_status_selection", required=True, readonly=True)
    status_decoration = fields.Char(compute="_compute_status_decoration", store=True)
    flow_id = fields.Many2one("fr.einvoicing.flow", readonly=True, copy=False, check_company=True)
    flow_state = fields.Selection(related="flow_id.state", store=True, string="Flow State")
    infos = fields.Html(compute="_compute_details", store=True)
    currency_id = fields.Many2one('res.currency', compute="_compute_payments", store=True)
    amount = fields.Monetary(compute="_compute_payments", store=True)
    direction = fields.Selection([
        ('in', 'In'),
        ('out', 'Out'),
        ], required=True, readonly=True)
    detail_ids = fields.One2many('fr.einvoicing.event.detail', 'event_id', string="Reasons and Actions")
    payment_ids = fields.One2many('fr.einvoicing.event.payment', 'event_id', string="Payments")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "fr_einvoicing_event_attachment_rel",
        string="Attachments", readonly=True)
    state = fields.Selection([
        ('created', 'Created'),  # out
        ('done', 'Done'),  # in + out
        ('error', 'Error'),  # out
        ], default='created', readonly=True, required=True)
    out_error_details = fields.Text(string="Error Details", readonly=True)  # out only

    def _prepare_flow(self):
        self.ensure_one()
        data_dict = self._prepare_xml_data()
        xml_bytes = generate_cdar(data_dict)
        invoice = self.move_id
        if invoice.is_sale_document():
            flow_type = "CustomerInvoiceLC"
        elif invoice.is_purchase_document():
            flow_type = "SupplierInvoiceLC"
        else:
            raise
        filename_suffix = ""
        if invoice.state == "posted":
            filename_suffix = f"_{invoice.name.replace('/', '_')}"
        flow_vals = {
            'direction': 'out',
            'type': flow_type,
            "company_id": self.company_id.id,
            "syntax": "CDAR",
            "file_bin": base64.encodebytes(xml_bytes),
            "filename": f"cdar_{self.status}{filename_suffix}.xml",
            "processing_rule": "B2B",  # TODO
            }
        return flow_vals

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        if tools.config.get('running_env') != 'prod':
            events.process()
        return events

    def process(self):
        flow_obj = self.env['fr.einvoicing.flow']
        for event in self:
            if event.direction == "out":
                try:
                    flow_vals = event._prepare_flow()
                    flow = flow_obj.sudo().create(flow_vals)
                    if tools.config.get('running_env') != 'prod':
                        flow.send()
                except Exception as e:
                    event.sudo().write({
                        'state': 'error',
                        'out_error_details': f"Failed to generate CDAR XML file.\nError: {str(e)}",
                        })
                    continue
                event.sudo().write({'state': 'done', 'flow_id': flow.id, 'out_error_details': False})

    @api.depends('detail_ids.reason', 'detail_ids.comment')
    def _compute_details(self):
        reason2label = dict(self.env['fr.einvoicing.event.detail']._fields['reason']._description_selection(self.env))
        for event in self:
            info_list = [l._display_html(reason2label) for l in event.detail_ids]
            if event.attachment_ids:
                if len(event.attachment_ids) == 1:
                    prefix = self.env._("1 attachment:")
                else:
                    prefix = self.env._("%s attachments:", len(event.attachment_ids))
                info_list.append(f"<strong>{prefix}</strong> {', '.join([x.name for x in event.attachment_ids])}")
            event.infos = '<br/>'.join([x for x in info_list if x])

    @api.depends('payment_ids.amount', 'payment_ids.currency_id')
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

    @api.depends('status')
    def _compute_status_decoration(self):
        for event in self:
            decoration = False
            if event.status:
                vals = self._from_code_str(event.status)
                decoration = vals.get("decoration")
            event.status_decoration = decoration

    # TODO move to pyfrctc ?
    @api.model
    def _get_all_status(self):
        res = {
            "200": {
                'label': self.env._("Submitted"),  # Déposée
                "str_code": "submitted",
                "decoration": "muted",
                },
            "201": {
                'label': self.env._('Issued by the Platform'),  # Emise par la plateforme (PAe)
                "str_code": "ap_sent",
                "decoration": "muted",
                },
            "202": {
                "label": self.env._("Received by the Platform"),  # Reçue par la plateforme (PAr)
                "str_code": "ap_received",
                "decoration": "muted",
                },
            "203": {
                "label": self.env._("Made Available"),  # Mise à disposition  (PAr)
                "str_code": "ap_available",
                "decoration": "muted",
                },
            "204": {
                "label": self.env._("In Hand"),  # Prise en charge
                # In Invoice: auto-set by Odoo when creating the draft supplier invoice
                "str_code": "in_hand",
                "MDT-88": "45",
                "decoration": "info",
                },
            "205": {
                "label": self.env._("Approved"),  # Approuvée
                "manual": "purchase",
                # In Invoice: auto-set by Odoo when confirming the invoice ? or manual set ?
                "str_code": "approved",
                "MDT-88": "1",
                "decoration": "success",
                },
            "206": {
                "label": self.env._("Partially Approved"),  # Approuvée partiellement
                "manual": False,  # should be true, but I don't see how to support it
                "str_code": "partially_approved",
                "detail_required": True,
                "MDT-88": "49",
                "decoration": "warning",
                },
            "207": {
                "label": self.env._("Disputed"),  # En litige
                "manual": "purchase",
                "str_code": "dispute",
                "detail_required": True,
                "MDT-88": "46",
                "decoration": "warning",
                },
            "208": {
                "label": self.env._("Suspended"),  # Suspendue
                "manual": "purchase",
                "str_code": "suspended",
                "detail_required": True,
                "MDT-88": "39",
                "decoration": "warning",
                },
            "209": {
                "label": self.env._("Completed"),  # Complétée
                "manual": "sale",  # TODO filter on out_invoice
                "str_code": "completed",
                "MDT-88": "37",
                "decoration": "info",
                },
            "210": {
                "label": self.env._("Refused"),
                # In Invoice: auto-set by Odoo when cancelling the invoice ?
                "manual": "purchase",
                "str_code": "refused",
                "detail_required": True,
                "confirm_required": True,
                "MDT-88": "50",
                "decoration": "danger",
                },
            "211": {
                "label": self.env._("Payment Sent"),
                # In Invoice: auto-set by Odoo when payment_state in ('paid', 'in_payment')
                "str_code": "payment_sent",
                "MDT-88": "47",
                "decoration": "success",
                },
            "212": {
                "label": self.env._("Payment Received"),
                # Out invoice: auto-set by Odoo when payment_state == "Paid" ?
                "str_code": "payment_received",
                "MDT-88": "47",
                "decoration": "success",
                },
            "213": {
                "label": self.env._("Rejected"),  # Rejeté
                # Technical status set by PA
                "str_code": "rejected",
                "decoration": "danger",
                },
            # "214": {  # Need another label in English
            #    "label": self.env._("Approved"),  # Visée
            #    },
            "220": {
                "label": self.env._("Cancelled"),  # Annulée (pour facture rectif)
                "str_code": "cancelled",
                "decoration": "danger",
                },
            }
        unique_str_code = set()
        required_values = ("label", "str_code")
        for key, vals in res.items():
            for required_value in required_values:
                if not vals.get(required_value):
                    raise RuntimeError(f"Error in status database: missing '{required_value}' for code '{key}'")
            str_code = vals["str_code"]
            if str_code in unique_str_code:
                raise RuntimeError(f"Error in status database: str_code {str_code} is not unique.")
            unique_str_code.add(str_code)
        return res

    @api.model
    def _status_selection(self):
        res = self._get_all_status()
        sel = []
        for vals in res.values():
            sel.append((vals['str_code'], vals['label']))
        return sel

    @api.model
    def _status_selection_manual(self, sale_or_purchase):
        res = self._get_all_status()
        sel = []
        for vals in res.values():
            if vals.get('manual') == sale_or_purchase:
                sel.append((vals['str_code'], vals['label']))
        return sel

    @api.model
    def _from_code_str(self, str_code, raise_if_not_found=True):
        res = self._get_all_status()
        str_code2vals = {}
        for code, vals in res.items():
            vals['code'] = code
            key = vals.pop('str_code')
            str_code2vals[key] = vals
        if str_code not in str_code2vals and raise_if_not_found:
            raise UserError(self.env._("Code %s doesn't exist. This should never happen.", str_code))
        return str_code2vals.get(str_code)

    @api.model
    def _get_str_code(self, code, raise_if_not_found=True):
        res = self._get_all_status()
        if code not in res and raise_if_not_found:
            raise UserError(self.env._("Code %s is unknown. This should never happen.", code))
        return res[code]['str_code']

    def _prepare_xml_data(self):
        self.ensure_one()
        assert self.status
        status = self.status
        invoice = self.move_id
        logger.info('Preparing XML for event %s linked to invoice %s', self.display_name, invoice.display_name)
        date_fmt = {
            102: '%Y%m%d',
            204: '%Y%m%d%H%M%S',
            }
        company_siren = invoice.company_id.partner_id._get_siren(raise_if_none=True)
        company_name = invoice.company_id.name
        partner_siren = invoice.commercial_partner_id._get_siren(raise_if_none=True)
        partner_name = invoice.commercial_partner_id.name
        assert invoice.invoice_date
        inv_date_str = invoice.invoice_date.strftime(date_fmt[102])  # TODO handle case where invoice_date is empty

        if invoice.is_sale_document():
            sender_role_code = 'SE'  # seller
            recipient_role_code = "BY"  # buyer
            inv_number = invoice.name
            issuer_siren = company_siren
        elif invoice.is_purchase_document():
            sender_role_code = "BY"
            recipient_role_code = 'SE'
            inv_number = invoice.ref  # TODO check
            issuer_siren = partner_siren
        else:
            raise
        inv_type_code = "380"  # TODO
        if invoice.move_type in ('out_refund', 'in_refund'):
            inv_type_code = "381"
        if not invoice.partner_id:
            raise UserError(self.env._("Partner is not set on invoice %s", invoice.display_name))
        if not invoice.fr_directory_line_id:
            raise UserError(self.env._("Directory line is not set on invoice %s", invoice.display_name))

        datetime_utc = fields.Datetime.now()  # TODO convert to local time ?
        now_str = datetime.strftime(datetime_utc, date_fmt[204])

        status_dict = self._from_code_str(status)
        identifier = f"{inv_number}_{inv_type_code}_{inv_date_str}#{status_dict['code']}_{now_str}"
        data_dict = {
            'MDT-2': 'REGULATED',
            'MDT-3': 'urn.cpro.gouv.fr:1p0:CDV:invoice',
            'MDT-4': identifier,
#            'MDT-5': # optional  'Name',  # optional
            'MDT-8': now_str,  # timezone
            'MDT-21': sender_role_code,  # Sender Trade Party/Role Code
            'MDT-38': company_siren,  # SIREN Issuer
            'MDT-39': company_name,
            'MDT-40': sender_role_code,  # Issuer Trade Party/Role Code
            'MDT-57': partner_siren,
            'MDT-58': partner_name,  # name of the destinee
            'MDT-59': recipient_role_code,
            'MDT-73': invoice.fr_directory_line_id.identifier,  # TODO set on import
            "MDT-74": False,
            "MDT-77": 23,  # 23 : Information - pour les statuts après transmission
            "MDT-78": now_str,  # TODO heure de dépôt
            "MDT-87": inv_number,
            "MDT-95": datetime.strftime(invoice.fr_einvoicing_flow_id.create_date, date_fmt[204]),  # TODO
            "MDT-88": status_dict['MDT-88'],
            "MDT-91": inv_type_code,
            "MDT-100": inv_date_str,
            'MDT-105': status_dict['code'],
            'MDT-106': status_dict['label'],
            'MDT-129': issuer_siren,
            'MDG-37': [],  # doc_status
        }
        reason2label = dict(self.env['fr.einvoicing.event.detail']._fields['reason']._description_selection(self.env))
        action2label = dict(self.env['fr.einvoicing.event.detail']._fields['action']._description_selection(self.env))
        for detail in self.detail_ids:
            detailed_data = {
                "MDT-113": detail.reason,
                "MDT-114": reason2label[detail.reason],
                }
            if detail.action:
                detailed_data.update({
                    "MDT-121": detail.action,
                    "MDT-122": action2label[detail.action],
                    })
            if detail.comment:
                detailed_data["MDT-126"] = detail.comment
            data_dict['MDG-37'].append(detailed_data)
        if status == "payment_sent":
            # PB LISTE
            doc_characteristics = []
            for payment in self.payment_ids:
                doc_characteristics.append({
                    'MDT-207': 'MPA',
                    'MDT-209': False,
                    'MDT-215': {'float': payment.amount, 'currency': payment.currency_id.name},  # TODO format-
                    'MDT-219': payment.date and payment.date.strftime(date_fmt[102]) or False,
                    })
            if doc_characteristics:
                data_dict['MDG-37'].append({'MDG-43': doc_characteristics})
        MDT96 = []
        for attachment in self.attachment_ids:
            mime_res = mimetypes.guess_type(attachment.name)
            print('mime_res=', mime_res)
            MDT96.append({'bin': attachment.raw, 'filename': attachment.name, 'mime_type': mime_res and mime_res[0] or "unknown"})
        if MDT96:
            data_dict['MDT-96'] = MDT96
        pprint(data_dict)
        return data_dict

    @api.depends('status')
    def _compute_display_name(self):
        for rec in self:
            dname = False
            if rec.status:
                dname = self._from_code_str(rec.status)['label']  # TODO bof
            rec.display_name = dname


class FrEinvoicingEventDetail(models.Model):
    _name = "fr.einvoicing.event.detail"
    _description = "Invoice Event Detail"

    event_id = fields.Many2one('fr.einvoicing.event', string="Event", required=True, readonly=True, ondelete='cascade')
    # reasons and comment are required in the view, to avoid errors if they are not set on an incoming
    # event
    reason = fields.Selection("_reason_selection", readonly=True)
    action = fields.Selection("_action_selection", readonly=True)
    comment = fields.Text(readonly=True)

    @api.model
    def _reason_selection(self):
        res = [
            ('JUSTIF_ABS', 'Justificatif absent ou insuffisant'),
            ('ROUTAGE_ERR', 'Erreur de routage'),
            ('AUTRE', 'Autre'),
            ('COORD_BANC_ERR', 'Erreur de coordonnées bancaires'),
            ('TX_TVA_ERR', 'Taux de TVA erroné'),
            ('MONTANTTOTAL_ERR', 'Montant total érroné'),
            ('CALCUL_ERR', 'Erreur de calcul de la facture'),
            ('NON_CONFORME', 'Mention légale manquante'),
            ('DOUBLON', 'Facture en doublon (déjà émise / reçue)'),
            ('DEST_INC', 'Destinataire inconnu'),
            ('DEST_ERR', 'Erreur de destinataire'),
            ('TRANSAC_INC', 'Transaction inconnue'),
            ('EMMET_INC', 'Émetteur inconnu'),
            ('CONTRAT_TERM', 'Contrat terminé'),
            ('DOUBLE_FACT', 'Déjà facturé sur autre facture'),
            ('CMD_ERR', 'N° de commande incorrect ou manquant'),
            ('ADR_ERR', "Adresse de facturation électronique erronée"),
            ('SIRET_ERR', 'SIRET Erroné ou absent'),
            ('CODE_ROUTAGE_ERR', 'Code routage absent ou erroné'),
            ('REF_CT_ABSENT', 'Référence contractuelle nécessaire pour le traitement de la facture manquante'),
            ('REF_ERR', 'Référence incorrecte'),
            ('PU_ERR', 'Prix unitaires incorrects'),
            ('REM_ERR', 'Remise erronée'),
            ('QTE_ERR', 'Quantité facturée incorrecte'),
            ('ART_ERR', 'Article facturé incorrect'),
            ('MODPAI_ERR', 'Modalités de paiement incorrectes'),
            ('QUALITE_ERR', "Qualité d'article livré incorrecte"),
            ('LIVR_INCOMP', 'Problème de livraison'),
# But may be needed for incoming events
# We'll do like for status:
            ('REJ_SEMAN', 'Rejet pour erreur sémantique'),
            ('REJ_UNI', 'Rejet sur contrôle unicité'),
            ('REJ_COH', 'Rejet sur contrôle Cohérence de données'),
            ('REJ_ADR', "Rejet sur Contrôle d'adressage"),
            ('REJ_CONT_B2G', "Rejet sur Contrôles métier B2G"),
            ('REJ_REF_PJ', "Rejet sur Référence de PJ"),
            ("REJ_ASS_PJ", "Rejet sur Erreur d'association de la PJ"),
            ('IRR_VIDE_F', "Contrôle de non vide sur les fichiers du flux"),
            ('IRR_TYPE_F', "Contrôle de type et extension des fichiers du flux"),
            ('IRR_SYNTAX', "Contrôle syntaxique des fichiers du flux"),
            ('IRR_TAILLE_PJ', "Contrôle de taille des PJ de chaque fichier du flux"),
            ('IRR_NOM_PJ', "Contrôle du nom des PJ de chaque fichier du flux (absence de caractères interdits)"),
            ('IRR_VID_PJ', "Contrôle de PJ non vide de chaque fichier du flux"),
            ('IRR_EXT_DOC', "Contrôle de l'extension des PJ de chaque fichier du flux"),
            ('IRR_TAILLE_F', "Contrôle de taille max des fichiers contenus dans le flux"),
            ('IRR_ANTIVIRUS', 'Contrôle anti-virus'),
        ]

        return res

    @api.model
    def _action_selection(self):
        res = [
            # list available in English
            ('NOA', 'Aucune Action Requise'),
            ('PIN', 'Information complémentaire requise'),
            ('NIN', 'Créer une Facture Rectificative'),
            ('CNF', 'Créer un Avoir total'),
            ('CNP', 'Créer un Avoir Partiel'),
            ('CNA', 'Rembourser le paiement de la facture'),
            ('OTH', 'Autre'),
            ]
        return res

    def _display_html(self, reason2label):
        self.ensure_one()
        res = []
        if self.reason:
            reason2label = dict(self._fields['reason']._description_selection(self.env))
            print('reason2label=', reason2label)
            reason_field_label = self.env._('Reason:')
            res.append(f"<strong>{reason_field_label}</strong> {reason2label[self.reason]}")
        if self.comment:
            comment_field_label = self.env._('Comment:')
            res.append(f"<strong>{comment_field_label}</strong> {self.comment}")
        return ' '.join(res)


class FrEinvoicingEventPayment(models.Model):
    _name = "fr.einvoicing.event.payment"
    _description = "Invoice Event Payment"

    event_id = fields.Many2one('fr.einvoicing.event', string="Event", required=True, readonly=True, ondelete='cascade')
    currency_id = fields.Many2one("res.currency", readonly=True, required=True)
    amount = fields.Monetary(readonly=True)
    date = fields.Date(readonly=True)
