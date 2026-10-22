# ============================================================
# TEST DEL MODELLO DI PREVISIONE — controlli analitici
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np

import simulation_engine as se


def run(**kw):
    base = dict(start="2026-01-01", horizon_months=12, n_sims=4000, seed=7, monthly_income=0.0,
                monthly_expenses_mean=0.0, monthly_expenses_std=0.0, pac=0.0, starting_cash=0.0,
                starting_inv=10000.0, infl_mean=0.0, infl_std=0.0, mkt_mean=0.06, mkt_std=0.16,
                cash_rate=0.0, wage_growth=0.0, annual_fee=0.0)
    base.update(kw)
    return se.run_simulation(**base)


class TestMarketReturns(unittest.TestCase):
    def test_zero_volatility_matches_closed_form(self):
        res = run(mkt_std=0.0, n_sims=50)
        self.assertAlmostEqual(float(res["invest_history"][0, -1]), 10000 * 1.06, places=6)

    def test_expected_annual_return_is_the_input_mean(self):
        """E[1+R] = 1+mu: il rendimento annuo atteso non perde sigma^2/2."""
        res = run(n_sims=20000, horizon_months=12)
        final = res["invest_history"][:, -1] / 10000
        se_mean = final.std() / np.sqrt(len(final))
        self.assertLess(abs(final.mean() - 1.06), 3 * se_mean)

    def test_annual_volatility_matches_input(self):
        res = run(n_sims=20000, horizon_months=12)
        final = res["invest_history"][:, -1] / 10000
        self.assertAlmostEqual(float(final.std()), 0.16, delta=0.01)

    def test_student_t_keeps_mean_and_has_fatter_tails(self):
        normal = run(n_sims=20000, seed=3)["invest_history"][:, -1]
        fat = run(n_sims=20000, seed=3, market_tail_df=3)["invest_history"][:, -1]
        self.assertAlmostEqual(float(fat.mean()) / 10000, 1.06, delta=0.02)
        kurt = lambda x: float(((x - x.mean()) ** 4).mean() / x.var() ** 2)
        self.assertGreater(kurt(fat), kurt(normal))

    def test_tail_df_must_have_finite_variance(self):
        with self.assertRaises(ValueError):
            run(market_tail_df=2)

    def test_fee_reduces_value_by_the_annual_rate(self):
        gross = run(mkt_std=0.0, n_sims=10)["invest_history"][0, -1]
        net = run(mkt_std=0.0, n_sims=10, annual_fee=0.01)["invest_history"][0, -1]
        self.assertAlmostEqual(float(net / gross), 0.99, places=6)


class TestInflationAndWages(unittest.TestCase):
    def test_price_level_differs_between_scenarios(self):
        res = run(infl_mean=0.025, infl_std=0.02, horizon_months=24)
        self.assertGreater(float(np.std(res["price_level_paths"])), 0.0)

    def test_real_value_uses_each_scenarios_own_deflator(self):
        res = run(infl_mean=0.03, infl_std=0.02, horizon_months=24, mkt_std=0.0)
        np.testing.assert_allclose(res["nw_final_real"], res["nw_final"] / res["price_level_paths"])

    def test_zero_inflation_std_gives_identical_price_level(self):
        res = run(infl_mean=0.03, infl_std=0.0, horizon_months=24)
        self.assertAlmostEqual(float(np.std(res["price_level_paths"])), 0.0, places=12)

    def test_wage_growth_defaults_to_inflation(self):
        res = run(monthly_income=1000.0, infl_mean=0.03, wage_growth=None, horizon_months=24)
        self.assertAlmostEqual(float(res["income"][11]), 1000.0)
        self.assertAlmostEqual(float(res["income"][12]), 1030.0)
        self.assertAlmostEqual(float(res["income"][23]), 1030.0)

    def test_zero_wage_growth_keeps_income_flat(self):
        res = run(monthly_income=1000.0, infl_mean=0.03, wage_growth=0.0, horizon_months=36)
        self.assertTrue(np.allclose(res["income"], 1000.0))

    def test_no_hidden_second_salary_phase(self):
        res = run(monthly_income=1000.0, salary2=5000.0, horizon_months=60, wage_growth=0.0)
        self.assertTrue(np.allclose(res["income"], 1000.0))
        res2 = run(monthly_income=1000.0, salary2=5000.0, horizon_months=24, wage_growth=0.0, phase2_start="2027-01-01")
        self.assertAlmostEqual(float(res2["income"][11]), 1000.0)
        self.assertAlmostEqual(float(res2["income"][12]), 5000.0)

    def test_neutral_defaults_without_inputs(self):
        res = se.run_simulation(start="2026-01-01", horizon_months=3, n_sims=10, seed=1)
        self.assertEqual(res["initial_nw"], 0.0)
        self.assertTrue(np.allclose(res["income"], 0.0))


class TestServiceWiring(unittest.TestCase):
    def test_volatility_and_fee_reach_the_engine(self):
        import loris_service as svc
        import bank_data_manager as bdm
        fixtures = Path(__file__).resolve().parent / "fixtures" / "mock_statements"
        data = svc.load_portfolio(fixtures, apply_overrides=False)
        low = svc.run_forecast(data, horizon_months=24, n_sims=2000, annual_volatility_pct=5.0)
        high = svc.run_forecast(data, horizon_months=24, n_sims=2000, annual_volatility_pct=30.0)
        self.assertLess(low["p95"] - low["p5"], high["p95"] - high["p5"])
        self.assertEqual(low["params"]["annual_fee_pct"], svc.FORECAST_DEFAULTS["annual_fee_pct"])


if __name__ == "__main__":
    unittest.main()
