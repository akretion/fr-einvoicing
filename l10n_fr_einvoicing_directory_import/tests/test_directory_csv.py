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


class DirectoryCase(TransactionCase):
    def setUp(self):
        super().setUp()
        # _directory_import_csv() commits between batches on purpose (a single
        # transaction would pile up the account.move recomputes until it runs
        # out of memory). Inside a test that commit releases the savepoint
        # TransactionCase rolls back to, which aborts the whole run. Neutralise
        # the commit only: the flush that precedes it still writes the rows.
        #
        # 19.0 patches `commit` on the cursor *instance* (see the `forbidden`
        # helper in odoo/tests/common.py), which shadows any patch set on the
        # class, so the instance is what has to be patched here.
        self.patch(self.env.cr, "commit", lambda: None)


class TestDirectoryCsv(DirectoryCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env["fr.directory.line"]
        cls.Partner = cls.env["res.partner"]
        cls.partner_a = cls.Partner.create(
            {
                "name": "Directory Test A",
                "is_company": True,
                "company_registry": SIRET_A,
                "country_id": cls.env.ref("base.fr").id,
            }
        )
        cls.partner_b = cls.Partner.create(
            {
                "name": "Directory Test B",
                "is_company": True,
                "company_registry": SIRET_B,
                "country_id": cls.env.ref("base.fr").id,
            }
        )

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
        cols = {"siren": "SIREN", "identifier": "Adresse", "active": "Adresse active"}
        vals = self.Line._directory_row_to_vals(
            {
                "SIREN": SIREN_A,
                "Adresse": f"{SIREN_A}_{SIRET_A}",
                "Adresse active": "0",
            },
            cols,
            SIREN_A,
        )
        self.assertEqual(vals["state"], "disabled")
        self.assertEqual(vals["type"], "siret")
        self.assertEqual(vals["siret"], SIRET_A)

    def test_row_to_vals_active_address(self):
        cols = {"siren": "SIREN", "identifier": "Adresse", "active": "Adresse active"}
        vals = self.Line._directory_row_to_vals(
            {"SIREN": SIREN_A, "Adresse": SIREN_A, "Adresse active": "oui"},
            cols,
            SIREN_A,
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
            type(self.Line),
            "_directory_export_siren_list",
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
    def _create_twin(self):
        """A second company sharing SIREN_A: the duplicate-record situation the
        fan-out addresses."""
        return self.Partner.create(
            {
                "name": "Directory Test A bis",
                "is_company": True,
                "company_registry": SIREN_A + "00017",
                "country_id": self.env.ref("base.fr").id,
            }
        )

    def test_match_partners_fans_out_on_shared_siren(self):
        twin = self._create_twin()
        index = self.Line._directory_partner_index()
        partners, issue = self.Line._directory_match_partners(SIREN_A, None, index)
        self.assertEqual(partners, self.partner_a | twin)
        self.assertEqual(issue, "ambiguous")

    def test_match_partners_siret_row_covers_every_twin(self):
        """Fan-out is unconditional: a row carrying a SIRET still lands on every
        company sharing the SIREN, not only on the SIRET holder."""
        twin = self._create_twin()
        index = self.Line._directory_partner_index()
        partners, issue = self.Line._directory_match_partners(
            SIREN_A, "10000000900017", index
        )
        self.assertEqual(partners, self.partner_a | twin)
        self.assertEqual(issue, "ambiguous")

    def test_match_partners_single_company_has_no_anomaly(self):
        index = self.Line._directory_partner_index()
        partners, issue = self.Line._directory_match_partners(SIREN_B, None, index)
        self.assertEqual(partners, self.partner_b)
        self.assertFalse(issue)

    def test_match_partners_falls_back_to_siret_when_siren_unknown(self):
        """The SIREN column and the SIRET of the identifier can disagree in a
        directory return; the SIRET still finds the company."""
        index = self.Line._directory_partner_index()
        partners, issue = self.Line._directory_match_partners(
            SIREN_C, SIRET_B, index
        )
        self.assertEqual(partners, self.partner_b)
        self.assertFalse(issue)

    def test_match_partners_unknown_siren(self):
        index = self.Line._directory_partner_index()
        partners, issue = self.Line._directory_match_partners(SIREN_C, None, index)
        self.assertFalse(partners)
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
        line = self.Line.with_context(active_test=False).search(
            [
                ("partner_id", "=", self.partner_a.id),
            ]
        )
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

    def test_import_marks_public_entity(self):
        """The directory return has no entity type: the Chorus Pro default
        service code is what tells a public entity apart."""
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A}_FACTURES_PUBLIQUES;1\n"
            f"{SIREN_B};{SIREN_B};1\n"
        )
        (self.partner_a | self.partner_b).invalidate_recordset()
        self.assertEqual(self.partner_a.fr_directory_entity_type, "public")
        self.assertEqual(self.partner_a.fr_directory_siret, SIRET_A)
        self.assertEqual(self.partner_b.fr_directory_entity_type, "private")

    def test_import_fixes_public_entity_made_private(self):
        """Earlier imports defaulted every partner to private."""
        self.partner_a.write({
            "fr_directory_entity_type": "private",
            "fr_directory_last_sync_date": "2026-01-01",
        })
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A}_FACTURES_PUBLIQUES;1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(self.partner_a.fr_directory_entity_type, "public")

    def test_import_ignores_disabled_public_routing_code(self):
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A}_FACTURES_PUBLIQUES;0\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(self.partner_a.fr_directory_entity_type, "private")

    def test_import_never_turns_public_entity_private(self):
        self.partner_a.write({
            "fr_directory_entity_type": "public",
            "fr_directory_last_sync_date": "2026-01-01",
        })
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(self.partner_a.fr_directory_entity_type, "public")

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
            f"{SIREN_C};{SIREN_C}\n"  # valid but no partner
            "12345;12345\n"  # not 9 digits
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
            (f"SIREN;Adresse de facturation\n{SIREN_A};{SIREN_A}\n").encode("utf-8-sig")
        )
        self.assertEqual(res["created"], 1)

    def test_import_without_siren_column_raises(self):
        with self.assertRaises(UserError):
            self._import("Raison sociale;Adresse\nACME;whatever\n")

    def test_import_empty_file_raises(self):
        with self.assertRaises(UserError):
            self._import("")

    def test_import_reports_ambiguous_siren(self):
        """A shared SIREN is reported, but as a replication notice: nothing is
        dropped any more."""
        self._create_twin()
        res = self._import(
            "SIREN;Adresse de facturation\n" f"{SIREN_A};{SIREN_A}\n"
        )
        res = self._import(f"SIREN;Adresse de facturation\n{SIREN_A};{SIREN_A}\n")
        self.assertEqual(res["ambiguous"], 1)
        # Assert on the SIREN, not on the wording: the message goes through _()
        # and the test database may run in any language.
        self.assertTrue(any(SIREN_A in err for err in res["errors"]))

    def test_import_fans_out_shared_siren(self):
        """Each company sharing the SIREN gets its own directory line, so each
        one can carry its own default routing line."""
        twin = self._create_twin()
        res = self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
        )
        self.assertEqual(res["created"], 2)
        for partner in (self.partner_a, twin):
            line = self.Line.with_context(active_test=False).search(
                [("partner_id", "=", partner.id)]
            )
            self.assertEqual(line.identifier, SIREN_A)
            self.assertIn(partner.id, res["partner_ids"])

    def test_import_fan_out_is_idempotent(self):
        twin = self._create_twin()
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
                [("partner_id", "in", (self.partner_a | twin).ids)]
            ),
            2,
        )

    # ------------------------------------------------------------------
    # Default directory line
    # ------------------------------------------------------------------
    def test_default_directory_line_without_line(self):
        self.assertFalse(self.partner_a._default_fr_directory_line())

    def test_default_directory_line_with_single_line(self):
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(
            self.partner_a._default_fr_directory_line(),
            self.partner_a.fr_directory_line_ids,
        )

    def test_default_directory_line_ignores_inactive_line(self):
        """A line present in the directory but not active cannot receive
        invoices: it is no default, even when it is the only one."""
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
        )
        self.partner_a.fr_directory_line_ids.state = "inactive"
        self.partner_a.invalidate_recordset()
        self.assertFalse(self.partner_a._default_fr_directory_line())

    def test_default_directory_line_with_several_lines(self):
        """Several lines: the base rule refuses to guess and leaves the choice
        to the user -- or to an override."""
        self._import(
            "SIREN;Adresse de facturation;Adresse de facturation active\n"
            f"{SIREN_A};{SIREN_A};1\n"
            f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        self.partner_a.invalidate_recordset()
        self.assertEqual(len(self.partner_a.fr_directory_line_ids), 2)
        self.assertFalse(self.partner_a._default_fr_directory_line())

    # ------------------------------------------------------------------
    # The file is authoritative for the partners it contains
    # ------------------------------------------------------------------
    def _lines(self, partner):
        return self.Line.with_context(active_test=False).search(
            [("partner_id", "=", partner.id)]
        )

    def test_import_disables_lines_missing_from_file(self):
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(
            header
            + f"{SIREN_A};{SIREN_A};1\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        res = self._import(header + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n")
        self.assertEqual(res["disabled"], 1)
        states = {line.identifier: line.state for line in self._lines(self.partner_a)}
        self.assertEqual(
            states, {SIREN_A: "disabled", f"{SIREN_A}_{SIRET_A}": "active"}
        )

    def test_import_keeps_lines_of_partners_absent_from_file(self):
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(header + f"{SIREN_A};{SIREN_A};1\n{SIREN_B};{SIREN_B};1\n")
        res = self._import(header + f"{SIREN_A};{SIREN_A};1\n")
        self.assertEqual(res["disabled"], 0)
        self.assertEqual(self._lines(self.partner_b).state, "active")

    def test_import_disable_pass_is_idempotent(self):
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(
            header
            + f"{SIREN_A};{SIREN_A};1\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        csv_text = header + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        self._import(csv_text)
        res = self._import(csv_text)
        self.assertEqual(res["disabled"], 0)
        self.assertEqual(res["default_reset"], 0)

    def test_import_resets_default_line_disabled_by_file(self):
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(header + f"{SIREN_A};{SIREN_A};1\n")
        self.partner_a.invalidate_recordset()
        old_default = self.partner_a.default_fr_directory_line_id
        self.assertEqual(old_default.identifier, SIREN_A)
        res = self._import(header + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n")
        self.assertEqual(res["default_reset"], 1)
        self.partner_a.invalidate_recordset()
        self.assertEqual(
            self.partner_a.default_fr_directory_line_id.identifier,
            f"{SIREN_A}_{SIRET_A}",
        )

    def test_import_empties_stale_default_line_without_candidate(self):
        """No obvious replacement: the stale line is emptied rather than kept,
        so the invoice cannot be sent to an address that is no longer active."""
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(header + f"{SIREN_A};{SIREN_A};1\n")
        res = self._import(
            header
            + f"{SIREN_A};{SIREN_A};0\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A}_SERVICE1;1\n"
        )
        self.assertEqual(res["default_reset"], 1)
        self.partner_a.invalidate_recordset()
        self.assertFalse(self.partner_a.default_fr_directory_line_id)

    def test_import_keeps_active_manual_default_line(self):
        header = "SIREN;Adresse de facturation;Adresse de facturation active\n"
        self._import(
            header
            + f"{SIREN_A};{SIREN_A};1\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        manual = self._lines(self.partner_a).filtered(
            lambda line: line.identifier == SIREN_A
        )
        self.partner_a.default_fr_directory_line_id = manual
        res = self._import(
            header
            + f"{SIREN_A};{SIREN_A};1\n"
            + f"{SIREN_A};{SIREN_A}_{SIRET_A};1\n"
        )
        self.assertEqual(res["default_reset"], 0)
        self.assertEqual(self.partner_a.default_fr_directory_line_id, manual)


class TestDirectoryCsvWizard(DirectoryCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Wizard Test",
                "is_company": True,
                "company_registry": SIRET_A,
                "country_id": cls.env.ref("base.fr").id,
            }
        )

    def test_export_uses_active_ids(self):
        wizard = (
            self.env["fr.directory.csv.wizard"]
            .with_context(active_ids=self.partner.ids)
            .create({"only_missing": False})
        )
        wizard.action_export_siren()
        self.assertEqual(wizard.export_filename, "directory_siren.csv")
        self.assertTrue(wizard.export_file)

    def test_export_only_missing_excludes_registered_partners(self):
        """A partner already holding a line — even a disabled one — is
        registered in the directory and must not be deposited again."""
        self.env["fr.directory.line"].create(
            {
                "partner_id": self.partner.id,
                "identifier": SIREN_A,
                "type": "siren",
                "siren": SIREN_A,
                "state": "disabled",
            }
        )
        wizard = (
            self.env["fr.directory.csv.wizard"]
            .with_context(active_ids=self.partner.ids)
            .create({"only_missing": True})
        )
        with self.assertRaises(UserError):
            wizard.action_export_siren()

    def test_import_requires_a_file(self):
        wizard = self.env["fr.directory.csv.wizard"].create({})
        with self.assertRaises(UserError):
            wizard.action_import()
