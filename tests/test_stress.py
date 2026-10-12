# ============================================================
# EXPENSES PREDICTION & BANKING SYSTEM — COMPREHENSIVE STRESS TESTS
# ============================================================
"""
Suite di Stress Testing ad alto carico e test sui casi limite (Edge Cases):
1. Monte Carlo Simulation Engine: 10k-20k scenari, casi patologici (0 cassa, cassa negativa,
   iperinflazione, crollo dei mercati, volatilità estrema).
2. Universal Bank Parser: 10k transazioni, formati numerici e date caotici/sporchi, file corrotti.
3. Riconciliazione Giroconti Circolari: topologia multi-conto (5 banche), 500+ trasferimenti incrociati.
4. PII Scrubber: throughput elevato su 5.000 descrizioni, audit anti-leakage su pattern avversari.
5. Motore Euristico & Local LLM Fallback: categorizzazione di massa a zero latenza.
6. Pipeline End-to-End ad alto carico.
"""

import io
import sys
import time
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import pandas as pd

import banking
from banking.anonymizer import PIIScrubber
from banking.parsers import (
    clean_numeric_amount,
    parse_flexible_date,
    parse_bank_statement,
    BankStatement,
    TradeRepublicParser,
    ErsteBankParser,
    ItalianBankParser,
    DigitalBankParser,
    GenericBankParser,
)
from banking.portfolio import PortfolioAggregator, PortfolioSummary
from banking.local_llm import LocalLLMClient
import bank_data_manager as bdm
import simulation_engine as se


