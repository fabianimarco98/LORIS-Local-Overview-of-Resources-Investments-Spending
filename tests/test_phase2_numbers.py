import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd

from banking.parsers import BankStatement
from banking.portfolio import PortfolioAggregator, monthly_spending_series


def tx(rows):
    return pd.DataFrame([{"date": pd.Timestamp(d), "amount": a, "description": desc, **extra} for d, a, desc, extra in rows])


def stmt(acc, rows, balance=1000.0, asset="LIQUID_CASH", **meta):
    return BankStatement(account_id=acc, institution=acc, account_type="Checking", asset_class=asset,
                         ending_balance=balance, transactions=tx(rows), metadata=meta)


def full_months(amount, months=("2026-05", "2026-06", "2026-07")):
    """Un mese completo: movimento il 1° e il 28."""
    rows = []
    for m in months:
        rows += [(f"{m}-01", -amount, "Spesa", {}), (f"{m}-28", -1.0, "Altro", {})]
    return rows


class TestSpendingDefinition(unittest.TestCase):
    def test_detected_transfer_is_not_spending(self):
        a = stmt("A", full_months(100) + [("2026-06-10", -500.0, "Bonifico a TR", {})])
        b = stmt("B", [("2026-06-10", 500.0, "Bonifico da Erste", {})])
        s = PortfolioAggregator([a, b]).aggregate()
        self.assertEqual(len(s.internal_transfers), 1)
        self.assertAlmostEqual(s.monthly_burn_rate, 101.0, places=1)   # senza i 500 del giroconto

    def test_investment_purchases_are_not_spending(self):
        rows = full_months(100) + [(f"2026-0{m}-15", -200.0, "Sparplan ETF", {"category": "Investimenti & PAC"}) for m in (5, 6, 7)]
        s = PortfolioAggregator([stmt("A", rows)]).aggregate()
        self.assertAlmostEqual(s.monthly_burn_rate, 101.0, places=1)

    def test_partial_edge_months_are_dropped_when_enough_data(self):
        rows = [("2026-04-20", -50.0, "x", {})] + full_months(100) + [("2026-08-02", -30.0, "y", {})]
        m = monthly_spending_series(tx(rows))
        self.assertEqual([str(p) for p in m.index], ["2026-05", "2026-06", "2026-07"])

    def test_short_history_keeps_all_months(self):
        m = monthly_spending_series(tx([("2026-09-12", -80.0, "x", {}), ("2026-09-20", -20.0, "y", {})]))
        self.assertEqual(len(m), 1)
        self.assertAlmostEqual(float(m.iloc[0]), 100.0)

    def test_same_amount_without_hint_on_other_day_is_not_a_transfer(self):
        a = stmt("A", [("2026-06-05", -1500.0, "Miete Wohnung", {})])
        b = stmt("B", [("2026-06-08", 1500.0, "Gehalt Firma", {})])
        self.assertTrue(PortfolioAggregator([a, b]).aggregate().internal_transfers.empty)


if __name__ == "__main__":
    unittest.main()
