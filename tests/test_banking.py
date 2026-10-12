# ============================================================
# UNIT TESTS — BANKING & ANONYMOUS MULTI-BANK SYSTEM
# ============================================================
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import banking
from banking.anonymizer import PIIScrubber
from banking.parsers import (
    parse_bank_statement,
    clean_numeric_amount,
    parse_flexible_date,
    TradeRepublicParser,
    ErsteBankParser,
    ItalianBankParser,
    DigitalBankParser,
    PdfBankParser,
)
from banking.portfolio import PortfolioAggregator
from banking.local_llm import LocalLLMClient


class TestBankingAnonymizer(unittest.TestCase):
    def setUp(self):
        self.scrubber = PIIScrubber()

    def test_iban_masking(self):
        text = "Bonifico a favore di Mario Rossi IBAN AT123456789012345678 per affitto"
        anon = self.scrubber.anonymize_text(text)
        self.assertNotIn("AT123456789012345678", anon)
        self.assertIn("[IBAN_AT_01]", anon)
        clean, leaks = self.scrubber.audit_cleanliness(anon)
        self.assertTrue(clean)
        self.assertEqual(len(leaks), 0)

    def test_card_and_cf_masking(self):
        text = "Carta 5167 1234 5678 9010 spesa; Codice Fiscale RSSMRA85M01H501Z"
        anon = self.scrubber.anonymize_text(text)
        self.assertNotIn("5167 1234 5678 9010", anon)
        self.assertNotIn("RSSMRA85M01H501Z", anon)
        self.assertIn("[CARD_****9010]", anon)
        self.assertIn("[TAX_ID_01]", anon)

    def test_email_and_counterparty_masking(self):
        text = "Email supporto: test@bank.com; Beneficiario: Mario Rossi Spa"
        anon = self.scrubber.anonymize_text(text)
        self.assertNotIn("test@bank.com", anon)
        self.assertIn("[EMAIL_01]", anon)
        self.assertIn("[SOGGETTO_01]", anon)

    def test_dataframe_scrubbing(self):
        df = pd.DataFrame({
            "desc": ["Bonifico IBAN IT60X0542811101000000123456", "Pagamento carta 4000-1234-5678-9999"],
            "amount": [-150.0, -35.0]
        })
        df_anon = self.scrubber.anonymize_dataframe(df, ["desc"])
        self.assertNotIn("IT60X0542811101000000123456", df_anon["desc"].iloc[0])
        self.assertNotIn("4000-1234-5678-9999", df_anon["desc"].iloc[1])