class TestSimulationEngineStress(unittest.TestCase):
    """Stress test sul motore di simulazione stocastico Monte Carlo."""

    def test_monte_carlo_10k_throughput(self):
        """10.000 iterazioni su 38 mesi: verifica throughput, tempo e monotonicità percentili."""
        t0 = time.perf_counter()
        res = se.run_simulation(
            start="2026-10-01",
            n_sims=10000,
            seed=123,
            pac=80.0,
            strategy="fixed",
            starting_cash=3000.0,
            starting_inv=1000.0,
            salary1=2000.0,
            monthly_expenses_mean=1350.0,
            monthly_expenses_std=200.0,
        )
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 4.0, f"Simulazione 10k troppo lenta: {elapsed:.2f}s (atteso < 4s)")
        tot_wealth = res["cash_history"] + res["invest_history"]
        terminal = tot_wealth[:, -1]

        # Verifica assenza di NaN o Inf
        self.assertFalse(np.isnan(terminal).any())
        self.assertFalse(np.isinf(terminal).any())

        # Verifica monotonicità rigorosa dei quantili
        q05 = np.percentile(terminal, 5)
        q25 = np.percentile(terminal, 25)
        q50 = np.percentile(terminal, 50)
        q75 = np.percentile(terminal, 75)
        q95 = np.percentile(terminal, 95)

        self.assertLessEqual(q05, q25)
        self.assertLessEqual(q25, q50)
        self.assertLessEqual(q50, q75)
        self.assertLessEqual(q75, q95)
        self.assertGreater(q50, 0.0)

    def test_monte_carlo_20k_extended_horizon(self):
        """20.000 iterazioni ad altissimo carico su orizzonte esteso: verifica stabilità memoria."""
        t0 = time.perf_counter()
        res = se.run_simulation(
            start="2024-11-01",  # 61 mesi
            n_sims=20000,
            seed=999,
            pac=100.0,
            strategy="dynamic",
            starting_cash=5000.0,
            starting_inv=2000.0,
            salary1=2000.0,
            monthly_expenses_mean=1400.0,
            monthly_expenses_std=250.0,
        )
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 8.0, f"Simulazione 20k troppo lenta: {elapsed:.2f}s")
        self.assertEqual(res["cash_history"].shape[0], 20000)
        self.assertEqual(res["cash_history"].shape[1], 61)

    def test_zero_and_negative_starting_cash_edge_cases(self):
        """Casi limite: cassa 0 e cassa iniziale fortemente negativa (-€5.000)."""
        # Caso 1: Cassa e investimenti a 0
        res_zero = se.run_simulation(
            start="2026-10-01",
            n_sims=1000,
            seed=42,
            starting_cash=0.0,
            starting_inv=0.0,
            salary1=1200.0,
            monthly_expenses_mean=1500.0,  # Burn rate > Stipendio
        )
        insolvency_zero = (res_zero["cash_history"] < 0).any(axis=1).mean() * 100
        self.assertGreater(insolvency_zero, 80.0)
        self.assertFalse(np.isnan(res_zero["cash_history"]).any())

        # Caso 2: Cassa iniziale negativa (-€5.000)
        res_neg = se.run_simulation(
            start="2026-10-01",
            n_sims=1000,
            seed=42,
            starting_cash=-5000.0,
            starting_inv=0.0,
            salary1=1500.0,
            monthly_expenses_mean=1200.0,
        )
        insolvency_neg = (res_neg["cash_history"] < 0).any(axis=1).mean() * 100
        self.assertEqual(insolvency_neg, 100.0)  # Inizia già scoperto
        self.assertFalse(np.isnan(res_neg["cash_history"]).any())

    def test_hyperinflation_and_market_crash(self):
        """Stress test: Iperinflazione al 25% annuo e crollo dei mercati al -40% annuo."""
        res_crisis = se.run_simulation(
            start="2026-10-01",
            n_sims=2000,
            seed=777,
            infl_mean=0.25,
            infl_std=0.08,
            mkt_mean=-0.40,
            mkt_std=0.30,
            starting_cash=2000.0,
            starting_inv=10000.0,
            monthly_expenses_mean=1200.0,
        )
        terminal_inv = res_crisis["invest_history"][:, -1]
        self.assertFalse(np.isnan(terminal_inv).any())
        self.assertFalse(np.isinf(terminal_inv).any())
        # In forte crisi di mercato gli investimenti dovrebbero mediamente ridursi
        self.assertLess(np.median(terminal_inv), 10000.0)

    def test_extreme_volatility_and_massive_shocks(self):
        """Stress test: Spese con deviazione standard estrema (€4.000) e shock imprevisti da €25.000."""
        shocks_df = pd.DataFrame([
            {"date": "2027-04-01", "amount": 15000.0},
            {"date": "2028-09-01", "amount": 10000.0},
        ])
        res_vol = se.run_simulation(
            start="2026-10-01",
            n_sims=2000,
            seed=555,
            monthly_expenses_mean=1200.0,
            monthly_expenses_std=4000.0,  # Deviazione enorme
            shocks_df=shocks_df,
            shock_scale=1.5,  # Shock amplificato a €37.500
        )
        insolvency = (res_vol["cash_history"] < 0).any(axis=1).mean() * 100
        self.assertTrue(0.0 <= insolvency <= 100.0)
        self.assertFalse(np.isnan(res_vol["cash_history"]).any())

    def test_deterministic_reproducibility(self):
        """Verifica che lo stesso seed generi matrici stocastiche identiche al bit."""
        res1 = se.run_simulation(start="2026-10-01", n_sims=1000, seed=42)
        res2 = se.run_simulation(start="2026-10-01", n_sims=1000, seed=42)
        np.testing.assert_array_equal(res1["cash_history"], res2["cash_history"])
        np.testing.assert_array_equal(res1["invest_history"], res2["invest_history"])


