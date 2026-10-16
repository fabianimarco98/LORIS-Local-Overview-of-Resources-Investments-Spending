# ============================================================
# TESTS — BILINGUAL i18n, RETROSPECTIVE ANALYTICS & FORECASTING
# ============================================================
import sys
from pathlib import Path
import unittest
import pandas as pd
import numpy as np

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import os
os.environ.setdefault("LORIS_USER_PROFILE", str(Path(__file__).resolve().parent / "fixtures" / "user_profile.json"))

import i18n
import bank_data_manager as bdm
import simulation_engine as se
from banking.parsers import GenericBankParser, DigitalBankParser, clean_numeric_amount


class TestBilingualAndAnalytics(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "mock_statements"

    def test_i18n_translation_keys(self):
        """Verifica che tutte le chiavi supportino sia 'it' che 'en'."""
        keys = [
            "app_title", "tab_overview", "tab_analytics", "tab_transactions",
            "tab_forecasting", "tab_ai", "tab_settings", "total_net_worth",
            "historical_title", "avg_monthly_spending", "forecast_title",
            "pessimistic_p5", "median_p50", "optimistic_p95", "ruin_probability"
        ]
        for k in keys:
            t_it = i18n.t(k, "it")
            t_en = i18n.t(k, "en")
            self.assertNotEqual(t_it, k, f"Key {k} missing Italian translation")
            self.assertNotEqual(t_en, k, f"Key {k} missing English translation")
            self.assertNotEqual(t_it, t_en, f"Key {k} should have different IT and EN translations")

    def test_category_translations(self):
        """Verifica la traduzione dei nomi delle categorie in inglese."""
        cats = [
            ("Affitto", "Rent & Housing"),
            ("Spesa & Alimentari", "Groceries & Food"),
            ("Bollette & Utenze", "Utilities & Bills"),
            ("Palestra & Sport", "Gym & Sports"),
            ("Ristoranti & Svago", "Dining & Leisure"),
            ("Trasporti & Viaggi", "Transport & Travel"),
            ("Abbonamenti & IT", "Subscriptions & Tech"),
            ("Stipendio", "Salary & Income"),
        ]
        for it_name, expected_en in cats:
            trans = i18n.get_category_translation(it_name, "en")
            self.assertEqual(trans, expected_en)
            self.assertEqual(i18n.get_category_translation(it_name, "it"), it_name)

    def test_retrospective_analytics_computation(self):
        """Verifica le statistiche retrospettive empiriche (cashflow, savings rate, top payees)."""
        _, summary = bdm.load_all_bank_statements(str(self.fixtures_dir))
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        stats = bdm.compute_bank_monthly_statistics(df_cat)

        self.assertIn("total_tracked_months", stats)
        self.assertIn("total_inflow", stats)
        self.assertIn("total_outflow", stats)
        self.assertIn("net_savings", stats)
        self.assertIn("average_savings_rate", stats)
        self.assertIn("top_payees", stats)
        self.assertIn("monthly_by_category", stats)
        self.assertIn("discretionary_split", stats)

        self.assertGreater(stats["total_inflow"], 0.0)
        self.assertGreater(stats["total_outflow"], 0.0)
        self.assertIsInstance(stats["top_payees"], pd.DataFrame)
        self.assertFalse(stats["top_payees"].empty)
        self.assertIn("ratio", stats["discretionary_split"])

    def test_generalized_simulation_horizons(self):
        """Verifica che la simulazione Monte Carlo funzioni con orizzonti temporali arbitrari (12, 24, 60 mesi)."""
        for h in [12, 24, 60]:
            res = se.run_simulation(
                horizon_months=h,
                n_sims=300,
                seed=42,
                monthly_income=2200.0,
                monthly_expenses_mean=1400.0,
                monthly_expenses_std=180.0,
                starting_cash=2500.0,
                starting_inv=500.0,
                pac=150.0
            )
            self.assertEqual(len(res["dates"]), h)
            self.assertIn("p5", res)
            self.assertIn("p50", res)
            self.assertIn("p95", res)
            self.assertIn("prob_ruin", res)
            self.assertIn("p50_real", res)
            self.assertGreater(res["p95"], res["p50"])
            self.assertGreater(res["p50"], res["p5"])
            self.assertGreaterEqual(res["prob_ruin"], 0.0)
            self.assertLessEqual(res["prob_ruin"], 100.0)

    def test_revolut_parser_internal_transfers_and_reverted(self):
        """Verifica che il parser Revolut escluda i REVERTED e identifichi i trasferimenti a se stessi."""
        csv_content = """Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
Transfer,Current,2026-09-01 10:00:00,2026-09-01 10:00:00,To Mario Rossi,-100.00,0,EUR,COMPLETED,900.00
Card Payment,Current,2026-09-02 12:00:00,2026-09-02 12:00:00,Supermarket,-50.00,0,EUR,COMPLETED,850.00
Transfer,Current,2026-09-03 14:00:00,2026-09-03 14:00:00,To pocket EUR Smartband from EUR,10.00,0,EUR,COMPLETED,860.00
Card Payment,Current,2026-09-04 15:00:00,,Failed Vendor,-30.00,0,EUR,REVERTED,
Deposit,Current,2026-09-05 09:00:00,2026-09-05 09:00:00,Top-up by *7292,500.00,0,EUR,COMPLETED,1360.00
"""
        parser = DigitalBankParser()
        stmt = parser.parse(csv_content, "Revolut_Test.csv")
        self.assertEqual(len(stmt.transactions), 4)  # 5 rows minus 1 REVERTED
        
        # Check internal flags
        tx = stmt.transactions
        self.assertTrue(tx[tx["description"] == "To Mario Rossi"]["is_internal_transfer"].iloc[0])
        self.assertTrue(tx[tx["description"] == "To pocket EUR Smartband from EUR"]["is_internal_transfer"].iloc[0])
        self.assertTrue(tx[tx["description"] == "Top-up by *7292"]["is_internal_transfer"].iloc[0])
        self.assertFalse(tx[tx["description"] == "Supermarket"]["is_internal_transfer"].iloc[0])


if __name__ == "__main__":
    unittest.main()
