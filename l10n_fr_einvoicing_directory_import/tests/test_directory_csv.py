# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
#
# Plain TransactionCase on purpose: the from-source Odoo images used to run
# these modules strip the `tests/` directories of the standard addons, so
# helpers such as odoo.addons.account.tests.common are not importable.
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

# SIREN and SIRET with valid checksums: l10n_fr_siret rejects anything else,
# and _get_siren() silently returns None for an invalid SIREN.
SIREN_A = "100000009"
SIRET_A = "10000000900009"
SIREN_B = "100000017"
SIRET_B = "10000001700002"
SIREN_C = "100000025"


class TestDirectoryCsv(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env["fr.directory.line"]
        cls.Partner = cls.env["res.partner"]
        cls.partner_a = cls.Partner.create({
            "name": "Directory Test A",
            "is_company": True,
            "siren": SIREN_A,
            "nic": SIRET_A[9:],
        })
        cls.partner_b = cls.Partner.create({
            "name": "Directory Test B",
            "is_company": True,
            "siren": SIREN_B,
            "nic": SIRET_B[9:],
        })

    # ------------------------------------------------------------------
    # Identifier parsing
    # ------------------------------------------------------------------
    def test_parse_identifier_siren_only(self):
        self.assertEqual(
            self.Line._directory_parse_identifier(SIREN_A, SIREN_A),
            ("siren", False, False),
        )

    def test_parse_identifier_siret(self):
        identifier = f"{SIREN_A}_{SIRET_A}"
        self.assertEqual(
            self.Line._directory_parse_identifier(identifier, SIREN_A),
            ("siret", SIRET_A, False),
        )

    def test_parse_identifier_routing_code(self):
        identifier = f"{SIREN_A}_{SIRET_A}_SERVICE1"
        self.assertEqual(
            self.Line._directory_parse_identifier(identifier, SIREN_A),
            ("routing_code", SIRET_A, "SERVICE1"),
        )

    def test_parse_identifier_routing_code_keeps_underscores(self):
        """The routing code is everything after the SIRET, underscores included."""
        identifier = f"{SIREN_A}_{SIRET_A}_SERVICE_COMPTA_2"
        self.assertEqual(
            self.Line._directory_parse_identifier(identifier, SIREN_A),
            ("routing_code", SIRET_A, "SERVICE_COMPTA_2"),
        )

    def test_parse_identifier_suffix(self):
        """A second segment that is not a 14-digit SIRET is an addressing suffix."""
        self.assertEqual(
            self.Line._directory_parse_identifier(f"{SIREN_A}_ABC", SIREN_A),
            ("suffix", False, False),
        )

    # ------------------------------------------------------------------
    # Column detection
    # ------------------------------------------------------------------
    def test_detect_columns_chorus_pro(self):
        cols = self.Line._directory_detect_columns(
            ["SIREN", "Adresse de facturation", "Adresse de facturation active"]
        )
        self.assertEqual(cols["siren"], "SIREN")
        self.assertEqual(cols["identifier"], "Adresse de facturation")
        self.assertEqual(cols["active"], "Adresse de facturation active")

    def test_detect_columns_canonical(self):
        cols = self.Line._directory_detect_columns(
            ["siren", "siret", "identifier", "routing_code", "state", "engagement"]
        )
        self.assertEqual(cols["siret"], "siret")
        self.assertEqual(cols["identifier"], "identifier")
        self.assertEqual(cols["routing_code"], "routing_code")
        self.assertEqual(cols["state"], "state")
        self.assertEqual(cols["commitment"], "engagement")

    def test_detect_columns_ignores_unknown(self):
        cols = self.Line._directory_detect_columns(["SIREN", "Raison sociale"])
        self.assertEqual(cols, {"siren": "SIREN"})

    # ------------------------------------------------------------------
    # Row -> values
    # ------------------------------------------------------------------
    def test_row_to_vals_inactive_address(self):
        """Chorus Pro answers 'present but inactive' for most companies."""
        cols = {"siren": "SIREN", "identifier": "Adresse",
                "active": "Adresse active"}
        vals = self.Line._directory_row_to_vals(
            {"SIREN": SIREN_A, "Adresse": f"{SIREN_A}_{SIRET_A}",
             "Adresse active": "0"},
            cols, SIREN_A,
        )
        self.assertEqual(vals["state"], "disabled")
        self.assertEqual(vals["type"], "siret")
        self.assertEqual(vals["siret"], SIRET_A)

    def test_row_to_vals_active_address(self):
        cols = {"siren": "SIREN", "identifier": "Adresse",
                "active": "Adresse active"}
        vals = self.Line._directory_row_to_vals(
            {"SIREN": SIREN_A, "Adresse": SIREN_A, "Adresse active": "oui"},
            cols, SIREN_A,
        )
        self.assertEqual(vals["state"], "active")
        self.assertEqual(vals["type"], "siren")

    def test_row_to_vals_state_alias(self):
        cols = {"siren": "siren", "state": "state"}
        vals = self.Line._directory_row_to_vals(
            {"siren": SIREN_A, "state": "in_progress"}, cols, SIREN_A
        )
        self.assertEqual(vals["state"], "upcoming")

    def test_row_to_vals_defaults_to_siren_identifier(self):
        """Without an identifier column the SIREN itself is the identifier."""
        vals = self.Line._directory_row_to_vals(
            {"siren": SIREN_A}, {"siren": "siren"}, SIREN_A
        )
        self.assertEqual(vals["identifier"], SIREN_A)
        self.assertEqual(vals["state"], "active")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def test_export_siren_list_dedupes(self):
        partners = self.partner_a | self.partner_b | self.partner_a
        self.assertEqual(
            self.Line._directory_export_siren_list(partners),
            [SIREN_A, SIREN_B],
        )

    def test_export_siren_list_skips_partners_without_siren(self):
        no_siren = self.Partner.create({"name": "No SIREN", "is_company": True})
        self.assertEqual(
            self.Line._directory_export_siren_list(self.partner_a | no_siren),
            [SIREN_A],
        )

    def test_export_siren_csv_has_no_header(self):
        csv_bytes = self.Line._directory_export_siren_csv(self.partner_a)
        self.assertEqual(csv_bytes, (SIREN_A + "\n").encode("utf-8"))

    def test_export_chunks_split_on_line_limit(self):
        """The State directory caps each deposited file at 5000 lines."""
        sirens = [str(100000000 + i) for i in range(12000)]
        self.patch(
            type(self.Line), "_directory_export_siren_list",
            lambda self, partners: sirens,
        )
        chunks = self.Line._directory_export_siren_chunks(self.partner_a)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].count(b"\n"), 5000)
        self.assertEqual(chunks[1].count(b"\n"), 5000)
        self.assertEqual(chunks[2].count(b"\n"), 2000)

    def test_export_chunks_single_file_below_limits(self):
        chunks = self.Line._directory_export_siren_chunks(
            self.partner_a | self.partner_b
        )
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], f"{SIREN_A}\n{SIREN_B}\n".encode("utf-8"))

    # ------------------------------------------------------------------
    # Partner matching
    # ------------------------------------------------------------------
    def test_match_partner_prefers_siret(self):
        """A SIRET disambiguates companies sharing a SIREN."""
        twin = self.Partner.create({
            "name": "Directory Test A bis", "is_company": True,
            "siren": SIREN_A, "nic": "00017",
        })
        index = self.Line._directory_partner_index()
        partner, issue = self.Line._directory_match_partner(
            SIREN_A, "10000000900017", index
        )
        self.assertEqual(partner, twin)
        self.assertFalse(issue)

    def test_match_partner_reports_ambiguous_siren(self):
        self.Partner.create({
            "name": "Directory Test A bis", "is_company": True,
            "siren": SIREN_A, "nic": "00017",
        })
        index = self.Line._directory_partner_index()
        partner, issue = self.Line._directory_match_partner(SIREN_A, None, index)
        self.assertEqual(issue, "ambiguous")
        self.assertTrue(partner)

    def test_match_partner_unknown_siren(self):
        index = self.Line._directory_partner_index()
        partner, issue = self.Line._directory_match_partner(SIREN_C, None, index)
        self.assertFalse(partner)
        self.assertEqual(issue, "no_partner")

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def _import(self, text):
        return self.Line._directory_import_csv(text.encode("utf-8"))

    def test_import_creates_lines(self):
        res = self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
            f"{SIREN_B};{SIREN_B};0\n"
        )
        self.assertEqual(res["created"], 2)
        self.assertEqual(res["skipped"], 0)
        line = self.Line.with_context(active_test=False).search([
            ("partner_id", "=", self.partner_a.id),
        ])
        self.assertEqual(line.identifier, f"{SIREN_A}_{SIRET_A}")
        self.assertEqual(line.state, "active")
        self.assertEqual(line.siret, SIRET_A)

    def test_import_is_idempotent(self):
        """Upsert on (partner, identifier): the batched import is not atomic,
        so re-running a failed file must not duplicate lines."""
        csv_text = (
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        self._import(csv_text)
        res = self._import(csv_text)
        self.assertEqual(res["created"], 0)
        self.assertEqual(res["updated"], 0)
        self.assertEqual(
            self.Line.with_context(active_test=False).search_count(
                [("partner_id", "=", self.partner_a.id)]
            ),
            1,
        )

    def test_import_updates_changed_state(self):
        base = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(base + f"{SIREN_A};{SIREN_A};0\n")
        res = self._import(base + f"{SIREN_A};{SIREN_A};1\n")
        self.assertEqual(res["updated"], 1)
        line = self.Line.with_context(active_test=False).search(
            [("partner_id", "=", self.partner_a.id)]
        )
        self.assertEqual(line.state, "active")

    def test_import_marks_partner_registered(self):
        """Without these partner fields the directory section stays hidden and
        BT-49 cannot resolve."""
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(self.partner_a.fr_directory_entity_type, "private")
        self.assertTrue(self.partner_a.fr_directory_last_sync_date)
        self.assertEqual(self.partner_a.fr_directory_siren, SIREN_A)

    def test_import_sets_single_active_line_as_default(self):
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(
            self.partner_a.default_fr_directory_line_id.identifier, SIREN_A
        )

    def test_import_skips_unknown_and_malformed_siren(self):
        res = self._import(
            "SIREN;Adresse de facturation\n"
            f"{SIREN_C};{SIREN_C}\n"       # valid but no partner
            "12345;12345\n"                 # not 9 digits
            f"{SIREN_A};{SIREN_A}\n"
        )
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["skipped"], 2)
        self.assertTrue(any(SIREN_C in err for err in res["errors"]))

    def test_import_detects_comma_delimiter(self):
        res = self._import(
            "SIREN,Adresse de facturation,Adresse de facturation active\n"
            f"{SIREN_A},{SIREN_A},1\n"
        )
        self.assertEqual(res["created"], 1)

    def test_import_accepts_utf8_bom(self):
        res = self.Line._directory_import_csv(
            ("SIREN;Adresse de facturation\n" f"{SIREN_A};{SIREN_A}\n")
            .encode("utf-8-sig")
        )
        self.assertEqual(res["created"], 1)

    def test_import_without_siren_column_raises(self):
        with self.assertRaises(UserError):
            self._import("Raison sociale;Adresse\nACME;whatever\n")

    def test_import_empty_file_raises(self):
        with self.assertRaises(UserError):
            self._import("")

    def test_import_reports_ambiguous_siren(self):
        self.Partner.create({
            "name": "Directory Test A bis", "is_company": True,
            "siren": SIREN_A, "nic": "00017",
        })
        res = self._import(
            "SIREN;Adresse de facturation\n" f"{SIREN_A};{SIREN_A}\n"
        )
        self.assertEqual(res["ambiguous"], 1)
        self.assertTrue(any("shared by several" in err for err in res["errors"]))


class TestDirectoryCsvWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Wizard Test", "is_company": True,
            "siren": SIREN_A, "nic": SIRET_A[9:],
        })

    def test_export_uses_active_ids(self):
        wizard = self.env["fr.directory.csv.wizard"].with_context(
            active_ids=self.partner.ids
        ).create({"only_missing": False})
        wizard.action_export_siren()
        self.assertEqual(wizard.export_filename, "directory_siren.csv")
        self.assertTrue(wizard.export_file)

    def test_export_only_missing_excludes_registered_partners(self):
        """A partner already holding a line — even a disabled one — is
        registered in the directory and must not be deposited again."""
        self.env["fr.directory.line"].create({
            "partner_id": self.partner.id, "identifier": SIREN_A,
            "type": "siren", "siren": SIREN_A, "state": "disabled",
        })
        wizard = self.env["fr.directory.csv.wizard"].with_context(
            active_ids=self.partner.ids
        ).create({"only_missing": True})
        with self.assertRaises(UserError):
            wizard.action_export_siren()

    def test_import_requires_a_file(self):
        wizard = self.env["fr.directory.csv.wizard"].create({})
        with self.assertRaises(UserError):
            wizard.action_import()