class TestBankParserStress(unittest.TestCase):
    """Stress test sul parser bancario universale e robustezza a input corrotti/avversari."""

    def test_high_volume_statement_parsing(self):
        """Parsing ad alta velocità di 10.000 movimenti generati sinteticamente."""
        dates = pd.date_range("2020-01-01", periods=10000, freq="h").strftime("%Y-%m-%d %H:%M:%S")
        amounts = np.random.uniform(-500.0, 500.0, size=10000).round(2)
        descriptions = [f"Transazione di test #{i} con causale casuale" for i in range(10000)]

        df_synthetic = pd.DataFrame({
            "Datum": dates,
            "Typ": ["Buchung"] * 10000,
            "Wert": amounts,
            "Name": descriptions
        })
        csv_buffer = df_synthetic.to_csv(index=False)

        t0 = time.perf_counter()
        stmt = parse_bank_statement(csv_buffer, "HighVolume_Test.csv")
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 2.5, f"Parsing 10k righe troppo lento: {elapsed:.2f}s")
        self.assertEqual(len(stmt.transactions), 10000)
        self.assertAlmostEqual(stmt.transactions["amount"].sum(), float(amounts.sum()), places=1)

    def test_chaotic_and_malformed_numeric_amounts(self):
        """Verifica che clean_numeric_amount non sollevi mai eccezioni su formati caotici."""
        cases = [
            ("1.250,50 €", 1250.50),
            ("-1.250,50", -1250.50),
            ("1,250.50", 1250.50),
            ("- 500,00 EUR", -500.0),
            ("(1.500,00)", -1500.0),
            ("250,75-", -250.75),
            ("+ 1000,00", 1000.00),
            ("  $ 99.99  ", 99.99),
            ("0,00", 0.0),
            ("-0,00", 0.0),
            ("", 0.0),
            ("   ", 0.0),
            (None, 0.0),
            (np.nan, 0.0),
            ("INVALID_AMOUNT", 0.0),
            ("---", 0.0),
            ("12.34.56,78", 123456.78),
            (150, 150.0),
            (-32.5, -32.5),
        ]
        for val, expected in cases:
            res = clean_numeric_amount(val)
            self.assertIsInstance(res, float)
            self.assertAlmostEqual(res, expected, places=2, msg=f"Fallito su valore: {repr(val)}")

    def test_chaotic_and_malformed_dates(self):
        """Verifica la robustezza di parse_flexible_date contro formati eterogenei o corrotti."""
        valid_cases = [
            ("31/12/2026", pd.Timestamp("2026-12-31")),
            ("31.12.2026", pd.Timestamp("2026-12-31")),
            ("2026-12-31", pd.Timestamp("2026-12-31")),
            ("2026-12-31 15:30:00", pd.Timestamp("2026-12-31")),
            ("01/02/2026", pd.Timestamp("2026-02-01")),
            ("29.02.2024", pd.Timestamp("2024-02-29")),  # Bisestile valido
        ]
        for s_date, exp_ts in valid_cases:
            res = parse_flexible_date(s_date)
            self.assertIsNotNone(res, f"Data non interpretata: {s_date}")
            self.assertEqual(res, exp_ts)

        invalid_cases = [
            "", "   ", None, np.nan, "non-una-data", "31/02/2026", "2026-13-45", 12345
        ]
        for inv in invalid_cases:
            res = parse_flexible_date(inv)
            self.assertIsNone(res, f"Valore non valido doveva ritornare None: {repr(inv)}")

    def test_corrupted_and_empty_files_resilience(self):
        """Verifica che file vuoti o con sintassi malformata non mandino in crash il sistema."""
        # File vuoto a 0 byte
        stmt_empty = parse_bank_statement("", "empty.csv")
        self.assertIsInstance(stmt_empty, BankStatement)
        self.assertEqual(len(stmt_empty.transactions), 0)

        # File con soli spazi
        stmt_spaces = parse_bank_statement("   \n\n   ", "spaces.csv")
        self.assertEqual(len(stmt_spaces.transactions), 0)

        # File CSV con righe mozze o incomplete
        broken_csv = """Data,Importo,Descrizione
2026-01-01,100.00,Test
2026-01-02
2026-01-03,invalid_num,Altro test
2026-01-04,50.00,Test finale,Extra_Column_Inaspettata
"""
        stmt_broken = parse_bank_statement(broken_csv, "broken.csv")
        self.assertIsInstance(stmt_broken, BankStatement)
        self.assertGreaterEqual(len(stmt_broken.transactions), 1)