class TestBankParsers(unittest.TestCase):
    def test_trade_republic_parser(self):
        sample = """Datum,Typ,Wert,Name
2026-09-01,Zinsen,4.37,Zinsen Trade Republic
2026-09-02,Sparplan,-80.00,iShares Core MSCI World
2026-09-15,Einzahlung,500.00,Girokonto Übertrag"""
        stmt = parse_bank_statement(sample, "Trade_Republic_Sep.csv")
        self.assertEqual(stmt.institution, "Trade Republic")
        self.assertEqual(stmt.asset_class, "HIGH_YIELD_CASH")
        self.assertEqual(len(stmt.transactions), 3)
        self.assertAlmostEqual(stmt.ending_balance, 424.37, places=2)

    def test_erste_bank_parser(self):
        sample = """Buchungsdatum;Partnername;Partner-IBAN;Betrag;Buchungstext
04.09.2026;McFit;AT123456789012345678;-29,90;Mitgliedsbeitrag
14.09.2026;acme Wien;AT987654321098765432;2850,00;Gehalt September 2026
30.09.2026;Vermieter;AT112233445566778899;-650,00;Miete musterstrasse"""
        stmt = parse_bank_statement(sample, "Erste_George_Sep.csv")
        self.assertEqual(stmt.institution, "Erste Bank")
        self.assertEqual(stmt.asset_class, "LIQUID_CASH")
        self.assertEqual(len(stmt.transactions), 3)

    def test_italian_bank_parser(self):
        sample = """Data Operazione;Descrizione;Entrate;Uscite;Saldo Contabile
05/09/2026;Donazione parenti;20,00;;2020,00
10/09/2026;Wiener Netze Gas;;36,00;1984,00"""
        stmt = parse_bank_statement(sample, "UniCredit_Conto.csv")
        self.assertEqual(stmt.institution, "Banca Italiana")
        self.assertEqual(len(stmt.transactions), 2)
        self.assertAlmostEqual(stmt.ending_balance, 1984.00, places=2)

    def test_revolut_parser(self):
        sample = """Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
CARD_PAYMENT,Current,2026-09-02 18:30:00,2026-09-02 18:30:00,Non Stop Kino Wien,-24.00,0.00,EUR,COMPLETED,342.50"""
        stmt = parse_bank_statement(sample, "Revolut_Statement.csv")
        self.assertEqual(stmt.institution, "Revolut")
        self.assertEqual(len(stmt.transactions), 1)
        self.assertAlmostEqual(stmt.ending_balance, 342.50, places=2)

    def test_clean_numeric_amounts(self):
        # Formati europei e anglosassoni
        self.assertAlmostEqual(clean_numeric_amount("-1.250,50 €"), -1250.50)
        self.assertAlmostEqual(clean_numeric_amount("1.250,50-"), -1250.50)
        self.assertAlmostEqual(clean_numeric_amount("150,00 S"), -150.00)
        self.assertAlmostEqual(clean_numeric_amount("150,00 H"), 150.00)
        self.assertAlmostEqual(clean_numeric_amount("1,250.50 DR"), -1250.50)
        self.assertAlmostEqual(clean_numeric_amount("1,250.50 CR"), 1250.50)
        self.assertAlmostEqual(clean_numeric_amount("(320.00)"), -320.00)
        self.assertAlmostEqual(clean_numeric_amount("+ 500,00"), 500.00)

    def test_parse_flexible_dates(self):
        d1 = parse_flexible_date("15/09/2026")
        self.assertIsNotNone(d1)
        self.assertEqual(d1.year, 2026)
        self.assertEqual(d1.month, 9)

        d2 = parse_flexible_date("15.09.2026")
        self.assertEqual(d2, d1)

        d3 = parse_flexible_date("15 Sep 2026")
        self.assertEqual(d3, d1)

        d4 = parse_flexible_date("15 Luglio 2026")
        self.assertIsNotNone(d4)
        self.assertEqual(d4.month, 7)

    def test_pdf_parsing_synthetic(self):
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
        from reportlab.lib.styles import getSampleStyleSheet

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Erste Bank Sparkasse - Kontoauszug", styles["Heading1"]),
            Paragraph("Schlusssaldo: 4.520,30 EUR", styles["Normal"]),
            Spacer(1, 10)
        ]
        data = [
            ["Datum", "Buchungstext", "Betrag"],
            ["15.09.2026", "BILLA Supermarkt", "-25,40 EUR"],
            ["16.09.2026", "Gehalt acme", "3.200,00 EUR"],
            ["20.09.2026", "Miete Wohnung", "-500,00 EUR"]
        ]
        story.append(Table(data))
        doc.build(story)
        pdf_bytes = buffer.getvalue()

        stmt = parse_bank_statement(pdf_bytes, "Erste_Kontoauszug.pdf")
        self.assertEqual(stmt.institution, "Erste Bank / Sparkasse")
        self.assertAlmostEqual(stmt.ending_balance, 4520.30, places=2)
        self.assertEqual(len(stmt.transactions), 3)

    def test_pdf_text_revolut(self):
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Revolut Bank Statement", styles["Heading1"]),
            Paragraph("Closing balance: 1.250,00 EUR", styles["Normal"]),
            Spacer(1, 10),
            Paragraph("15 Sep 2026 Uber Eats Vienna -22.50 EUR", styles["Normal"]),
            Paragraph("18 Sep 2026 Top Up from Bank +500.00 EUR", styles["Normal"]),
            Paragraph("25 Sep 2026 Spotify Subscription -10.99 EUR", styles["Normal"])
        ]
        doc.build(story)
        pdf_bytes = buffer.getvalue()

        stmt = parse_bank_statement(pdf_bytes, "Revolut_statement.pdf")
        self.assertEqual(stmt.institution, "Revolut")
        self.assertAlmostEqual(stmt.ending_balance, 1250.00, places=2)
        self.assertEqual(len(stmt.transactions), 3)


class TestPortfolioAggregator(unittest.TestCase):
    def test_aggregation_and_transfer_detection(self):
        tr_sample = """Datum,Typ,Wert,Name
2026-09-01,Zinsen,4.37,Zinsen Trade Republic
2026-09-15,Einzahlung,500.00,Girokonto Übertrag"""
        stmt_tr = parse_bank_statement(tr_sample, "Trade_Republic.csv")

        erste_sample = """Buchungsdatum;Partnername;Partner-IBAN;Betrag;Buchungstext
14.09.2026;acme Wien;AT987654321098765432;2850,00;Gehalt acme
15.09.2026;Trade Republic;DE890000000000000500;-500,00;Girokonto Übertrag
30.09.2026;Vermieter;AT112233445566778899;-650,00;Miete"""
        stmt_erste = parse_bank_statement(erste_sample, "Erste_Bank.csv")

        agg = PortfolioAggregator([stmt_tr, stmt_erste])
        summary = agg.aggregate()

        self.assertGreater(summary.total_net_worth, 0)
        self.assertGreater(summary.total_liquid_cash, 0)
        self.assertGreater(summary.total_high_yield_cash, 0)
        self.assertEqual(len(summary.internal_transfers), 1)
        self.assertEqual(summary.internal_transfers.iloc[0]["amount"], 500.00)


