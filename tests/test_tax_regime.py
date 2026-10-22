# ============================================================
# TEST DEL REGIME FISCALE
# ============================================================
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np

import loris_service as svc
import simulation_engine as se
from banking import tax, user_profile

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


def sim(**kw):
    base = dict(start="2026-01-01", horizon_months=12, n_sims=50, seed=1, monthly_income=0.0,
                monthly_expenses_mean=0.0, monthly_expenses_std=0.0, pac=0.0, starting_cash=0.0,
                starting_inv=0.0, infl_mean=0.0, infl_std=0.0, mkt_mean=0.0, mkt_std=0.0, cash_rate=0.0,
                wage_growth=0.0, annual_fee=0.0)
    base.update(kw)
    return se.run_simulation(**base)


class TestEngineTaxes(unittest.TestCase):
    def test_interest_is_taxed_with_the_cash_rate_not_the_gains_rate(self):
        a = sim(starting_cash=10000.0, cash_rate=0.04, tax_rate=0.26, cash_tax_rate=0.0)
        b = sim(starting_cash=10000.0, cash_rate=0.04, tax_rate=0.26, cash_tax_rate=0.5)
        self.assertAlmostEqual(float(a["cash_history"][0, -1]), 10000 * 1.04, places=4)
        self.assertAlmostEqual(float(b["cash_history"][0, -1]), 10000 * 1.02, places=4)

    def test_securities_stamp_reduces_value_by_the_annual_rate(self):
        r = sim(starting_inv=10000.0, securities_stamp=0.002)
        self.assertAlmostEqual(float(r["invest_history"][0, -1]), 9980.0, places=4)

    def test_account_stamp_only_above_threshold(self):
        rich = sim(starting_cash=20000.0, account_stamp_eur=34.2, account_stamp_threshold=5000.0)
        poor = sim(starting_cash=3000.0, account_stamp_eur=34.2, account_stamp_threshold=5000.0)
        self.assertAlmostEqual(float(rich["cash_history"][0, -1]), 20000 - 34.2, places=4)
        self.assertAlmostEqual(float(poor["cash_history"][0, -1]), 3000.0, places=4)

    def test_default_behaviour_without_stamps_is_unchanged(self):
        r = sim(starting_cash=1000.0, starting_inv=1000.0)
        self.assertAlmostEqual(float(r["nw_final"][0]), 2000.0)


class TestRegimeFromProfile(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("LORIS_USER_PROFILE")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LORIS_USER_PROFILE", None)
        else:
            os.environ["LORIS_USER_PROFILE"] = self._old
        self.tmp.cleanup()

    def profile(self, data):
        path = Path(self.tmp.name) / "profile.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        os.environ["LORIS_USER_PROFILE"] = str(path)

    def test_austria_uses_kest_and_no_stamps(self):
        self.profile({"tax_country": "at"})
        r = tax.tax_regime()
        self.assertEqual((r.country, r.capital_gains, r.securities_stamp_pct), ("AT", 0.275, 0.0))
        self.assertFalse(tax.tax_country_assumed())

    def test_missing_or_unknown_country_falls_back_to_italy_and_says_so(self):
        for data in ({}, {"tax_country": "XX"}):
            self.profile(data)
            self.assertEqual(tax.tax_regime().country, "IT")
            self.assertTrue(tax.tax_country_assumed())

    def test_forecast_reports_regime_and_applies_it(self):
        data = svc.load_portfolio(FIXTURES, apply_overrides=False)
        self.profile({"tax_country": "AT"})
        at = svc.run_forecast(data, horizon_months=12, n_sims=100)
        self.assertEqual((at["params"]["tax_country"], at["params"]["tax_rate"]), ("AT", 0.275))
        self.assertFalse(at["params"]["tax_country_assumed"])
        self.profile({})
        it = svc.run_forecast(data, horizon_months=12, n_sims=100)
        self.assertEqual((it["params"]["tax_country"], it["params"]["tax_rate"]), ("IT", 0.26))
        self.assertTrue(it["params"]["tax_country_assumed"])

    def test_explicit_tax_rate_overrides_the_regime(self):
        data = svc.load_portfolio(FIXTURES, apply_overrides=False)
        self.profile({"tax_country": "AT"})
        r = svc.run_forecast(data, horizon_months=6, n_sims=50, tax_rate=0.10)
        self.assertEqual(r["params"]["tax_rate"], 0.10)


if __name__ == "__main__":
    unittest.main()