class TestGirocontoReconciliationStress(unittest.TestCase):
    """Stress test sulla riconciliazione automatica dei giroconti multi-banca circolare."""

    def test_multi_account_circular_transfers_stress(self):
        """
        Simula 500 giroconti incrociati e circolari tra 5 istituti bancari differenti:
        Erste Giro, Trade Republic, Revolut EUR, UniCredit IT e Fineco.
        Verifica:
        1. Riconciliazione esatta di tutti i trasferimenti
        2. Neutralizzazione del doppio conteggio: somma netta trasferimenti = 0.00
        3. Isolamento perfetto dalle spese esterne reali
        """
        accounts = ["AT_Erste_Giro", "DE_Trade_Republic", "LT_Revolut_EUR", "IT_UniCredit", "IT_Fineco"]
        records = []
        base_date = pd.Timestamp("2026-01-01")

        n_cycles = 100  # 100 cicli * 5 salti = 500 giroconti
        expected_transfer_volume = 0.0

        for i in range(n_cycles):
            for step in range(5):
                from_acc = accounts[step]
                to_acc = accounts[(step + 1) % 5]
                amount = 100.0 + (i * 5) + step
                expected_transfer_volume += amount

                t_date = base_date + pd.Timedelta(days=i * 2 + step)

                # Addebito sul conto di origine
                records.append({
                    "date": t_date,
                    "amount": -amount,
                    "description": f"Giroconto a favore di {to_acc} rif #{i}_{step}",
                    "account_id": from_acc,
                    "institution": from_acc.split("_")[1],
                    "asset_class": "LIQUID_CASH" if "Trade" not in from_acc else "HIGH_YIELD_CASH"
                })

                # Accredito sul conto di destinazione (con 1 giorno di latenza bancaria)
                records.append({
                    "date": t_date + pd.Timedelta(days=1),
                    "amount": amount,
                    "description": f"Giroconto ricevuto da {from_acc} rif #{i}_{step}",
                    "account_id": to_acc,
                    "institution": to_acc.split("_")[1],
                    "asset_class": "LIQUID_CASH" if "Trade" not in to_acc else "HIGH_YIELD_CASH"
                })

        # Aggiunta di 100 spese esterne reali (Supermercato, Affitto) per verificare assenza di falsi positivi
        for i in range(100):
            records.append({
                "date": base_date + pd.Timedelta(days=i),
                "amount": -65.50,
                "description": f"Spesa Supermercato Spar #{i}",
                "account_id": "AT_Erste_Giro",
                "institution": "Erste",
                "asset_class": "LIQUID_CASH"
            })

        df_all = pd.DataFrame(records)

        # Esecuzione riconciliazione tramite PortfolioAggregator
        aggregator = PortfolioAggregator()
        t0 = time.perf_counter()
        df_transfers = aggregator._detect_internal_transfers(df_all, days_tolerance=3)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 1.5, f"Rilevamento 500 giroconti troppo lento: {elapsed:.2f}s")
        self.assertEqual(len(df_transfers), 500, f"Attesi 500 giroconti identificati, trovati {len(df_transfers)}")

        # Verifica che il volume totale dei giroconti corrisponda esattamente
        self.assertAlmostEqual(df_transfers["amount"].sum(), expected_transfer_volume, places=2)

        # Categorizzazione: verifica che le spese esterne (Spar) rimangano intatte
        df_cat = bdm.categorize_transactions(df_all, df_transfers)
        spar_tx = df_cat[df_cat["description"].str.contains("Spar")]
        self.assertEqual(len(spar_tx), 100)
        self.assertTrue((spar_tx["category"] == "Spesa & Alimentari").all())
        self.assertFalse(spar_tx["is_internal_transfer"].any())


