# ============================================================
# TEST DELL'ANALISI DI RISCHIO, STRESS E SENSITIVITÀ
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import pandas as pd

import forecast_analysis as fa
import loris_service as svc
import simulation_engine as se

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


def sim(**kw):
    base = dict(start="2026-01-01", horizon_months=24, n_sims=3000, seed=5, monthly_income=2000.0,
                monthly_expenses_mean=1500.0, monthly_expenses_std=300.0, pac=0.0, starting_cash=5000.0,
                starting_inv=20000.0, infl_mean=0.02, infl_std=0.01, mkt_mean=0.05, mkt_std=0.15, cash_rate=0.01,
                wage_growth=0.0, annual_fee=0.0, tax_rate=0.0)
    base.update(kw)
    return se.run_simulation(**base)


class TestRiskMetrics(unittest.TestCase):
    def setUp(self):
        self.res = sim()
        self.m = fa.risk_metrics(self.res, goal_amount=30000.0)

    def test_expected_shortfall_is_not_above_the_5th_percentile(self):
        self.assertLessEqual(self.m["es5"], self.m["var5"])
        self.assertAlmostEqual(self.m["var5"], self.res["p5"])
        tail = self.res["nw_final"][self.res["nw_final"] <= self.m["var5"]]
        self.assertAlmostEqual(self.m["es5"], float(tail.mean()))

    def test_ruin_by_month_is_cumulative_and_ends_at_prob_ruin(self):
        r = np.array(self.m["ruin_by_month"])
        self.assertTrue(np.all(np.diff(r) >= -1e-12))
        self.assertAlmostEqual(r[-1], self.res["prob_ruin"])

    def test_months_to_ruin_for_a_deterministic_drain(self):
        res = sim(monthly_income=0.0, monthly_expenses_mean=1000.0, monthly_expenses_std=0.0, starting_cash=3500.0,
                  starting_inv=0.0, infl_mean=0.0, infl_std=0.0, cash_rate=0.0, horizon_months=12, n_sims=50)
        m = fa.risk_metrics(res)
        self.assertEqual(m["median_months_to_ruin"], 4.0)
        self.assertAlmostEqual(m["ruin_by_month"][2], 0.0)
        self.assertAlmostEqual(m["ruin_by_month"][3], 100.0)

    def test_ruin_free_scenario_has_no_months_to_ruin(self):
        res = sim(monthly_income=5000.0, monthly_expenses_mean=1000.0, monthly_expenses_std=0.0, horizon_months=6, n_sims=100)
        self.assertIsNone(fa.risk_metrics(res)["median_months_to_ruin"])

    def test_drawdown_of_a_constant_wealth_is_zero_and_of_a_crash_is_positive(self):
        flat = sim(monthly_income=0.0, monthly_expenses_mean=0.0, monthly_expenses_std=0.0, starting_inv=0.0,
                   infl_mean=0.0, infl_std=0.0, cash_rate=0.0, n_sims=20, horizon_months=6)
        self.assertEqual(fa.risk_metrics(flat)["max_drawdown_median_pct"], 0.0)
        crash = sim(market_shock_path=[-0.1] * 6, mkt_std=0.0, monthly_income=0.0, monthly_expenses_mean=0.0,
                    monthly_expenses_std=0.0, starting_cash=0.0, infl_mean=0.0, infl_std=0.0, n_sims=20, horizon_months=6)
        self.assertAlmostEqual(fa.risk_metrics(crash)["max_drawdown_median_pct"], (1 - 0.9 ** 6) * 100, places=6)

    def test_goal_probability(self):
        g = self.m["goal"]
        self.assertGreaterEqual(g["prob_ever_pct"], g["prob_at_month_pct"])
        self.assertEqual(g["month"], 24)
        easy = fa.risk_metrics(self.res, goal_amount=1.0)["goal"]["prob_at_month_pct"]
        impossible = fa.risk_metrics(self.res, goal_amount=1e9)["goal"]["prob_ever_pct"]
        self.assertEqual((easy, impossible), (100.0, 0.0))
        early = fa.risk_metrics(self.res, goal_amount=30000.0, goal_month=6)["goal"]
        self.assertEqual(early["month"], 6)

    def test_monte_carlo_error_is_reported(self):
        p = self.res["prob_ruin"] / 100
        self.assertAlmostEqual(self.res["prob_ruin_se"], np.sqrt(p * (1 - p) / 3000) * 100)
        self.assertEqual(self.res["n_sims"], 3000)


