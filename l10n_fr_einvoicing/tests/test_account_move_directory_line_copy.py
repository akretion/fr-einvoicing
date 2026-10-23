# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Valid SIRENs (Luhn checksum) with the matching french VAT numbers
SIREN_COMPANY = ("100000017", "FR15100000017")
SIREN_CUSTOMER_1 = ("100000025", "FR39100000025")
SIREN_CUSTOMER_2 = ("100000033", "FR63100000033")


@tagged("post_install", "-at_install")
class TestAccountMoveDirectoryLineCopy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.today = fields.Date.context_today(cls.env["res.partner"])
        cls.env.ref("base.EUR").active = True
        # French company registered for e-invoicing, without any external call:
        # no directory sync upon posting and no flow sent to the platform.
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test FR Company",
                "country_id": cls.env.ref("base.fr").id,
                "currency_id": cls.env.ref("base.EUR").id,
                "fr_ctc_accredited_platform": "superpdp",
                "fr_ctc_directory_sync_on_invoice_post": "no",
                "fr_ctc_send_out_invoice": "none",
            }
        )
        cls.env = cls.env(
            context=dict(cls.env.context, allowed_company_ids=cls.company.ids)
        )
        company_partner = cls.company.partner_id
        # entity type and last sync date are written together (constraint)
        company_partner.write(
            {
                "vat": SIREN_COMPANY[1],
                "siren": SIREN_COMPANY[0],
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": cls.today,
            }
        )
        cls.company_line = cls._create_dir_line(company_partner, "COMPANY-1")
        # Minimal accounting setup for the new company (no chart template is
        # loaded on it): accounts, default receivable/payable properties
        # and one sale and one purchase journal.
        account_obj = cls.env["account.account"]
        vals = {"company_id": cls.company.id}
        cls.receivable = account_obj.create(
            dict(
                vals,
                name="Receivable",
                code="TFR411",
                account_type="asset_receivable",
                reconcile=True,
            )
        )
        cls.payable = account_obj.create(
            dict(
                vals,
                name="Payable",
                code="TFR401",
                account_type="liability_payable",
                reconcile=True,
            )
        )
        cls.income = account_obj.create(
            dict(vals, name="Income", code="TFR706", account_type="income")
        )
        cls.expense = account_obj.create(
            dict(vals, name="Expense", code="TFR606", account_type="expense")
        )
        prop_obj = cls.env["ir.property"]
        prop_obj._set_default(
            "property_account_receivable_id",
            "res.partner",
            cls.receivable,
            cls.company,
        )
        prop_obj._set_default(
            "property_account_payable_id", "res.partner", cls.payable, cls.company
        )
        journal_obj = cls.env["account.journal"]
        cls.sale_journal = journal_obj.create(
            dict(
                vals,
                name="Test Sales",
                code="TSAL",
                type="sale",
                default_account_id=cls.income.id,
            )
        )
        cls.purchase_journal = journal_obj.create(
            dict(
                vals,
                name="Test Purchases",
                code="TPUR",
                type="purchase",
                default_account_id=cls.expense.id,
            )
        )
        cls.customer1 = cls._create_customer("Customer 1", SIREN_CUSTOMER_1)
        cls.customer2 = cls._create_customer("Customer 2", SIREN_CUSTOMER_2)

    @classmethod
    def _create_customer(cls, name, siren_vat):
        return cls.env["res.partner"].create(
            {
                "name": name,
                "is_company": True,
                "country_id": cls.env.ref("base.fr").id,
                "siren": siren_vat[0],
                "vat": siren_vat[1],
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": cls.today,
            }
        )

    @classmethod
    def _create_dir_line(cls, partner, identifier):
        return cls.env["fr.directory.line"].create(
            {
                "partner_id": partner.id,
                "identifier": identifier,
                "type": "suffix",
                "state": "active",
            }
        )

    def _create_invoice(self, partner, move_type="out_invoice", **extra_vals):
        is_sale = move_type == "out_invoice"
        vals = {
            "move_type": move_type,
            "partner_id": partner.id,
            "company_id": self.company.id,
            "journal_id": (self.sale_journal if is_sale else self.purchase_journal).id,
            "invoice_date": self.today,
            "invoice_line_ids": [
                Command.create(
                    {
                        "name": "Test line",
                        "quantity": 1,
                        "price_unit": 100,
                        "account_id": (self.income if is_sale else self.expense).id,
                        "tax_ids": [Command.clear()],
                    }
                )
            ],
        }
        vals.update(extra_vals)
        return self.env["account.move"].create(vals)

    def _post_invoice_before_connection(
        self, partner, clear_partner_line=True, clear_company_line=True
    ):
        """Post a customer invoice, then empty its directory line(s) to simulate
        an invoice created before the connection to the e-invoicing platform."""
        # A directory line is required to post: give one explicitly, because
        # the computation may find none (several active lines, no default).
        line = partner.default_fr_directory_line_id or partner.fr_directory_line_ids[:1]
        move = self._create_invoice(partner, fr_directory_line_id=line.id)
        move.action_post()
        self._clear_directory_lines(
            move, partner_line=clear_partner_line, company_line=clear_company_line
        )
        return move

    def _clear_directory_lines(self, move, partner_line=True, company_line=True):
        # SQL to trigger neither computes nor tracking; flush first so that no
        # pending computation writes the values back over the NULLs
        self.env.flush_all()
        sets = []
        if company_line:
            sets.append("company_fr_directory_line_id=NULL")
        if partner_line:
            sets += ["fr_directory_line_id=NULL", "fr_directory_line_identifier=NULL"]
        self.env.cr.execute(
            f"UPDATE account_move SET {', '.join(sets)} WHERE id=%s",  # noqa: S608
            (move.id,),
        )
        move.invalidate_recordset(
            [
                "fr_directory_line_id",
                "fr_directory_line_identifier",
                "company_fr_directory_line_id",
            ]
        )

    def _reverse(self, move, refund_method):
        """Reverse with the wizard. Returns (refund, new draft or empty)."""
        wizard = (
            self.env["account.move.reversal"]
            .with_context(active_model="account.move", active_ids=move.ids)
            .create({"refund_method": refund_method, "journal_id": move.journal_id.id})
        )
        action = wizard.reverse_moves()
        refund = move.reversal_move_id[:1]
        self.assertTrue(refund, "The wizard should have created a refund")
        if refund_method == "modify":
            new_move = self.env["account.move"].browse(action["res_id"])
            self.assertTrue(new_move)
            self.assertNotEqual(new_move, refund)
            return refund, new_move
        return refund, self.env["account.move"]

    def test_01_refund_modify_takes_partner_default_line(self):
        line = self._create_dir_line(self.customer1, "CUST1-DEFAULT")
        self.customer1.default_fr_directory_line_id = line
        move = self._post_invoice_before_connection(self.customer1)
        self.assertFalse(move.fr_directory_line_id)
        refund, new_move = self._reverse(move, "modify")
        self.assertEqual(refund.state, "posted")
        self.assertEqual(refund.fr_directory_line_id, line)
        self.assertEqual(refund.fr_directory_line_identifier, line.identifier)
        self.assertEqual(new_move.state, "draft")
        self.assertEqual(new_move.fr_directory_line_id, line)
        self.assertEqual(new_move.fr_directory_line_identifier, line.identifier)

    def test_02_refund_cancel_takes_single_active_line(self):
        line = self._create_dir_line(self.customer1, "CUST1-ONLY")
        move = self._post_invoice_before_connection(self.customer1)
        self.assertFalse(move.fr_directory_line_id)
        refund, __ = self._reverse(move, "cancel")
        self.assertEqual(refund.state, "posted")
        self.assertEqual(refund.fr_directory_line_id, line)
        self.assertEqual(refund.fr_directory_line_identifier, line.identifier)

    def test_03_refund_keeps_original_valid_line(self):
        line_a = self._create_dir_line(self.customer1, "CUST1-A")
        line_b = self._create_dir_line(self.customer1, "CUST1-B")
        self.customer1.default_fr_directory_line_id = line_b
        move = self._create_invoice(self.customer1, fr_directory_line_id=line_a.id)
        move.action_post()
        self.assertEqual(move.fr_directory_line_id, line_a)
        refund, __ = self._reverse(move, "refund")
        self.assertEqual(refund.state, "draft")
        self.assertEqual(refund.fr_directory_line_id, line_a)
        self.assertEqual(refund.fr_directory_line_identifier, line_a.identifier)

    def test_04_duplicate_takes_partner_default_line(self):
        line = self._create_dir_line(self.customer1, "CUST1-DEFAULT")
        self._create_dir_line(self.customer1, "CUST1-OTHER")
        self.customer1.default_fr_directory_line_id = line
        move = self._post_invoice_before_connection(self.customer1)
        self.assertFalse(move.fr_directory_line_id)
        new_move = move.copy()
        self.assertEqual(new_move.state, "draft")
        self.assertEqual(new_move.fr_directory_line_id, line)
        self.assertEqual(new_move.fr_directory_line_identifier, line.identifier)

    def test_05_partial_refund_multi_lines_manual(self):
        line1 = self._create_dir_line(self.customer1, "CUST1-1")
        self._create_dir_line(self.customer1, "CUST1-2")
        # the company line of old invoices was filled by the company directory
        # sync, so this workaround works today: keep it set
        move = self._post_invoice_before_connection(
            self.customer1, clear_company_line=False
        )
        self.assertFalse(move.fr_directory_line_id)
        refund, __ = self._reverse(move, "refund")
        self.assertEqual(refund.state, "draft")
        # two active lines and no default: nothing can be chosen automatically
        self.assertFalse(
            refund.fr_directory_line_id,
            "Precondition: with several active lines and no default, the line "
            "has to be chosen by hand",
        )
        refund.fr_directory_line_id = line1
        refund.action_post()
        self.assertEqual(refund.state, "posted")
        self.assertEqual(refund.fr_directory_line_id, line1)

    def test_06_refund_recomputes_inactive_original_line(self):
        line_a = self._create_dir_line(self.customer1, "CUST1-A")
        line_b = self._create_dir_line(self.customer1, "CUST1-B")
        self.customer1.default_fr_directory_line_id = line_b
        move = self._create_invoice(self.customer1, fr_directory_line_id=line_a.id)
        move.action_post()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE fr_directory_line SET state='disabled', active=false WHERE id=%s",
            (line_a.id,),
        )
        line_a.invalidate_recordset(["state", "active"])
        self.assertEqual(move.fr_directory_line_id, line_a)
        refund, __ = self._reverse(move, "refund")
        self.assertEqual(refund.fr_directory_line_id, line_b)
        self.assertEqual(refund.fr_directory_line_identifier, line_b.identifier)

    def test_07_refund_takes_company_line_when_original_empty(self):
        line = self._create_dir_line(self.customer1, "CUST1-ONLY")
        # only the company line is emptied: the customer line is still valid
        move = self._post_invoice_before_connection(
            self.customer1, clear_partner_line=False
        )
        self.assertFalse(move.company_fr_directory_line_id)
        self.assertEqual(move.fr_directory_line_id, line)
        refund, __ = self._reverse(move, "cancel")
        self.assertEqual(refund.state, "posted")
        self.assertEqual(refund.company_fr_directory_line_id, self.company_line)

    def test_08_supplier_invoice_copy_keeps_identifier(self):
        supplier = self.env["res.partner"].create(
            {"name": "Test Supplier", "is_company": True}
        )
        bill = self._create_invoice(
            supplier,
            move_type="in_invoice",
            ref="SUPPLIER-BILL-1",
            fr_directory_line_identifier="SUPPLIER-DIR-ID",
        )
        self.assertEqual(bill.fr_directory_line_identifier, "SUPPLIER-DIR-ID")
        new_bill = bill.copy()
        self.assertEqual(new_bill.fr_directory_line_identifier, "SUPPLIER-DIR-ID")

    def test_09_copy_with_other_partner_recomputes_line(self):
        line_a = self._create_dir_line(self.customer1, "CUST1-A")
        line_c = self._create_dir_line(self.customer2, "CUST2-C")
        self._create_dir_line(self.customer2, "CUST2-D")
        self.customer2.default_fr_directory_line_id = line_c
        move = self._create_invoice(self.customer1, fr_directory_line_id=line_a.id)
        new_move = move.copy({"partner_id": self.customer2.id})
        self.assertEqual(new_move.partner_id, self.customer2)
        self.assertEqual(new_move.fr_directory_line_id, line_c)
        self.assertEqual(new_move.fr_directory_line_identifier, line_c.identifier)

    def test_10_copy_keeps_directory_line_given_in_default(self):
        line_a = self._create_dir_line(self.customer1, "CUST1-A")
        line_b = self._create_dir_line(self.customer1, "CUST1-B")
        self.customer1.default_fr_directory_line_id = line_a
        move = self._create_invoice(self.customer1)
        self.assertEqual(move.fr_directory_line_id, line_a)
        # the original line is valid: the identifier must still follow the
        # line given in default, not the copied one
        new_move = move.copy({"fr_directory_line_id": line_b.id})
        self.assertEqual(new_move.fr_directory_line_id, line_b)
        self.assertEqual(new_move.fr_directory_line_identifier, line_b.identifier)

    def test_11_copy_keeps_identifier_given_in_default(self):
        line = self._create_dir_line(self.customer1, "CUST1-DEFAULT")
        self.customer1.default_fr_directory_line_id = line
        move = self._post_invoice_before_connection(self.customer1)
        self.assertFalse(move.fr_directory_line_id)
        new_move = move.copy({"fr_directory_line_identifier": "MANUAL-ID"})
        self.assertEqual(new_move.fr_directory_line_identifier, "MANUAL-ID")

    def test_12_copy_keeps_company_line_given_in_default(self):
        company_partner = self.company.partner_id
        company_partner.default_fr_directory_line_id = self.company_line
        other_company_line = self._create_dir_line(company_partner, "COMPANY-2")
        self._create_dir_line(self.customer1, "CUST1-ONLY")
        move = self._post_invoice_before_connection(
            self.customer1, clear_partner_line=False
        )
        self.assertFalse(move.company_fr_directory_line_id)
        new_move = move.copy({"company_fr_directory_line_id": other_company_line.id})
        self.assertEqual(new_move.company_fr_directory_line_id, other_company_line)

    def test_13_copy_data_to_other_company_drops_company_line(self):
        self._create_dir_line(self.customer1, "CUST1-ONLY")
        move = self._create_invoice(self.customer1)
        self.assertEqual(move.company_fr_directory_line_id, self.company_line)
        # same company: the valid company line is copied
        self.assertIn("company_fr_directory_line_id", move.copy_data()[0])
        # other company: the line is not of its partner, so it is recomputed
        other_company = self.env.ref("base.main_company")
        self.assertNotEqual(other_company, self.company)
        data = move.copy_data({"company_id": other_company.id})[0]
        self.assertNotIn("company_fr_directory_line_id", data)
