# ============================================================
# TEST DI CALIBRAZIONE — reddito, rimborsi, bootstrap delle spese
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import pandas as pd

import bank_data_manager as bdm
import loris_service as svc
import simulation_engine as se
from banking.portfolio import income_credits, monthly_spending_series, refund_credits


def tx(date, amount, desc="x", cat=None):
    return {"date": pd.Timestamp(date), "amount": amount, "description": desc,
            "category": cat or ("Stipendio" if amount > 0 else "Altre Spese"), "is_internal_transfer": False}


def two_years(salary=2000.0, extra_months=(), extra=0.0, split=False, spend=1000.0):
    """24 mesi completi: stipendio il 27, spesa il 10 di ogni mese (opz. stipendio in due bonifici)."""
    rows = []
    for m in pd.period_range("2024-01", "2025-12", freq="M"):
        pay = salary + (extra if m.month in extra_months else 0.0)
        if split:
            rows += [tx(m.to_timestamp() + pd.Timedelta(days=14), pay / 2), tx(m.to_timestamp() + pd.Timedelta(days=26), pay / 2)]
        else:
            rows.append(tx(m.to_timestamp() + pd.Timedelta(days=26), pay))
        rows.append(tx(m.to_timestamp() + pd.Timedelta(days=9), -spend))
        rows.append(tx(m.to_timestamp() + pd.Timedelta(days=2), -5.0))
    return pd.DataFrame(rows)


class TestSalaryDetection(unittest.TestCase):
    def test_fourteen_payments_are_detected(self):
        stats = bdm.compute_bank_monthly_statistics(two_years(extra_months=(6, 12), extra=2000.0))
        self.assertAlmostEqual(stats["detected_salary"], 2000.0)
        self.assertEqual(stats["salary_bonus_months"], (6, 12))
        self.assertAlmostEqual(stats["salary_bonus_amount"], 2000.0)
        self.assertAlmostEqual(stats["annual_income_estimate"], 28000.0, delta=280.0)

    def test_split_salary_is_not_halved(self):
        stats = bdm.compute_bank_monthly_statistics(two_years(split=True))
        self.assertAlmostEqual(stats["detected_salary"], 2000.0)
        self.assertEqual(stats["salary_bonus_months"], ())

    def test_short_history_has_no_bonus_detection(self):
        df = two_years(extra_months=(12,), extra=2000.0)
        stats = bdm.compute_bank_monthly_statistics(df[df["date"] < "2024-08-01"])
        self.assertEqual(stats["salary_bonus_months"], ())
        self.assertAlmostEqual(stats["detected_salary"], 2000.0)

    def test_service_passes_bonus_months_to_engine_unless_income_overridden(self):
        stats = bdm.compute_bank_monthly_statistics(two_years(extra_months=(6, 12), extra=2000.0))
        data = svc.PortfolioData([], type("S", (), {"total_liquid_cash": 5000.0, "total_high_yield_cash": 0.0,
                                                   "total_investments": 0.0, "all_transactions": pd.DataFrame({"a": [1]})})(),
                                 two_years(), stats)
        res = svc.run_forecast(data, start="2026-01-01", horizon_months=12, n_sims=50, annual_inflation_pct=0.0,
                               wage_growth_pct=0.0)
        self.assertAlmostEqual(float(res["income"][5]), 4000.0)
        self.assertAlmostEqual(float(res["income"][0]), 2000.0)
        forced = svc.run_forecast(data, start="2026-01-01", horizon_months=12, n_sims=50, monthly_income=1500.0,
                                  annual_inflation_pct=0.0, wage_growth_pct=0.0)
        self.assertTrue(np.allclose(forced["income"], 1500.0))