class TestStressEngine(unittest.TestCase):
    def test_market_shock_path_replaces_random_returns_then_resumes(self):
        res = sim(market_shock_path=[-0.1, -0.1], mkt_std=0.2, monthly_income=0.0, monthly_expenses_mean=0.0,
                  monthly_expenses_std=0.0, starting_cash=0.0, infl_mean=0.0, infl_std=0.0, annual_fee=0.0)
        inv = res["invest_history"]
        np.testing.assert_allclose(inv[:, 0], 20000 * 0.9)
        np.testing.assert_allclose(inv[:, 1], 20000 * 0.81)
        self.assertGreater(float(inv[:, 5].std()), 0.0)

    def test_shock_does_not_shift_the_random_stream(self):
        a = sim(income_gap=None)
        b = sim(market_shock_path=[0.0] * 3)
        np.testing.assert_array_equal(a["expenses"], b["expenses"])

    def test_inflation_shock_path_sets_price_level(self):
        res = sim(inflation_shock_path=[0.01] * 3, infl_std=0.05, monthly_expenses_std=0.0, horizon_months=3)
        np.testing.assert_allclose(res["price_level_paths"], 1.01 ** 3)

    def test_income_gap_zeroes_income_only_in_the_window(self):
        res = sim(income_gap=(2, 3), horizon_months=8)
        self.assertEqual(res["income"].tolist(), [2000, 2000, 0, 0, 0, 2000, 2000, 2000])


class TestStressTestsAndTornado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = svc.load_portfolio(FIXTURES, apply_overrides=False)

    def test_stress_table_has_base_and_all_scenarios(self):
        t = fa.run_stress_tests(self.data, horizon_months=24, n_sims=500)
        self.assertEqual(list(t["scenario"]), ["base", *fa.STRESS_SCENARIOS])
        self.assertEqual(float(t.loc[0, "delta_p50"]), 0.0)

    def test_crash_with_holdings_hurts_and_job_loss_raises_ruin(self):
        t = fa.run_stress_tests(self.data, horizon_months=36, n_sims=500, starting_inv=50000.0,
                                monthly_income=2000.0, monthly_expenses_mean=1500.0, monthly_expenses_std=0.0)
        row = t.set_index("scenario")
        self.assertLess(row.loc["gfc_2008", "trough_p50"], row.loc["base", "trough_p50"])
        self.assertLess(row.loc["gfc_2008", "p50"], row.loc["base", "p50"])
        self.assertGreater(row.loc["gfc_2008", "max_drawdown_median_pct"], row.loc["base", "max_drawdown_median_pct"])
        self.assertLess(row.loc["inflation_2022", "p50"], row.loc["base", "p50"])
        self.assertLess(row.loc["job_loss", "p50"], row.loc["base", "p50"])
        self.assertGreaterEqual(row.loc["job_loss", "prob_ruin"], row.loc["base", "prob_ruin"])

    def test_tornado_uses_actual_values_and_orders_by_range(self):
        t, base = fa.run_tornado(self.data, horizon_months=24)
        self.assertFalse(t.empty)
        self.assertTrue(t["range"].is_monotonic_decreasing)
        income = t[t["chiave"] == "monthly_income"].iloc[0]
        self.assertAlmostEqual(income["valore_alto"] / income["valore_basso"], 1.1 / 0.9)
        self.assertGreater(income["delta_high"], 0)
        spend = t[t["chiave"] == "monthly_expenses_mean"].iloc[0]
        self.assertLess(spend["delta_high"], 0)
        self.assertNotIn("1.800", " ".join(t["parametro"]))

    def test_tornado_skips_zero_based_parameters(self):
        t, _ = fa.run_tornado(self.data, horizon_months=12, monthly_investment=0.0)
        self.assertNotIn("monthly_investment", set(t["chiave"]))


class TestEmergencyFund(unittest.TestCase):
    def test_runway_uses_essential_spend_and_recommended_cash_the_p95(self):
        data = svc.load_portfolio(FIXTURES, apply_overrides=False)
        res = svc.run_forecast(data, horizon_months=12, n_sims=2000)
        ef = fa.emergency_fund(data, res)
        self.assertGreater(ef["essential_monthly"], 0.0)
        self.assertLessEqual(ef["essential_monthly"], data.stats["monthly_expenses_mean"] * 1.01)
        self.assertAlmostEqual(ef["runway_months_essential"], ef["current_cash"] / ef["essential_monthly"])
        self.assertAlmostEqual(ef["recommended_cash_p95"], float(np.percentile(res["expenses"][:, :6].sum(axis=1), 95)))
        self.assertAlmostEqual(ef["gap"], max(ef["recommended_cash_p95"] - ef["current_cash"], 0.0))
        self.assertGreater(ef["recommended_cash_p95"], 6 * data.stats["monthly_expenses_mean"] * 0.8)

    def test_no_essential_spend_gives_no_runway(self):
        data = svc.PortfolioData([], type("S", (), {"total_liquid_cash": 1000.0, "total_high_yield_cash": 0.0,
                                                   "total_investments": 0.0, "all_transactions": pd.DataFrame()})(),
                                 pd.DataFrame(), {"monthly_expenses_history": []})
        res = sim(horizon_months=6, n_sims=50)
        ef = fa.emergency_fund(data, res)
        self.assertIsNone(ef["runway_months_essential"])


if __name__ == "__main__":
    unittest.main()
