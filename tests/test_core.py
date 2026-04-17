"""Unit tests for the core pricing engine and DB layer."""
import os, sys, tempfile, unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.markup import (
    DEFAULT_TIERS, multiplier_for_cost, marked_up_price, profit_on_part,
)
from app.tax import tax_on, DEFAULT_RATE
from app.pricing import LineItem, compute_totals
from app import db, repo


D = Decimal


class MarkupTests(unittest.TestCase):
    def test_tier_boundaries(self):
        # Matches the posted table exactly
        cases = [
            ("1.00",  "4.00"),
            ("2.50",  "4.00"),
            ("2.51",  "3.75"),
            ("5.00",  "3.75"),
            ("5.01",  "3.00"),
            ("10.00", "3.00"),
            ("10.01", "2.75"),
            ("50.00", "2.75"),
            ("50.01", "2.50"),
            ("100.00","2.50"),
            ("100.01","2.20"),
            ("150.00","2.20"),
            ("150.01","2.00"),
            ("200.00","2.00"),
            ("200.01","1.85"),
            ("500.00","1.85"),
            ("500.01","1.70"),
            ("2500.00","1.70"),
        ]
        for cost, expected in cases:
            with self.subTest(cost=cost):
                self.assertEqual(multiplier_for_cost(D(cost)), D(expected))

    def test_marked_up_price(self):
        self.assertEqual(marked_up_price(D("75.00")), D("187.50"))    # x2.50
        self.assertEqual(marked_up_price(D("250.00")), D("462.50"))   # x1.85
        self.assertEqual(marked_up_price(D("1.25")), D("5.00"))       # x4.00

    def test_profit(self):
        self.assertEqual(profit_on_part(D("10.00")), D("20.00"))


class TaxTests(unittest.TestCase):
    def test_default_55(self):
        self.assertEqual(tax_on(D("100.00")), D("5.50"))

    def test_override(self):
        self.assertEqual(tax_on(D("100.00"), D("0.07")), D("7.00"))


class PricingTests(unittest.TestCase):
    def _lines(self):
        return [
            LineItem(kind="part",  description="Brake pads (F)",
                     quantity=D("1"), unit_cost=D("60.00"), unit_price=D("150.00"), taxable=True),
            LineItem(kind="part",  description="Rotors (pair)",
                     quantity=D("2"), unit_cost=D("45.00"), unit_price=D("112.50"), taxable=True),
            LineItem(kind="labor", description="Front brake job",
                     quantity=D("1.5"), unit_cost=D("0"), unit_price=D("125.00"), taxable=False),
        ]

    def test_unpaid_totals(self):
        # Unpaid estimate still shows the non-cash adjustment on its face,
        # because the sticker price is always adjusted. Discount only applies
        # once payment method is cash or check.
        t = compute_totals(self._lines(), payment_method="unpaid")
        # parts = 150 + 225 = 375
        self.assertEqual(t.parts_subtotal, D("375.00"))
        # labor = 125 * 1.5 = 187.50
        self.assertEqual(t.labor_subtotal, D("187.50"))
        self.assertEqual(t.subtotal, D("562.50"))
        # tax = 5.5% of parts only
        self.assertEqual(t.tax, D("20.63"))
        # pre-payment total
        self.assertEqual(t.pre_payment_total, D("583.13"))
        # Non-cash adjustment always applied
        self.assertEqual(t.non_cash_adjustment, D("20.41"))
        self.assertEqual(t.cash_check_discount, D("0"))
        self.assertEqual(t.grand_total, D("603.54"))
        # parts profit: (150-60) + (225 - 90) = 90 + 135 = 225
        self.assertEqual(t.parts_profit, D("225.00"))
        # Backwards-compat aliases still work
        self.assertEqual(t.card_surcharge, D("20.41"))
        self.assertEqual(t.cash_discount, D("0"))

    def test_card_pays_adjusted_price(self):
        t = compute_totals(self._lines(), payment_method="card")
        self.assertEqual(t.non_cash_adjustment, D("20.41"))  # 583.13 * .035
        self.assertEqual(t.cash_check_discount, D("0"))
        self.assertEqual(t.grand_total, D("603.54"))

    def test_cash_gets_discount(self):
        t = compute_totals(self._lines(), payment_method="cash")
        # Adjustment stays on the invoice but is cancelled by an equal discount.
        self.assertEqual(t.non_cash_adjustment, D("20.41"))
        self.assertEqual(t.cash_check_discount, D("20.41"))
        self.assertEqual(t.grand_total, D("583.13"))

    def test_check_gets_same_discount_as_cash(self):
        # Check now gets the same 3.5% discount as cash (new policy — April 2026).
        t = compute_totals(self._lines(), payment_method="check")
        self.assertEqual(t.non_cash_adjustment, D("20.41"))
        self.assertEqual(t.cash_check_discount, D("20.41"))
        self.assertEqual(t.grand_total, D("583.13"))

    def test_labor_not_taxed(self):
        only_labor = [LineItem(kind="labor", description="Diag",
                               quantity=D("1"), unit_cost=D("0"),
                               unit_price=D("100"), taxable=False)]
        t = compute_totals(only_labor, payment_method="card")
        self.assertEqual(t.tax, D("0"))
        # $100 + 3.5% non-cash adjustment = $103.50
        self.assertEqual(t.grand_total, D("103.50"))


class DBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = db.connect(self.tmp.name)
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_settings_seed(self):
        self.assertEqual(db.get_setting(self.conn, "shop_name"), "Up Front Auto Repair")
        self.assertEqual(db.get_setting(self.conn, "tax_rate"), "0.055")

    def test_markup_tiers_seed(self):
        tiers = db.load_markup_tiers(self.conn)
        self.assertEqual(len(tiers), 9)
        self.assertEqual(tiers[0], (D("2.50"), D("4.00")))
        self.assertEqual(tiers[-1], (None, D("1.70")))

    def test_customer_roundtrip(self):
        cid = repo.upsert_customer(self.conn, {
            "first_name":"Jane","last_name":"Doe","phone":"207-555-0101",
            "email":"jane@example.com","address1":"1 Main St",
            "city":"Standish","state":"ME","zip":"04084",
        })
        c = repo.get_customer(self.conn, cid)
        self.assertEqual(c["last_name"], "Doe")
        results = repo.list_customers(self.conn, "jane")
        self.assertEqual(len(results), 1)

    def test_job_with_lines_and_delete(self):
        cid = repo.upsert_customer(self.conn, {"first_name":"Jane","last_name":"Doe"})
        vid = repo.upsert_vehicle(self.conn, {"customer_id":cid,"year":2018,"make":"Honda","model":"Civic"})
        jid = repo.create_job(self.conn, cid, vid, 0.055)
        lines = [
            LineItem(kind="part", description="Oil filter",
                     quantity=D("1"), unit_cost=D("6.00"), unit_price=D("18.00")),
            LineItem(kind="labor", description="Oil change",
                     quantity=D("0.5"), unit_cost=D("0"), unit_price=D("125.00"), taxable=False),
        ]
        repo.save_lines(self.conn, jid, lines)
        loaded = repo.load_lines(self.conn, jid)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].description, "Oil filter")
        # cash-paid hard delete path
        repo.delete_job(self.conn, jid)
        self.assertIsNone(repo.get_job(self.conn, jid))
        # lines cascaded
        remaining = self.conn.execute(
            "SELECT COUNT(*) AS c FROM line_items WHERE job_id=?", (jid,)
        ).fetchone()["c"]
        self.assertEqual(remaining, 0)

    def test_next_job_number(self):
        n1 = db.next_job_number(self.conn, "E")
        n2 = db.next_job_number(self.conn, "I")
        self.conn.commit()
        self.assertTrue(n1.startswith("E-"))
        self.assertTrue(n2.startswith("I-"))
        self.assertNotEqual(n1, n2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