class TestRefundsAndDisinvestments(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            tx("2025-01-05", -300.0, "Amazon"),
            tx("2025-01-12", 80.0, "Rimborso Amazon", "Entrate Varie"),
            tx("2025-01-20", 1500.0, "Sell trade ETF world", "Entrate Varie"),
            tx("2025-01-27", 2000.0, "Gehalt Gutschrift"),
            tx("2025-01-28", 5.0, "Zinsen", "Interessi & Rendite"),
        ])

    def test_refunds_are_not_income(self):
        self.assertEqual(len(refund_credits(self.df)), 1)
        self.assertEqual(sorted(income_credits(self.df)["amount"].tolist()), [5.0, 2000.0])

    def test_refunds_reduce_spending_of_the_month(self):
        self.assertAlmostEqual(float(monthly_spending_series(self.df, trim_partial=False).iloc[0]), 220.0)

    def test_refund_larger_than_spend_never_goes_negative(self):
        df = pd.DataFrame([tx("2025-01-05", -50.0), tx("2025-01-12", 80.0, "Refund", "Entrate Varie")])
        self.assertAlmostEqual(float(monthly_spending_series(df, trim_partial=False).iloc[0]), 0.0)

    def test_salary_with_gutschrift_in_description_is_kept_as_income(self):
        self.assertIn(2000.0, income_credits(self.df)["amount"].tolist())

    def test_savings_rate_ignores_etf_sale_and_refund(self):
        stats = bdm.compute_bank_monthly_statistics(self.df)
        self.assertAlmostEqual(stats["total_inflow"], 2005.0)
        self.assertAlmostEqual(stats["total_outflow"], 220.0)


class TestExpenseBootstrap(unittest.TestCase):
    def history(self):
        rng = np.random.default_rng(0)
        base = rng.lognormal(mean=np.log(1000), sigma=0.25, size=18)
        base[5] += 2500      # un mese eccezionale (es. viaggio)
        return base

    def sim(self, **kw):
        base = dict(start="2026-01-01", horizon_months=12, n_sims=3000, seed=4, monthly_income=0.0,
                    starting_cash=1e6, starting_inv=0.0, infl_mean=0.0, infl_std=0.0, mkt_std=0.0, mkt_mean=0.0,
                    cash_rate=0.0, wage_growth=0.0, pac=0.0)
        base.update(kw)
        return se.run_simulation(**base)

    def test_mean_matches_history_and_values_come_from_it(self):
        h = self.history()
        res = self.sim(expense_history=h)
        exp = res["expenses"]
        self.assertAlmostEqual(float(exp.mean()), float(h.mean()), delta=40.0)
        self.assertTrue(set(np.round(np.unique(exp), 6)) <= set(np.round(h, 6)))

    def test_keeps_the_fat_right_tail(self):
        h = self.history()
        exp = self.sim(expense_history=h)["expenses"]
        self.assertGreater(float(exp.max()), float(h.mean()) + 2000.0)

    def test_blocks_keep_consecutive_months_together(self):
        h = np.arange(100.0, 100.0 + 18)         # 100,101,...: i blocchi crescono di 1 per mese
        exp = self.sim(expense_history=h, horizon_months=6, bootstrap_block=3, n_sims=200)["expenses"]
        steps = np.diff(exp, axis=1)
        self.assertTrue(np.allclose(steps[:, [0, 1, 3, 4]], 1.0))

    def test_target_mean_and_std_rescale_history(self):
        h = self.history()
        exp = self.sim(expense_history=h, monthly_expenses_mean=2000.0, monthly_expenses_std=100.0,
                       n_sims=6000, horizon_months=36)["expenses"]
        self.assertAlmostEqual(float(exp.mean()), 2000.0, delta=15.0)
        self.assertAlmostEqual(float(exp.std()), 100.0, delta=10.0)

    def test_short_history_falls_back_to_normal_model(self):
        res = self.sim(expense_history=[900.0, 1100.0, 1000.0], monthly_expenses_mean=1000.0,
                       monthly_expenses_std=0.0, horizon_months=3, n_sims=50)
        self.assertTrue(np.allclose(res["expenses"], 1000.0))

    def test_expenses_scale_with_inflation(self):
        h = np.full(12, 1000.0)
        res = self.sim(expense_history=h, infl_mean=0.12, horizon_months=12, n_sims=20)
        self.assertGreater(float(res["expenses"][0, -1]), float(res["expenses"][0, 0]))


if __name__ == "__main__":
    unittest.main()
