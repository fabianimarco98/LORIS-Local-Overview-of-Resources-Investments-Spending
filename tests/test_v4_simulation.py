# ============================================================
# UNIT TESTS — V4_SPECIALE BANKING & MONTE CARLO INTEGRATION
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import numpy as np

import bank_data_manager as bdm
import simulation_engine as se
from banking.anonymizer import PIIScrubber
from banking.portfolio import PortfolioAggregator


class TestV4SpecialeIntegration(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.statements_dir = self.base_dir / "tests" / "fixtures" / "mock_statements"

    def test_load_all_bank_statements(self):
        stmts, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        self.assertGreaterEqual(len(stmts), 3)
        self.assertGreater(summary.total_net_worth, 0.0)
        self.assertGreater(summary.total_liquid_cash, 0.0)
        self.assertGreater(summary.recommended_starting_cash, 0.0)
        self.assertFalse(summary.all_transactions.empty)

    def test_giroconto_elimination_and_categorization(self):
        _, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        self.assertIn("category", df_cat.columns)
        self.assertIn("is_internal_transfer", df_cat.columns)

        # Verifica che il giroconto tra Erste e Trade Republic sia marcato
        giroconti = df_cat[df_cat["category"] == "Giroconto Interno"]
        self.assertGreaterEqual(len(giroconti), 1)

    def test_monthly_statistics(self):
        _, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        stats = bdm.compute_bank_monthly_statistics(df_cat)

        self.assertGreater(stats["monthly_expenses_mean"], 0.0)
        self.assertGreater(stats["detected_salary"], 0.0)
        self.assertFalse(stats["category_summary"].empty)

    def test_monte_carlo_bank_simulation(self):
        _, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        macro, rec, shocks = bdm.load_configs(str(self.base_dir / "input"))

        res = se.run_simulation(
            start="2026-10-01",
            n_sims=500,
            seed=42,
            pac=80.0,
            strategy="dynamic",
            starting_cash=summary.recommended_starting_cash,
            starting_inv=summary.total_investments,
            recurring_df=rec,
            shocks_df=shocks,
            macro_df=macro,
        )

        self.assertEqual(len(res["dates"]), 36)
        self.assertIn("cash", res)
        self.assertIn("cash_history", res)
        self.assertIn("invest", res)
        self.assertIn("nw_final", res)
        self.assertGreater(res["p50"], 0.0)
        self.assertGreaterEqual(res["prob_ruin"], 0.0)

    def test_pure_bank_statements_simulation_without_csv_files(self):
        """Verifica che la simulazione Monte Carlo funzioni al 100% solo da estratti conto senza file CSV ausiliari."""
        _, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        stats = bdm.compute_bank_monthly_statistics(df_cat)

        res = se.run_simulation(
            start="2026-10-01",
            n_sims=300,
            seed=42,
            pac=100.0,
            starting_cash=summary.recommended_starting_cash,
            starting_inv=summary.total_investments,
            recurring_df=None,
            shocks_df=None,
            macro_df=None,
            monthly_expenses_mean=stats["monthly_expenses_mean"],
            monthly_expenses_std=stats["monthly_expenses_std"],
        )

        self.assertEqual(len(res["dates"]), 36)
        self.assertGreater(res["p50"], 0.0)
        self.assertIn("cash_history", res)
        self.assertEqual(res["cash_history"].shape, (300, 36))

    def test_detect_recurring_from_statements(self):
        """Verifica la rilevazione automatica delle spese fisse/ricorrenti dagli estratti conto."""
        _, summary = bdm.load_all_bank_statements(str(self.statements_dir))
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        rec_df = bdm.detect_recurring_from_statements(df_cat)
        self.assertIsInstance(rec_df, pd.DataFrame)
        self.assertIn("name", rec_df.columns)
        self.assertIn("min_cost", rec_df.columns)

    def test_model_catalog_and_cli_detection(self):
        """Verifica il catalogo dei modelli consigliati e il rilevamento CLI di Ollama."""
        from banking.local_llm import LocalLLMClient, RECOMMENDED_MODELS
        client = LocalLLMClient()
        self.assertGreater(len(RECOMMENDED_MODELS), 3)
        cli_ok, _ = client.is_ollama_cli_available()
        self.assertTrue(cli_ok)
        st = client.check_health()
        if st.is_available:
            self.assertTrue(len(st.model_name) > 0)
        else:
            self.assertTrue(st.is_cli_installed)


if __name__ == "__main__":
    unittest.main()
