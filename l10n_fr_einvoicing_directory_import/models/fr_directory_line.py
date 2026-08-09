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

# Partners processed per transaction during the import. Each batch is
# committed on its own: marking partners invalidates a stored compute on
# account.move, whose recompute would otherwise pile up over the entire
# invoice history and exhaust memory on a production-sized database.
DIRECTORY_IMPORT_BATCH = 200

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
    def _directory_import_csv(self, content):  # noqa: C901
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
            raise UserError(
                _("No SIREN column found. Columns: %s") % ", ".join(reader.fieldnames)
            )

        index = self._directory_partner_index()
        created = updated = skipped = ambiguous = 0
        errors = []
        affected = set()
        synced = set()

        # Pass 1 — parse the whole file and resolve partners, without touching
        # the database. A directory return holds one row per company: doing an
        # ORM search and a write per row costs one query each and re-triggers
        # the stored computes on res.partner every time, which blows past the
        # server's request time limit on real files (thousands of rows).
        parsed = []
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
                    _("Row %(n)s: no partner found for SIREN %(s)s.")
                    % {"n": line_no, "s": siren}
                )
                continue
            if issue == "ambiguous":
                ambiguous += 1
                errors.append(
                    _(
                        "Row %(n)s: SIREN %(s)s is shared by several companies — "
                        "linked to %(p)s."
                    )
                    % {"n": line_no, "s": siren, "p": partner.display_name}
                )
            synced.add(partner.id)
            parsed.append((partner, vals))

        # Pre-load every existing line of the partners involved in one query,
        # indexed by (partner, identifier) — the key used for the upsert.
        existing_map = {}
        if parsed:
            partner_ids = list({partner.id for partner, _vals in parsed})
            for line in self.with_context(active_test=False).search(
                [("partner_id", "in", partner_ids)]
            ):
                existing_map[(line.partner_id.id, line.identifier)] = line

        # Pass 2 — write in batches of partners, committing between each.
        #
        # Marking a partner as present in the directory invalidates the stored
        # `fr_einvoicing_required` on account.move, which depends on the
        # partner's entity type. Doing it for every partner in one transaction
        # makes Odoo recompute that field over the partner's whole invoice
        # history at flush time — on a production database (877k moves here)
        # the process runs out of memory. Committing per batch keeps each
        # recompute bounded and releases the cache as we go.
        #
        # Trade-off: the import is no longer atomic. That is deliberate — a
        # directory return is idempotent (upsert by partner + identifier), so
        # re-running it after a failure resumes where it stopped.
        Line = self.sudo().with_context(tracking_disable=True)
        by_partner = {}
        for partner, vals in parsed:
            by_partner.setdefault(partner.id, []).append(vals)
        all_partner_ids = list(by_partner)
        batches = range(0, len(all_partner_ids), DIRECTORY_IMPORT_BATCH)

        for offset in batches:
            batch_ids = all_partner_ids[offset : offset + DIRECTORY_IMPORT_BATCH]
            to_create = []
            write_groups = {}
            for partner_id in batch_ids:
                for vals in by_partner[partner_id]:
                    existing = existing_map.get((partner_id, vals["identifier"]))
                    if existing:
                        wvals = {
                            key: value
                            for key, value in vals.items()
                            if key != "identifier"
                            and (existing[key] or False) != (value or False)
                        }
                        if wvals:
                            write_groups.setdefault(
                                tuple(sorted(wvals.items(), key=lambda kv: kv[0])), []
                            ).append(existing.id)
                            updated += 1
                            affected.add(partner_id)
                    else:
                        to_create.append(dict(vals, partner_id=partner_id))
                        created += 1
                        affected.add(partner_id)
            for wvals_items, line_ids in write_groups.items():
                Line.browse(line_ids).write(dict(wvals_items))
            if to_create:
                Line.create(to_create)

            batch_synced = [pid for pid in batch_ids if pid in synced]
            if batch_synced:
                self._directory_mark_partners_registered(
                    self.env["res.partner"].browse(batch_synced)
                )

            # Flush, commit, then drop the cache: without this the recomputes
            # of the whole run pile up until the final flush.
            self.env.flush_all()
            self.env.cr.commit()
            self.env.invalidate_all()
            logger.info(
                "Directory CSV import: %s/%s partners processed.",
                min(offset + DIRECTORY_IMPORT_BATCH, len(all_partner_ids)),
                len(all_partner_ids),
            )
        logger.info(
            "Directory CSV import: %s created, %s updated, %s skipped, %s ambiguous.",
            created,
            updated,
            skipped,
            ambiguous,
        )
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "ambiguous": ambiguous,
            "errors": errors,
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
        # One write per partner would mean thousands of UPDATE plus as many
        # recomputes of the stored directory fields. Partners sharing the exact
        # same values are written together, and tracking is disabled so the
        # import doesn't fill the chatter.
        Partner = partners.sudo().with_context(tracking_disable=True)
        groups = {}
        for partner in Partner.commercial_partner_id:
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
            groups.setdefault(
                tuple(sorted(vals.items(), key=lambda kv: kv[0])), []
            ).append(partner.id)
        for vals_items, partner_ids in groups.items():
            Partner.browse(partner_ids).write(dict(vals_items))

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
        rtype, siret, routing_code = self._directory_parse_identifier(identifier, siren)
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
                val("commitment").lower() in BOOL_TRUE
                if "commitment" in cols
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
