# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
#
# Official French e-invoicing directory (Chorus Pro):
# https://facturation.chorus-pro.gouv.fr/annuaire/
import csv
import io
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

# Map the status returned by the directory to the ``state`` field.
STATE_ALIASES = {
    "": "inactive",
    "enabled": "active",
    "active": "active",
    "registered": "active",
    "upcoming": "upcoming",
    "in_progress": "upcoming",
    "disabled": "disabled",
    "inactive": "inactive",
}
VALID_TYPES = ("siren", "siret", "routing_code", "suffix", "error")
BOOL_TRUE = {"1", "true", "vrai", "oui", "yes", "x", "o"}

# The State directory caps each deposited file at 5000 lines and 1 MB.
DIRECTORY_MAX_LINES = 5000
DIRECTORY_MAX_BYTES = 1_000_000


class FrDirectoryLine(models.Model):
    _inherit = "fr.directory.line"

    # ------------------------------------------------------------------
    # Export: CSV of SIREN numbers to deposit on the State directory
    # ------------------------------------------------------------------
    @api.model
    def _directory_export_siren_list(self, partners):
        """Return the ordered list of unique SIREN numbers of the partners."""
        sirens = []
        seen = set()
        for partner in partners:
            siren = partner._get_siren(raise_if_none=False)
            if siren and siren not in seen:
                seen.add(siren)
                sirens.append(siren)
        return sirens

    @api.model
    def _directory_export_siren_chunks(self, partners):
        """Return a list of CSV chunks (bytes), one SIREN per line, WITHOUT a
        header and with ``\\n`` line endings. Each chunk stays within the State
        directory limits (<= 5000 lines and <= 1 MB), splitting when needed."""
        chunks = []
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        lines = 0
        for siren in self._directory_export_siren_list(partners):
            if lines >= DIRECTORY_MAX_LINES or (
                buf.tell() + len(siren) + 1 > DIRECTORY_MAX_BYTES
            ):
                chunks.append(buf.getvalue().encode("utf-8"))
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator="\n")
                lines = 0
            writer.writerow([siren])
            lines += 1
        if lines:
            chunks.append(buf.getvalue().encode("utf-8"))
        return chunks

    @api.model
    def _directory_export_siren_csv(self, partners):
        """Return a single CSV (bytes) with every SIREN (no size limit).

        Kept for callers that do not care about the directory 5000-lines / 1 MB
        deposit limits; the wizard uses :meth:`_directory_export_siren_chunks`.
        """
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        for siren in self._directory_export_siren_list(partners):
            writer.writerow([siren])
        return out.getvalue().encode("utf-8")

    # ------------------------------------------------------------------
    # Import: directory return CSV -> create/update directory lines
    # ------------------------------------------------------------------
    @api.model
    def _directory_import_csv(self, content):
        """Create/update directory lines from the directory return CSV.

        Understands the Chorus Pro directory export (columns "SIREN" and
        "Adresse de facturation" / "Adresse de facturation active") as well as
        a canonical format (siren, siret, identifier, routing_code, state...).
        Each row is matched to its commercial partner by SIREN and upserted by
        (partner, identifier), like the native API sync. The delimiter (``,``
        or ``;``) is auto-detected.
        """
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        sample = text[:2000]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise UserError(_("Empty or unreadable CSV file."))
        cols = self._directory_detect_columns(reader.fieldnames)
        if "siren" not in cols:
            raise UserError(_(
                "No SIREN column found. Columns: %s",
                ", ".join(reader.fieldnames),
            ))

        index = self._directory_partner_index()
        created = updated = skipped = ambiguous = 0
        errors = []
        affected = set()
        synced = set()
        for line_no, row in enumerate(reader, start=2):
            siren = (row.get(cols["siren"]) or "").strip().replace(" ", "")
            if not siren.isdigit() or len(siren) != 9:
                skipped += 1
                continue
            vals = self._directory_row_to_vals(row, cols, siren)
            partner, issue = self._directory_match_partner(
                siren, vals.get("siret"), index
            )
            if not partner:
                skipped += 1
                errors.append(
                    _("Row %(n)s: no partner found for SIREN %(s)s.",
                      n=line_no, s=siren)
                )
                continue
            if issue == "ambiguous":
                ambiguous += 1
                errors.append(
                    _("Row %(n)s: SIREN %(s)s is shared by several companies — "
                      "linked to %(p)s.", n=line_no, s=siren, p=partner.display_name)
                )
            synced.add(partner.id)
            existing = self.with_context(active_test=False).search(
                [("partner_id", "=", partner.id),
                 ("identifier", "=", vals["identifier"])],
                limit=1,
            )
            if existing:
                wvals = {
                    key: value
                    for key, value in vals.items()
                    if key != "identifier"
                    and (existing[key] or False) != (value or False)
                }
                if wvals:
                    existing.sudo().write(wvals)
                    updated += 1
                    affected.add(partner.id)
            else:
                self.sudo().create(dict(vals, partner_id=partner.id))
                created += 1
                affected.add(partner.id)
        if synced:
            self._directory_mark_partners_registered(
                self.env["res.partner"].browse(list(synced))
            )
        logger.info(
            "Directory CSV import: %s created, %s updated, %s skipped, "
            "%s ambiguous.", created, updated, skipped, ambiguous,
        )
        return {
            "created": created, "updated": updated, "skipped": skipped,
            "ambiguous": ambiguous, "errors": errors,
            "partner_ids": list(affected),
        }

    @api.model
    def _directory_mark_partners_registered(self, partners):
        """Mark partners as present in the directory after a CSV import.

        The native module fills these partner-level fields during the API sync;
        the CSV import must do the same, otherwise the directory section on the
        partner (status, default line selector) stays hidden and BT-49 cannot
        resolve. Entity type defaults to ``private`` when not already set.
        """
        today = fields.Date.context_today(self)
        for partner in partners.commercial_partner_id:
            vals = {"fr_directory_last_sync_date": today}
            if not partner.fr_directory_entity_type:
                vals["fr_directory_entity_type"] = "private"
            siren = partner._get_siren(raise_if_none=False)
            if siren:
                vals["fr_directory_siren"] = siren
            siret = partner._get_siret(raise_if_none=False)
            if siret:
                vals["fr_directory_siret"] = siret
            # Convenience: when the partner ends up with a single active line and
            # no default set, use it as the default routing line (BT-49). The
            # field is a manual selector natively; the directory return usually
            # confirms one address per company, so this saves a manual pick.
            if not partner.default_fr_directory_line_id:
                active_lines = partner.fr_directory_line_ids
                if len(active_lines) == 1:
                    vals["default_fr_directory_line_id"] = active_lines.id
            partner.sudo().write(vals)

    @api.model
    def _directory_partner_index(self):
        """Index companies by SIREN and by SIRET for partner matching."""
        Partner = self.env["res.partner"]
        companies = Partner.with_context(active_test=False).search(
            [("is_company", "=", True)]
        )
        by_siren = {}
        by_siret = {}
        for partner in companies:
            siren = partner._get_siren(raise_if_none=False)
            if siren:
                by_siren[siren] = by_siren.get(siren, Partner) | partner
            siret = partner._get_siret(raise_if_none=False)
            if siret:
                by_siret.setdefault(siret, partner)
        return {"siren": by_siren, "siret": by_siret}

    @api.model
    def _directory_match_partner(self, siren, siret, index):
        """Return (commercial_partner, anomaly).

        Prefer the SIRET (disambiguates when several companies share a SIREN);
        otherwise match by SIREN. ``anomaly`` is 'ambiguous' when the SIREN maps
        to several distinct companies.
        """
        empty = self.env["res.partner"]
        if siret and siret in index["siret"]:
            return index["siret"][siret].commercial_partner_id, None
        partners = index["siren"].get(siren, empty)
        commercials = partners.commercial_partner_id
        if not commercials:
            return empty, "no_partner"
        if len(commercials) == 1:
            return commercials, None
        return commercials[0], "ambiguous"

    @api.model
    def _directory_detect_columns(self, fieldnames):
        """Map each column to a role (Chorus Pro or canonical format)."""
        cols = {}
        for src in fieldnames:
            low = (src or "").strip().lower()
            if low == "siren":
                cols["siren"] = src
            elif "adresse de facturation" in low and "active" in low:
                cols["active"] = src
            elif "adresse de facturation" in low:
                cols["identifier"] = src
            elif low in ("identifier", "adresse"):
                cols.setdefault("identifier", src)
            elif low in ("state", "etat", "état"):
                cols["state"] = src
            elif low == "siret":
                cols["siret"] = src
            elif low in ("routing_code", "code_routage", "code routage"):
                cols["routing_code"] = src
            elif low in ("routing_code_name", "libelle", "libellé"):
                cols["routing_code_name"] = src
            elif low in ("commitment_required", "engagement"):
                cols["commitment"] = src
        return cols

    @api.model
    def _directory_row_to_vals(self, row, cols, siren):
        """Turn a CSV row into fr.directory.line values."""
        def val(role):
            return (row.get(cols[role]) or "").strip() if role in cols else ""

        identifier = val("identifier") or siren
        rtype, siret, routing_code = self._directory_parse_identifier(
            identifier, siren
        )
        if "active" in cols:
            state = "active" if val("active").lower() in BOOL_TRUE else "disabled"
        elif "state" in cols:
            state = STATE_ALIASES.get(val("state").lower(), "active")
        else:
            state = "active"
        return {
            "identifier": identifier,
            "type": rtype,
            "siren": siren,
            "siret": (val("siret") or siret) or False,
            "routing_code": (val("routing_code") or routing_code) or False,
            "routing_code_name": val("routing_code_name") or False,
            "state": state,
            "commitment_required": (
                val("commitment").lower() in BOOL_TRUE if "commitment" in cols
                else False
            ),
        }

    @api.model
    def _directory_parse_identifier(self, identifier, siren):
        """Derive (type, siret, routing_code) from the identifier.

        Formats: SIREN | SIREN_SIRET | SIREN_SIRET_RoutingCode | SIREN_Suffix.
        The routing code may contain "_": it is whatever follows the SIRET.
        """
        parts = identifier.split("_")
        siret = routing_code = False
        if len(parts) == 1:
            return "siren", siret, routing_code
        second = parts[1]
        is_siret = len(second) == 14 and second.isdigit()
        if is_siret:
            siret = second
            if len(parts) == 2:
                return "siret", siret, routing_code
            routing_code = "_".join(parts[2:])
            return "routing_code", siret, routing_code
        # 2nd segment is not a SIRET => addressing suffix
        return "suffix", siret, routing_code
