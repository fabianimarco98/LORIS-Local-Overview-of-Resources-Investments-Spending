# ============================================================
# UNIT TESTS — WALLET APP (BUDGETBAKERS) PARSER & GROUNDING
# ============================================================
import sys
import unittest
from pathlib import Path
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from banking.parsers import WalletAppParser, parse_bank_statement, BankStatement
from banking.portfolio import PortfolioAggregator
from banking.guardrails import FinancialFactSheet
from banking.local_llm import LocalLLMClient
import bank_data_manager as bdm


SAMPLE_WALLET_CSV = """account;category;currency;amount;ref_currency_amount;type;payment_type;payment_type_local;note;date;gps_latitude;gps_longitude;gps_accuracy_in_meters;warranty_in_month;transfer;payee;labels;envelope_id;custom_category
Conto Corrente;Pub e Ristoranti FUORI;EUR;-39,00;-39,00;Spese;CASH;Contanti;;2026-10-11 00:03:25;;;;0;false;;;1002;false
Conto Corrente;Spesa;EUR;-30,00;-30,00;Spese;CASH;Contanti;;2026-10-10 23:32:38;;;;0;false;;;1000;false
Conto Corrente;Salute;EUR;-80,00;-80,00;Spese;CASH;Contanti;Visita specialistica;2026-10-10 11:31:04;;;;0;false;;;8000;false
Conto Corrente;Consulenza;EUR;-52,83;-52,83;Spese;TRANSFER;Bonifico bancario;;2026-10-02 12:00:00;;;;0;false;;;8004;false
Conto Corrente;Affitto;EUR;-800,00;-800,00;Spese;CASH;Contanti;;2026-10-02 12:00:00;;;;0;false;;;3000;false
"""