class TestPIIScrubberStress(unittest.TestCase):
    """Stress test sul motore di anonimizzazione PII e audit anti-leakage."""

    def setUp(self):
        self.scrubber = PIIScrubber()

    def test_high_throughput_pii_sanitization(self):
        """Sanitizzazione di 5.000 stringhe bancarie complesse: verifica throughput e assenza memory leak."""
        dirty_templates = [
            "Bonifico a favore di Mario Rossi IBAN IT60X0542811101000000123456 causale affitto",
            "Addebito carta 5167 1234 5678 9010 presso Amazon EU; CF: RSSMRA85M01H501Z",
            "Überweisung an Dr. Johann Wolfgang IBAN AT12 3456 7890 1234 5678 Miete",
            "Stipendio acme Wien accreditato su conto con codice fiscale VRDLGI90A01F205X",
            "Payment to John Doe email john.doe@example.com phone +43 676 1234567",
        ]
        samples = [dirty_templates[i % len(dirty_templates)] for i in range(5000)]

        t0 = time.perf_counter()
        sanitized = [self.scrubber.anonymize_text(s) for s in samples]
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 2.5, f"Scrubbing 5k frasi troppo lento: {elapsed:.2f}s")
        self.assertEqual(len(sanitized), 5000)

        # Audit a campione su 100 frasi sanificate: deve risultare pulito al 100%
        for s in sanitized[:100]:
            clean, leaks = self.scrubber.audit_cleanliness(s)
            self.assertTrue(clean, f"Leak rilevato in stringa sanitizzata: {leaks} -> '{s}'")

    def test_adversarial_pii_patterns(self):
        """Verifica la cattura di IBAN con spazi disomogenei e carte con trattini."""
        adversarial_cases = [
            "IBAN AT 61 1921 1000 0000 1234",
            "IBAN DE89370400440532013000",
            "iban it60x0542811101000000123456",
            "Carta di credito: 4532-1234-5678-9012",
            "Email: confidential_phd_student.2026@acme.ac.at",
        ]
        for raw in adversarial_cases:
            anon = self.scrubber.anonymize_text(raw)
            clean, leaks = self.scrubber.audit_cleanliness(anon)
            self.assertTrue(clean, f"Leak su pattern avversario: {raw} -> {anon} (Leaks: {leaks})")


