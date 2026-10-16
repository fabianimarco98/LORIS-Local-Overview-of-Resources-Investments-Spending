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


class TestUserOverridesAreEffective(unittest.TestCase):
    def setUp(self):
        import bank_data_manager as bdm
        self.bdm = bdm
        rows = full_months(100) + [("2026-06-10", -500.0, "Bonifico a TR", {})]
        self.statements = [stmt("A", rows, balance=5000.0)]

    def _apply(self, overrides):
        agg = PortfolioAggregator(self.statements)
        summary = agg.aggregate()
        base = {"balance_overrides": {}, "category_overrides": {}, "transfer_flags": {},
                "excluded_transactions": [], "manual_transactions": []}
        base.update(overrides)
        return self.bdm.apply_user_overrides(self.statements, summary, base)[1]

    def test_excluding_a_transaction_lowers_burn_rate(self):
        before = self._apply({})
        key = self.bdm.make_tx_key(pd.Timestamp("2026-06-10"), "A", -500.0, "Bonifico a TR")
        after = self._apply({"excluded_transactions": [key]})
        self.assertLess(after.monthly_burn_rate, before.monthly_burn_rate)
        self.assertAlmostEqual(after.monthly_burn_rate, 101.0, places=1)

    def test_marking_transfer_removes_it_from_spending_and_stats(self):
        key = self.bdm.make_tx_key(pd.Timestamp("2026-06-10"), "A", -500.0, "Bonifico a TR")
        s = self._apply({"transfer_flags": {key: True}})
        self.assertAlmostEqual(s.monthly_burn_rate, 101.0, places=1)
        cat = self.bdm.categorize_transactions(s.all_transactions, s.internal_transfers)
        row = cat[cat["amount"] == -500.0].iloc[0]
        self.assertTrue(row["is_internal_transfer"])

    def test_unflagging_an_autodetected_transfer_sticks(self):
        a = stmt("A", full_months(100) + [("2026-06-10", -500.0, "Bonifico a TR", {})])
        b = stmt("B", [("2026-06-10", 500.0, "Bonifico da Erste", {})])
        self.statements = [a, b]
        summary = PortfolioAggregator(self.statements).aggregate()
        self.assertEqual(len(summary.internal_transfers), 1)
        key = self.bdm.make_tx_key(pd.Timestamp("2026-06-10"), "A", -500.0, "Bonifico a TR")
        s = self._apply({"transfer_flags": {key: False}})
        cat = self.bdm.categorize_transactions(s.all_transactions, s.internal_transfers)
        self.assertFalse(cat[cat["amount"] == -500.0].iloc[0]["is_internal_transfer"])

    def test_overridden_summary_keeps_asset_class_and_tracker_columns(self):
        s = self._apply({})
        self.assertIn("asset_class", s.all_transactions.columns)
        self.assertIn("is_tracker", s.all_transactions.columns)

    def test_manual_transaction_counts_in_burn(self):
        manual = [{"date": "2026-06-15", "amount": -400.0, "description": "Spesa manuale", "category": "Altre Spese",
                   "account_id": "A", "institution": "A"}]
        s = self._apply({"manual_transactions": manual, "transfer_flags": {}, "excluded_transactions":
                         [self.bdm.make_tx_key(pd.Timestamp("2026-06-10"), "A", -500.0, "Bonifico a TR")]})
        self.assertAlmostEqual(s.monthly_burn_rate, (101 * 3 + 400) / 3, places=0)


class TestSimulationFixes(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import simulation_engine as se
        self.np, self.se = np, se

    def _run(self, **kw):
        base = dict(start="2026-10-01", horizon_months=6, n_sims=300, seed=1, monthly_income=0.0,
                    infl_mean=0.0, infl_std=0.0, mkt_std=0.0, mkt_mean=0.0, cash_rate=0.0)
        base.update(kw)
        return self.se.run_simulation(**base)

    def test_empirical_volatility_is_not_inflated_by_common_shock(self):
        res = self._run(pac=0.0, starting_cash=10000.0, starting_inv=0.0,
                        monthly_expenses_mean=1000.0, monthly_expenses_std=0.0)
        self.assertAlmostEqual(float(self.np.std(res["expenses"][:, 0])), 0.0, places=6)

    def test_forced_sale_covers_shortfall_after_tax(self):
        res = self._run(pac=0.0, starting_cash=0.0, starting_inv=10000.0, tax_rate=0.26,
                        monthly_expenses_mean=500.0, monthly_expenses_std=0.0)
        self.assertGreaterEqual(float(res["cash_history"].min()), -1e-6)

    def test_pac_is_skipped_without_cash(self):
        res = self._run(pac=100.0, starting_cash=50.0, starting_inv=0.0,
                        monthly_expenses_mean=0.0, monthly_expenses_std=0.0)
        self.assertAlmostEqual(float(res["invest_history"].max()), 0.0)
        self.assertAlmostEqual(float(res["cash_history"][0, -1]), 50.0)

    def test_after_tax_history_matches_final_wealth(self):
        res = self._run(pac=100.0, starting_cash=5000.0, starting_inv=1000.0, mkt_mean=0.08,
                        monthly_expenses_mean=300.0, monthly_expenses_std=0.0)
        self.np.testing.assert_allclose(res["nw_history"][:, -1], res["nw_final"], rtol=1e-9)

    def test_default_start_is_first_of_next_month(self):
        import pandas as pd
        d = pd.Timestamp(self.se.default_start())
        self.assertEqual(d.day, 1)
        self.assertGreater(d, pd.Timestamp.today().normalize())