class TestWalletAppParser(unittest.TestCase):
    def setUp(self):
        self.parser = WalletAppParser()

    def test_can_parse_signature(self):
        self.assertTrue(self.parser.can_parse(SAMPLE_WALLET_CSV, "report_2026-10-11.csv"))
        self.assertTrue(self.parser.can_parse(SAMPLE_WALLET_CSV.encode("utf-8"), "wallet_export.csv"))
        self.assertFalse(self.parser.can_parse("col1,col2,col3\n1,2,3", "random.csv"))

    def test_parse_transactions_and_features(self):
        stmt = self.parser.parse(SAMPLE_WALLET_CSV, "report_2026-10-11.csv")
        self.assertEqual(stmt.institution, "Wallet App (BudgetBakers)")
        self.assertEqual(stmt.account_type, "ExpenseTracker")
        self.assertEqual(stmt.asset_class, "EXPENSE_TRACKER")
        self.assertEqual(stmt.ending_balance, 0.0)  # Deve essere zero per non alterare il patrimonio
        self.assertEqual(len(stmt.transactions), 5)

        tx = stmt.transactions
        # Verifica importi
        self.assertIn(-800.0, tx["amount"].values)
        self.assertAlmostEqual(tx["amount"].sum(), -1001.83)
        self.assertTrue(all(tx["amount"] < 0))

        # Verifica categorie
        self.assertIn("wallet_category", tx.columns)
        self.assertIn("payment_type", tx.columns)
        self.assertIn("is_cash", tx.columns)

        # Verifica contanti vs bonifici
        cash_count = tx["is_cash"].sum()
        self.assertEqual(cash_count, 4)  # 4 CASH, 1 TRANSFER

        # Note e descrizioni
        note_rows = tx[tx["wallet_category"] == "Salute"]
        self.assertTrue(any("Visita specialistica" in str(d) for d in note_rows["description"]))

    def test_net_worth_isolation_in_portfolio(self):
        """Verifica fondamentale: Wallet non deve intaccare o ridurre il net worth reale delle banche."""
        bank_stmt = BankStatement(
            account_id="Revolut_Checking",
            institution="Revolut",
            account_type="Checking",
            asset_class="LIQUID_CASH",
            ending_balance=1500.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-10-01"), "amount": -50.0, "category": "Spesa", "is_internal_transfer": False}
            ])
        )

        wallet_stmt = self.parser.parse(SAMPLE_WALLET_CSV, "report_wallet.csv")

        aggregator = PortfolioAggregator([bank_stmt, wallet_stmt])
        summary = aggregator.aggregate()

        # Il patrimonio netto deve essere ESATTAMENTE quello della banca (€ 1500), NON € 1500 - € 1001.83
        self.assertAlmostEqual(summary.total_net_worth, 1500.0)
        self.assertAlmostEqual(summary.total_liquid_cash, 1500.0)
        self.assertTrue(summary.has_wallet_tracker)
        self.assertAlmostEqual(summary.wallet_summary["total_expenses"], 1001.83)
        self.assertAlmostEqual(summary.wallet_summary["cash_expenses"], 949.00)

    def test_guardrails_fact_sheet_grounding(self):
        """Verifica che il modello LLM riceva i fatti certificati di Wallet e i vincoli anti-allucinazione."""
        fact_sheet = FinancialFactSheet(
            net_worth=2868.20,
            liquid_cash=103.87,
            high_yield_cash=2764.33,
            investments=0.0,
            monthly_burn_rate=548.08,
            cash_buffer_months=5.2,
            cash_yield_pct=2.5,
            annual_interest_est=69.11,
            has_wallet_tracker=True,
            wallet_total_expenses=19574.96,
            wallet_cash_expenses=19046.66,
            wallet_electronic_expenses=528.30,
            wallet_tx_count=416,
            wallet_cash_ratio_pct=97.3,
            wallet_top_categories={"Affitto": 8038.0, "Salute": 2365.61, "Spesa": 2271.74},
            wallet_date_range_str="dal 2026-01-02 al 2026-10-11"
        )

        prompt_block = fact_sheet.to_prompt_grounding_block()
        self.assertIn("DATI INTEGRATIVI DALL'APP SPESE (WALLET", prompt_block)
        self.assertIn("19,574.96", prompt_block)
        self.assertIn("19,046.66", prompt_block)
        self.assertIn("CONTANTI (CASH)", prompt_block)
        self.assertIn("NON sottrarre mai il totale di Wallet dal patrimonio netto", prompt_block)
        self.assertIn(19574.96, fact_sheet.verified_numbers_set)
        self.assertIn(19046.66, fact_sheet.verified_numbers_set)

    def test_compute_bank_monthly_statistics_filtering(self):
        """Verifica il filtro della vista 'all', 'banks', 'wallet'."""
        wallet_stmt = self.parser.parse(SAMPLE_WALLET_CSV, "report_wallet.csv")
        df_w = wallet_stmt.transactions.copy()
        df_w["is_tracker"] = True
        df_w["is_internal_transfer"] = False

        df_b = pd.DataFrame([
            {"date": pd.Timestamp("2026-10-05"), "amount": -100.0, "category": "Ristorante", "is_tracker": False, "is_internal_transfer": False},
            {"date": pd.Timestamp("2026-10-01"), "amount": 2000.0, "category": "Stipendio", "is_tracker": False, "is_internal_transfer": False},
        ])

        df_all = pd.concat([df_b, df_w], ignore_index=True)

        stats_all = bdm.compute_bank_monthly_statistics(df_all, filter_source="all")
        stats_banks = bdm.compute_bank_monthly_statistics(df_all, filter_source="banks")
        stats_wallet = bdm.compute_bank_monthly_statistics(df_all, filter_source="wallet")

        self.assertTrue(stats_all["has_wallet_data"])
        self.assertAlmostEqual(stats_banks["total_outflow"], 100.0)
        self.assertAlmostEqual(stats_wallet["total_outflow"], 1001.83)
        self.assertAlmostEqual(stats_all["total_outflow"], 1101.83)


if __name__ == "__main__":
    unittest.main()