class TestLocalLLMClient(unittest.TestCase):
    def test_security_rejects_external_hosts(self):
        with self.assertRaises(ValueError):
            LocalLLMClient(endpoint_url="https://api.openai.com/v1")
        with self.assertRaises(ValueError):
            LocalLLMClient(endpoint_url="http://192.168.1.100:11434")

    def test_offline_categorization(self):
        client = LocalLLMClient()
        res_miete = client.categorize_transaction("Miete musterstrasse 13", -650.00, "Vermieter")
        self.assertEqual(res_miete["category"], "Affitto")
        self.assertGreater(res_miete["confidence"], 0.5)

        res_salary = client.categorize_transaction("Gehalt acme Wien", 2850.00, "acme")
        self.assertEqual(res_salary["category"], "Salary")

    def test_audit_generation(self):
        client = LocalLLMClient()
        summary_mock = {
            "total_net_worth": 5000.0,
            "total_liquid_cash": 2000.0,
            "total_high_yield_cash": 2500.0,
            "total_investments": 500.0,
            "monthly_burn_rate": 1800.0,
            "liquidity_buffer_months": 2.5
        }
        audit = client.generate_portfolio_audit(summary_mock)
        self.assertIn("Liquidità", audit)
        self.assertIn("Asset Allocation", audit)

    def test_detailed_models_and_recommended(self):
        from banking.local_llm import RECOMMENDED_MODELS
        client = LocalLLMClient()
        models = client.get_detailed_models()
        self.assertIsInstance(models, list)
        self.assertTrue(any("llama3.2" in m["tag"] for m in RECOMMENDED_MODELS))

    def test_install_command_generation(self):
        client = LocalLLMClient()
        cmd = client.get_install_instructions()
        self.assertIsInstance(cmd, str)
        self.assertIn("ollama", cmd.lower())


class TestInvestmentAndCategorization(unittest.TestCase):
    def test_betfair_is_gambling_not_etf(self):
        from bank_data_manager import classify_transaction
        cat_betfair = classify_transaction("Betfair card payment", -6.0)
        self.assertEqual(cat_betfair, "Svago & Scommesse")

        cat_real_etf = classify_transaction("Vanguard FTSE All-World UCITS ETF", -100.0)
        self.assertEqual(cat_real_etf, "Investimenti & PAC")

    def test_investment_portfolio_parser(self):
        from banking.parsers import parse_bank_statement
        sample_csv = """Ticker,Name,Shares,Buy_Price,Current_Price,Market_Value
VWCE,Vanguard FTSE All-World UCITS ETF,20,100.0,120.0,2400.0
SWDA,iShares Core MSCI World,10,80.0,95.0,950.0"""
        stmt = parse_bank_statement(sample_csv, "my_portfolio_etf.csv")
        self.assertEqual(stmt.asset_class, "INVESTMENTS")
        self.assertEqual(stmt.institution, "Portafoglio Titoli & ETF")
        self.assertEqual(stmt.ending_balance, 3350.0)
        self.assertEqual(len(stmt.metadata.get("holdings", [])), 2)
        self.assertEqual(stmt.metadata["holdings"][0]["ticker"], "VWCE")
        self.assertEqual(stmt.metadata["holdings"][0]["pnl"], 400.0)

    def test_financial_system_context_accounting_rules(self):
        client = LocalLLMClient()
        ctx = client.build_financial_system_context(
            {"total_net_worth": 3000.0, "total_liquid_cash": 100.0, "total_high_yield_cash": 2900.0, "total_investments": 0.0},
            cash_yield_pct=2.75
        )
        self.assertIn("SEGNO NEGATIVO (-)", ctx)
        self.assertIn("NON sono affatto errori di registrazione", ctx)
        self.assertIn("Svago & Scommesse", ctx)
        self.assertIn("2.75%", ctx)

    def test_financial_guardrail_auditing(self):
        from banking.guardrails import FinancialFactSheet, FinancialGuardrail
        sheet = FinancialFactSheet(
            net_worth=2868.20,
            liquid_cash=103.87,
            high_yield_cash=2764.33,
            investments=0.0,
            monthly_burn_rate=548.08,
            cash_buffer_months=5.2,
            cash_yield_pct=2.5,
            annual_interest_est=69.11
        )
        res_grounded = FinancialGuardrail.audit_response("Il patrimonio è € 2,868.20 con € 2,764.33 su Trade Republic.", sheet)
        self.assertTrue(res_grounded["is_grounded"])
        self.assertEqual(len(res_grounded["unverified_amounts"]), 0)

        res_hallucinated = FinancialGuardrail.audit_response("Hai € 50,000.00 su un conto segreto in Svizzera.", sheet)
        self.assertFalse(res_hallucinated["is_grounded"])
        self.assertIn(50000.0, res_hallucinated["unverified_amounts"])

    def test_financial_tool_registry(self):
        from banking.guardrails import FinancialToolRegistry
        res_interest = FinancialToolRegistry.calculate_compound_interest(principal=2764.33, annual_rate_pct=2.5, years=1)
        self.assertAlmostEqual(res_interest["total_interest_earned"], 69.11, places=1)

        res_runway = FinancialToolRegistry.calculate_runway(total_cash=2868.20, burn_rate=548.08)
        self.assertAlmostEqual(res_runway["runway_months"], 5.2, places=1)
        self.assertTrue(res_runway["is_runway_healthy"])


if __name__ == "__main__":
    unittest.main()
