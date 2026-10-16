import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import loris_service as svc
from agents import PortfolioContext, build_portfolio_registry

FIX = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


class TestService(unittest.TestCase):
    def test_load_portfolio_derives_stats_and_categories(self):
        data = svc.load_portfolio(FIX, apply_overrides=False)
        self.assertFalse(data.is_empty)
        self.assertIn("category", data.df_tx.columns)
        self.assertGreater(data.stats["monthly_expenses_mean"], 0)
        self.assertAlmostEqual(data.cash, data.summary.total_liquid_cash + data.summary.total_high_yield_cash)

    def test_agent_forecast_matches_service(self):
        data = svc.load_portfolio(FIX, apply_overrides=False)
        direct = svc.run_forecast(data, horizon_months=12, n_sims=400, cash_rate_pct=2.5)
        reg = build_portfolio_registry(PortfolioContext(data.summary, data.df_tx, data.stats, 2.5))
        via_agent = reg.execute("run_forecast", {"horizon_months": 12, "n_sims": 400}).data
        self.assertAlmostEqual(via_agent["net_worth_p50_median"], round(direct["p50"], 2), places=1)
        self.assertAlmostEqual(via_agent["probability_of_running_out_of_cash_pct"], round(direct["prob_ruin"], 2), places=1)

    def test_forecast_is_deterministic_and_overridable(self):
        data = svc.load_portfolio(FIX, apply_overrides=False)
        a = svc.run_forecast(data, horizon_months=6, n_sims=200)
        b = svc.run_forecast(data, horizon_months=6, n_sims=200)
        self.assertEqual(a["p50"], b["p50"])
        rich = svc.run_forecast(data, horizon_months=6, n_sims=200, starting_cash=1_000_000)
        self.assertGreater(rich["p50"], a["p50"])
        self.assertEqual(a["months"], 6)

    def test_overrides_flow_through_service(self):
        base = svc.load_portfolio(FIX, apply_overrides=False)
        acc = base.summary.accounts_summary.iloc[0]["account_id"]
        ov = {"balance_overrides": {acc: 123456.0}, "category_overrides": {}, "transfer_flags": {},
              "excluded_transactions": [], "manual_transactions": []}
        with_ov = svc.load_portfolio(FIX, overrides=ov)
        self.assertGreater(with_ov.summary.total_net_worth, base.summary.total_net_worth + 100000)


if __name__ == "__main__":
    unittest.main()
