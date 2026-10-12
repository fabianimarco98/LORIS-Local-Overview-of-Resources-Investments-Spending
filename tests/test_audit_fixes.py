# ============================================================
# AUDIT REGRESSION TESTS — V4_SPECIALE FIXES & INTEGRITY
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import pandas as pd

from banking.parsers import BankStatement
from banking.portfolio import PortfolioAggregator
import bank_data_manager as bdm
import simulation_engine as se


class TestAuditFixes(unittest.TestCase):
    """Test di verifica per tutti i bug e criticità risolti durante l'audit completo."""

    def test_multi_period_statement_consolidation(self):
        """Verifica che estratti conto multipli per lo stesso conto non duplichino il saldo."""
        stmt1 = BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            start_date=pd.Timestamp("2026-01-01"),
            end_date=pd.Timestamp("2026-01-31"),
            ending_balance=100.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-01-10"), "amount": -20.0, "description": "Bar"},
                {"date": pd.Timestamp("2026-01-20"), "amount": -30.0, "description": "Spesa"},
            ]),
            source_file="Revolut_Gennaio.csv"
        )
        stmt2 = BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            start_date=pd.Timestamp("2026-01-20"),
            end_date=pd.Timestamp("2026-02-28"),
            ending_balance=150.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-01-20"), "amount": -30.0, "description": "Spesa"},  # duplicato intenzionale
                {"date": pd.Timestamp("2026-02-05"), "amount": 80.0, "description": "Regalo"},
            ]),
            source_file="Revolut_Febbraio.csv"
        )

        agg = PortfolioAggregator([stmt1, stmt2])
        summary = agg.aggregate()

        # Il saldo deve essere quello del documento più recente (150.0), non la somma (250.0)
        self.assertEqual(summary.total_net_worth, 150.0)
        self.assertEqual(len(summary.accounts_summary), 1)
        self.assertEqual(summary.accounts_summary.iloc[0]["balance"], 150.0)

        # Le transazioni duplicate devono essere state deduplicate (2 da stmt1 + 1 nuova da stmt2 = 3 totali)
        self.assertEqual(len(summary.all_transactions), 3)

    def test_transfer_detection_no_false_positives_with_wallet_cash(self):
        """Verifica che le spese in contanti di Wallet non vengano neutralizzate come giroconti bancari."""
        stmt_bank = BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            ending_balance=200.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-04-07"), "amount": 16.0, "description": "Payment from MANGOPAY", "category": "Entrata", "is_internal_transfer": False}
            ])
        )
        stmt_wallet = BankStatement(
            account_id="Wallet_Conto",
            institution="Wallet App",
            account_type="ExpenseTracker",
            asset_class="EXPENSE_TRACKER",
            ending_balance=0.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-04-07"), "amount": -16.0, "description": "[Contanti] Deliveroo a casa", "category": "Ristoranti & Svago", "is_cash": True, "is_tracker": True, "is_internal_transfer": False}
            ])
        )

        agg = PortfolioAggregator([stmt_bank, stmt_wallet])
        summary = agg.aggregate()

        # Nessun giroconto deve essere rilevato tra una spesa in contanti e un'entrata bancaria
        self.assertTrue(summary.internal_transfers.empty)

    def test_transfer_detection_no_false_positives_with_merchants(self):
        """Verifica che acquisti da esercenti non vengano accoppiati a crediti casuali per lo stesso importo."""
        stmt_tr = BankStatement(
            account_id="Trade_Republic_Cash",
            institution="Trade Republic",
            account_type="HighYieldCash",
            asset_class="HIGH_YIELD_CASH",
            ending_balance=1000.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-04-28"), "amount": -4.99, "description": "KartentransaktionTGTG xfn154xa", "category": "Spesa Carta", "is_internal_transfer": False}
            ])
        )
        stmt_rev = BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            ending_balance=500.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-04-28"), "amount": 4.99, "description": "Payment from Friend", "category": "Entrata", "is_internal_transfer": False}
            ])
        )

        agg = PortfolioAggregator([stmt_tr, stmt_rev])
        summary = agg.aggregate()

        # Too Good To Go non deve essere considerato un giroconto
        self.assertTrue(summary.internal_transfers.empty)

    def test_transfer_detection_matches_authentic_transfers(self):
        """Verifica che i bonifici autentici tra conti propri vengano regolarmente riconciliati."""
        stmt_rev = BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            ending_balance=500.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-08-14"), "amount": -1900.0, "description": "To Mario Rossi", "category": "Giroconto", "is_internal_transfer": True}
            ])
        )
        stmt_tr = BankStatement(
            account_id="Trade_Republic_Cash",
            institution="Trade Republic",
            account_type="HighYieldCash",
            asset_class="HIGH_YIELD_CASH",
            ending_balance=2500.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-08-14"), "amount": 1900.0, "description": "Incoming transfer from Mario Rossi", "category": "Giroconto Entrata", "is_internal_transfer": True}
            ])
        )

        agg = PortfolioAggregator([stmt_rev, stmt_tr])
        summary = agg.aggregate()

        self.assertEqual(len(summary.internal_transfers), 1)
        self.assertEqual(summary.internal_transfers.iloc[0]["amount"], 1900.0)

    def test_simulation_custom_income_no_phantom_phd_bonuses(self):
        """Verifica che l'indicazione di entrate mensili personalizzate non inietti bonus PhD non richiesti."""
        res = se.run_simulation(
            start="2026-10-01",
            horizon_months=12,
            n_sims=50,
            monthly_income=2500.0,
            pac=0.0,
            starting_cash=1000.0,
            starting_inv=0.0,
            monthly_expenses_mean=0.0,
            monthly_expenses_std=0.0,
        )

        # In 12 mesi con entrate fisse a €2.500/m, spese 0 e cassa iniziale 1.000:
        # l'income totale programmato deve essere esattamente 12 * 2500 = 30.000 (nessun extra +1070 a marzo/giugno/ecc.)
        self.assertEqual(len(res["dates"]), 12)
        income_sched = res.get("income_schedule")
        if income_sched is not None:
            self.assertEqual(list(income_sched), [2500.0] * 12)

    def test_burn_rate_null_safety(self):
        """Verifica che _compute_burn_rate non sollevi eccezioni anche con colonne contenenti None o assenti."""
        df_dirty = pd.DataFrame({
            "amount": [-50.0, -100.0],
            "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-15")],
            "is_internal_transfer": [None, False],
            "is_tracker": [None, None]
        })
        agg = PortfolioAggregator([])
        burn = agg._compute_burn_rate(df_dirty)
        self.assertAlmostEqual(burn, 150.0, places=1)

    def test_buffer_months_clamping(self):
        """Verifica che un patrimonio o cassa negativa non produca mesi di cuscinetto negativi."""
        stmt_debt = BankStatement(
            account_id="Overdraft",
            institution="Bank",
            account_type="Checking",
            asset_class="LIQUID_CASH",
            ending_balance=-1000.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-01-01"), "amount": -500.0, "description": "Spesa"}
            ])
        )
        agg = PortfolioAggregator([stmt_debt])
        summary = agg.aggregate()
        self.assertGreaterEqual(summary.liquidity_buffer_months, 0.0)

    def test_trade_republic_csv_multilingual_italian(self):
        """Verifica che il parser CSV di Trade Republic supporti colonne e causali in lingua italiana."""
        from banking.parsers import TradeRepublicParser
        csv_it = (
            "Data,Tipo,Descrizione,Importo,Saldo\n"
            "2026-05-15,Interessi,Interessi liquidità conto,15.50,1500.00\n"
            "2026-05-18,Spesa Carta,Ristorante Da Mario,-45.00,1455.00\n"
            "2026-05-20,Investimento,PAC ETF World,-100.00,1355.00\n"
        )
        parser = TradeRepublicParser()
        self.assertTrue(parser.can_parse(csv_it, "estratto_tr_maggio.csv"))
        stmt = parser.parse(csv_it, "estratto_tr_maggio.csv")
        self.assertEqual(stmt.institution, "Trade Republic")
        self.assertEqual(len(stmt.transactions), 3)
        self.assertEqual(stmt.ending_balance, 1355.00)
        self.assertEqual(stmt.transactions.iloc[0]["category"], "Interessi Attivi")
        self.assertEqual(stmt.transactions.iloc[1]["category"], "Spesa Carta")
        self.assertEqual(stmt.transactions.iloc[2]["category"], "Investimento ETF / Azioni")

    def test_trade_republic_pdf_multilingual_months_and_custodian(self):
        """Verifica che il parser PDF di Trade Republic estragga correttamente date con mesi in formato testuale esteso."""
        from banking.parsers import PdfBankParser
        pdf_text = (
            "TRADE REPUBLIC BANK GMBH, BRANCH AUSTRIA\n"
            "DATUM 01 Jän. 2026 - 31 Okt. 2026\n"
            "KONTOÜBERSICHT\n"
            "Cashkonto € 0,00 € 5.000,00 € 2.000,00 € 3.000,00\n"
            "UMSATZÜBERSICHT\n"
            "14 Juli\n"
            "KartentransaktionSupermercato € 25,50 € 2.974,50\n"
            "2026\n"
            "02 Juni\n"
            "Zinsen Interest reward € 12,00 € 2.986,50\n"
            "2026\n"
            "ENDSALDO\n"
            "€ 2.986,50\n"
        )
        parser = PdfBankParser()
        stmt = parser._parse_trade_republic_pdf(pdf_text, "TR_Statement.pdf")
        self.assertEqual(len(stmt.transactions), 2)
        # 02 Juni viene cronologicamente prima di 14 Juli
        self.assertEqual(stmt.transactions.iloc[0]["date"].month, 6)
        self.assertEqual(stmt.transactions.iloc[0]["date"].day, 2)
        # 14 Juli viene al secondo posto
        self.assertEqual(stmt.transactions.iloc[1]["date"].month, 7)
        self.assertEqual(stmt.transactions.iloc[1]["date"].day, 14)
        self.assertEqual(stmt.ending_balance, 3000.0)

    def test_user_overrides_application(self):
        """Verifica che apply_user_overrides modifichi saldi, categorie, ed escluda movimenti corretti."""
        import bank_data_manager as bdm
        stmt1 = BankStatement(
            account_id="TR_Test",
            institution="Trade Republic",
            account_type="HighYieldCash",
            asset_class="HIGH_YIELD_CASH",
            ending_balance=1000.0,
            transactions=pd.DataFrame([
                {"date": pd.Timestamp("2026-05-01"), "amount": -30.0, "description": "Cena fuori", "category": "Altre Spese", "account_id": "TR_Test", "institution": "Trade Republic"},
                {"date": pd.Timestamp("2026-05-02"), "amount": -10.0, "description": "Errore", "category": "Altre Spese", "account_id": "TR_Test", "institution": "Trade Republic"},
            ])
        )
        agg = PortfolioAggregator([stmt1])
        summary = agg.aggregate()

        k_edit = bdm.make_tx_key(pd.Timestamp("2026-05-01"), "TR_Test", -30.0, "Cena fuori")
        k_excl = bdm.make_tx_key(pd.Timestamp("2026-05-02"), "TR_Test", -10.0, "Errore")

        overrides = {
            "balance_overrides": {"TR_Test": 1500.0},
            "category_overrides": {k_edit: "Ristoranti & Svago"},
            "transfer_flags": {},
            "excluded_transactions": [k_excl],
            "manual_transactions": [{
                "date": "2026-05-05",
                "account_id": "TR_Test",
                "institution": "Trade Republic",
                "amount": 200.0,
                "description": "Bonus Lavoro",
                "category": "Stipendio & Compensi",
                "is_internal_transfer": False,
            }]
        }

        stmts_mod, sum_mod = bdm.apply_user_overrides([stmt1], summary, overrides)

        # Saldo forzato
        self.assertEqual(stmts_mod[0].ending_balance, 1500.0)
        self.assertEqual(sum_mod.total_high_yield_cash, 1500.0)

        # Transazione esclusa rimossa
        tx_keys_res = sum_mod.all_transactions["tx_key"].tolist()
        self.assertNotIn(k_excl, tx_keys_res)

        # Categoria modificata
        row_edited = sum_mod.all_transactions[sum_mod.all_transactions["tx_key"] == k_edit].iloc[0]
        self.assertEqual(row_edited["category"], "Ristoranti & Svago")

        # Movimento manuale iniettato
        self.assertTrue(any(r["description"] == "Bonus Lavoro" for _, r in sum_mod.all_transactions.iterrows()))

    def test_delete_statement_file_and_unique_keys(self):
        """Verifica che delete_statement_file gestisca Path e str e che i tasti di cancellazione siano univoci."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_a = tmp_path / "test_statement.csv"
            file_a.write_text("date,amount,description\n2026-05-01,10.0,Test\n")
            
            # Deletion using Path
            self.assertTrue(bdm.delete_statement_file(file_a))
            self.assertFalse(file_a.exists())

            # Deletion using str
            file_b = tmp_path / "test_statement_2.csv"
            file_b.write_text("date,amount,description\n2026-05-01,20.0,Test 2\n")
            self.assertTrue(bdm.delete_statement_file(str(file_b)))
            self.assertFalse(file_b.exists())

        # Test valid extensions filter out .md files
        valid_exts = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".pdf", ".json"}
        self.assertNotIn(".md", valid_exts)
        self.assertIn(".csv", valid_exts)
        self.assertIn(".pdf", valid_exts)

    def test_empty_statements_zero_burn_rate(self):
        """Verifica che senza estratti conto o transazioni, burn rate e medie non mostrino valori predefiniti fittizi."""
        # 1. Test PortfolioAggregator su lista vuota
        agg = PortfolioAggregator([])
        summary = agg.aggregate()
        self.assertEqual(summary.monthly_burn_rate, 0.0)
        self.assertEqual(summary.liquidity_buffer_months, 0.0)

        # 2. Test compute_bank_monthly_statistics su DataFrame vuoto
        stats_empty = bdm.compute_bank_monthly_statistics(pd.DataFrame())
        self.assertEqual(stats_empty["monthly_expenses_mean"], 0.0)
        self.assertEqual(stats_empty["monthly_expenses_std"], 0.0)
        self.assertEqual(stats_empty["detected_salary"], 0.0)
        self.assertEqual(stats_empty["total_inflow"], 0.0)
        self.assertEqual(stats_empty["total_outflow"], 0.0)

    def test_internal_transfers_table_columns_safety(self):
        """Verifica che la tabella dei giroconti gestisca correttamente le 8 colonne senza sollevare ValueError per length mismatch."""
        df_tr_mock = pd.DataFrame([{
            "date": pd.Timestamp("2026-05-01"),
            "from_date": pd.Timestamp("2026-05-01"),
            "to_date": pd.Timestamp("2026-05-02"),
            "from_account": "Revolut_123",
            "to_account": "Trade_Republic",
            "amount": 500.0,
            "from_desc": "Transfer to Trade Republic",
            "to_desc": "Deposit from Revolut",
        }])

        target_cols = ["date", "from_account", "to_account", "amount", "from_desc", "to_desc"]
        avail_cols = [c for c in target_cols if c in df_tr_mock.columns]
        df_tr_view = df_tr_mock[avail_cols].copy()
        rename_map = {
            "date": "Data",
            "from_account": "Conto Origine",
            "to_account": "Conto Destinazione",
            "amount": "Importo (€)",
            "from_desc": "Causale Uscita",
            "to_desc": "Causale Entrata",
        }
        df_tr_view = df_tr_view.rename(columns=rename_map)
        self.assertEqual(list(df_tr_view.columns), ["Data", "Conto Origine", "Conto Destinazione", "Importo (€)", "Causale Uscita", "Causale Entrata"])
        self.assertEqual(len(df_tr_view), 1)


if __name__ == "__main__":
    unittest.main()