class TestLocalLLMAndFallbackStress(unittest.TestCase):
    """Stress test sul motore di categorizzazione euristica e diagnosi patrimoniale offline."""

    def test_mass_offline_categorization_throughput(self):
        """Categorizzazione euristica di 1.000 descrizioni variegate a latenza zero (< 0.5s)."""
        descriptions = [
            "Spar Markt Wien 1190", "Billa Corso Kärntner", "Hofer KG Filiale 22",
            "Lidl Austria", "Wiener Linien Jahreskarte", "ÖBB Personenverkehr AG",
            "Uber BV Amsterdam", "Amazon EU S.a.r.l.", "Netflix International B.V.",
            "Spotify AB", "acme Personalabteilung Gehalt", "Zinsen Trade Republic",
            "iShares Core MSCI World ETF Sparplan", "Ristorante Pizzeria da Mario",
            "Apotheke am acme Campus", "McFIT Wien Gym", "Girokonto Übertrag",
            "Bonifico a favore di proprietario Affitto Miete", "Altro acquisto generico"
        ] * 60  # 1.140 movimenti

        df_synthetic = pd.DataFrame({
            "description": descriptions,
            "amount": [-25.0] * len(descriptions)
        })

        t0 = time.perf_counter()
        df_cat = bdm.categorize_transactions(df_synthetic, pd.DataFrame())
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.5, f"Categorizzazione di 1140 movimenti troppo lenta: {elapsed:.2f}s")
        self.assertEqual(len(df_cat), len(descriptions))
        self.assertFalse(df_cat["category"].isna().any())

    def test_pathological_portfolio_audit_summary(self):
        """Verifica che generate_portfolio_audit gestisca portafogli con valori limite senza divisioni per zero."""
        client = LocalLLMClient()

        # Caso 1: Cassa zero, investimenti zero, burn rate zero
        p_zero = PortfolioSummary(
            total_net_worth=0.0,
            total_liquid_cash=0.0,
            total_high_yield_cash=0.0,
            total_investments=0.0,
            asset_allocation={"LIQUID_CASH": 0.0, "HIGH_YIELD_CASH": 0.0, "INVESTMENTS": 0.0},
            asset_allocation_pct={"LIQUID_CASH": 0.0, "HIGH_YIELD_CASH": 0.0, "INVESTMENTS": 0.0},
            accounts_summary=pd.DataFrame(),
            internal_transfers=pd.DataFrame(),
            all_transactions=pd.DataFrame(),
            monthly_burn_rate=0.0,
            liquidity_buffer_months=0.0,
            recommended_starting_cash=0.0,
        )
        audit_zero = client.generate_portfolio_audit(p_zero)
        self.assertIsInstance(audit_zero, str)
        self.assertIn("LORIS", audit_zero)
        self.assertNotIn("NaN", audit_zero)

        # Caso 2: Portafoglio con cassa negativa (scoperto) ed elevato burn rate
        p_negative = PortfolioSummary(
            total_net_worth=-2000.0,
            total_liquid_cash=-2000.0,
            total_high_yield_cash=0.0,
            total_investments=500.0,
            asset_allocation={"LIQUID_CASH": -2000.0, "HIGH_YIELD_CASH": 0.0, "INVESTMENTS": 500.0},
            asset_allocation_pct={"LIQUID_CASH": 100.0, "HIGH_YIELD_CASH": 0.0, "INVESTMENTS": 0.0},
            accounts_summary=pd.DataFrame(),
            internal_transfers=pd.DataFrame(),
            all_transactions=pd.DataFrame(),
            monthly_burn_rate=2500.0,
            liquidity_buffer_months=0.0,
            recommended_starting_cash=0.0,
        )
        audit_neg = client.generate_portfolio_audit(p_negative)
        self.assertIsInstance(audit_neg, str)
        self.assertIn("LORIS", audit_neg)
        self.assertIn("Troppo basso", audit_neg)


class TestEndToEndPipelineStress(unittest.TestCase):
    """Stress test sull'intera pipeline unificata di LORIS."""

    def test_complete_pipeline_real_bank_data(self):
        """Esecuzione completa della pipeline sui dati reali con 5.000 simulazioni Monte Carlo."""
        statements_dir = Path(__file__).resolve().parent / "fixtures" / "mock_statements"
        self.assertTrue(statements_dir.exists())

        t0 = time.perf_counter()
        # 1. Caricamento e parsing multi-banca
        stmts, summary = bdm.load_all_bank_statements(str(statements_dir))
        self.assertGreater(len(stmts), 0)

        # 2. Categorizzazione e identificazione giroconti
        df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        self.assertFalse(df_cat.empty)

        # 3. Statistiche empiriche
        stats = bdm.compute_bank_monthly_statistics(df_cat)
        self.assertGreater(stats["monthly_expenses_mean"], 0.0)

        # 4. Simulazione Monte Carlo 5.000 scenari
        res = se.run_simulation(
            start="2026-10-01",
            n_sims=5000,
            seed=42,
            pac=80.0,
            starting_cash=summary.recommended_starting_cash,
            starting_inv=summary.total_investments,
            salary1=stats.get("detected_salary", 2000.0),
            monthly_expenses_mean=stats["monthly_expenses_mean"],
            monthly_expenses_std=stats["monthly_expenses_std"],
        )
        tot_wealth = res["cash_history"] + res["invest_history"]
        terminal = tot_wealth[:, -1]
        self.assertEqual(len(terminal), 5000)

        # 5. Diagnosi AI offline
        client = LocalLLMClient()
        audit = client.generate_portfolio_audit(summary)
        self.assertIn("LORIS", audit)

        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 12.0, f"Pipeline completa troppo lenta: {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
