import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
for p in (str(SRC_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import bank_data_manager as bdm
from banking.parsers import parse_bank_statement
from banking.pdf_statement import find_iban, validate_iban
from banking.portfolio import PortfolioAggregator
from pdf_factory import SAMPLE_IBAN, SAMPLE_IBAN_SPACED, make_pdf


def statement(rows, opening="1.000,00", closing="1.174,60", period=("01/09/2026", "30/09/2026"),
              bank="UniCredit", iban=SAMPLE_IBAN_SPACED, extra=()):
    lines = [f"{bank} - Estratto conto"]
    if iban:
        lines.append(f"IBAN {iban}")
    if period:
        lines.append(f"Periodo dal {period[0]} al {period[1]}")
    if opening is not None:
        lines.append(f"Saldo iniziale {opening} EUR")
    lines += list(extra)
    lines.append("Data Descrizione Importo")
    lines += list(rows)
    if closing is not None:
        lines.append(f"Saldo finale {closing} EUR")
    return make_pdf([lines])


SEPT_ROWS = ["15/09/2026 Pagamento POS Supermercato -25,40", "16/09/2026 Stipendio Acme 200,00"]
OCT_ROWS = ["05/10/2026 Pagamento POS Benzina -50,00"]


def parse(pdf, name="estratto.pdf"):
    return parse_bank_statement(pdf, name)


class TestIban(unittest.TestCase):
    def test_validation(self):
        self.assertTrue(validate_iban(SAMPLE_IBAN))
        self.assertTrue(validate_iban(SAMPLE_IBAN_SPACED))
        self.assertFalse(validate_iban("IT60X0542811101000000123457"))    # cifra alterata
        self.assertFalse(validate_iban("IT60X05428111010000001234"))      # lunghezza sbagliata per l'Italia
        self.assertFalse(validate_iban("not an iban"))

    def test_find_iban_only_valid_ones(self):
        self.assertEqual(find_iban(f"Intestazione\nIBAN {SAMPLE_IBAN_SPACED}\nresto"), SAMPLE_IBAN)
        self.assertIsNone(find_iban("Codice AB12 3456 7890 1234 5678 9012 non è un IBAN"))


class TestBalancesAndReconciliation(unittest.TestCase):
    def test_clean_statement_reconciles_without_warnings(self):
        s = parse(statement(SEPT_ROWS))
        self.assertEqual(len(s.transactions), 2)
        self.assertAlmostEqual(s.starting_balance, 1000.0)
        self.assertAlmostEqual(s.ending_balance, 1174.60)
        self.assertTrue(s.metadata["reconciled"])
        self.assertEqual(s.metadata["closing_source"], "label")
        self.assertFalse(s.metadata["balance_estimated"])
        self.assertEqual(s.start_date, __import__("pandas").Timestamp("2026-09-01"))
        self.assertEqual(s.end_date, __import__("pandas").Timestamp("2026-09-30"))
        self.assertEqual([w for w in s.metadata["warnings"] if "non quadrano" in w], [])

    def test_mismatch_is_reported_with_the_difference(self):
        s = parse(statement(SEPT_ROWS, closing="1.200,00"))
        self.assertFalse(s.metadata["reconciled"])
        self.assertAlmostEqual(s.metadata["reconciliation_diff"], 25.40)
        self.assertTrue(any("non quadrano" in w and "+25,40" in w for w in s.metadata["warnings"]))

    def test_opening_balance_is_never_used_as_closing(self):
        s = parse(statement(SEPT_ROWS, closing=None))
        self.assertAlmostEqual(s.ending_balance, 1174.60)       # iniziale 1000 + movimenti, non 1000
        self.assertEqual(s.metadata["closing_source"], "derived")
        self.assertFalse(s.metadata["balance_estimated"])

    def test_no_balances_at_all_is_flagged_as_estimated(self):
        s = parse(statement(SEPT_ROWS, opening=None, closing=None))
        self.assertTrue(s.metadata["balance_estimated"])
        self.assertAlmostEqual(s.ending_balance, 174.60)

    def test_saldo_al_dates_pick_opening_and_closing(self):
        pdf = make_pdf([[
            "Intesa Sanpaolo", f"IBAN {SAMPLE_IBAN}", "Saldo al 31/08/2026 1.000,00", "Saldo al 30/09/2026 1.174,60",
            *SEPT_ROWS]])
        s = parse(pdf)
        self.assertAlmostEqual(s.starting_balance, 1000.0)
        self.assertAlmostEqual(s.ending_balance, 1174.60)
        self.assertTrue(s.metadata["reconciled"])


class TestRowsAndSigns(unittest.TestCase):
    def test_identical_transactions_are_all_kept(self):
        rows = ["15/09/2026 Pagamento POS Bar Roma -1,20", "15/09/2026 Pagamento POS Bar Roma -1,20"]
        s = parse(statement(rows, opening="100,00", closing="97,60"))
        self.assertEqual(len(s.transactions), 2)
        self.assertAlmostEqual(s.transactions["amount"].sum(), -2.40)
        self.assertTrue(s.metadata["reconciled"])

    def test_amounts_without_thousands_separator(self):
        s = parse(statement(["01/09/2026 Bonifico affitto -1250,50"], opening="2.000,00", closing="749,50"))
        self.assertAlmostEqual(s.transactions["amount"].iloc[0], -1250.50)
        self.assertTrue(s.metadata["reconciled"])

    def test_balance_column_fixes_unsigned_amounts(self):
        rows = ["15/09/2026 Pagamento POS Supermercato 25,40 974,60", "16/09/2026 Stipendio Acme 3.200,00 4.174,60"]
        s = parse(statement(rows, closing="4.174,60"))
        self.assertEqual(list(s.transactions["amount"]), [-25.40, 3200.00])
        self.assertTrue(s.metadata["reconciled"])

    def test_wrong_keyword_sign_is_overridden_by_balance_delta(self):
        # "Rimborso" sembra un accredito ma il saldo scende: vince la matematica
        rows = ["15/09/2026 Rimborso quota palestra 40,00 960,00", "16/09/2026 Stipendio Acme 200,00 1.160,00"]
        s = parse(statement(rows, closing="1.160,00"))
        self.assertEqual(list(s.transactions["amount"]), [-40.00, 200.00])
        self.assertTrue(any("segni corretti" in w for w in s.metadata["warnings"]))

    def test_newest_first_statement_is_oriented_and_signed_correctly(self):
        rows = ["16/09/2026 Stipendio Acme 3.200,00 4.174,60", "15/09/2026 Pagamento POS Supermercato 25,40 974,60"]
        s = parse(statement(rows, opening=None, closing=None))
        self.assertEqual(list(s.transactions["amount"]), [-25.40, 3200.00])
        self.assertAlmostEqual(s.ending_balance, 4174.60)
        self.assertEqual(s.metadata["closing_source"], "running")
        self.assertFalse(s.metadata["balance_estimated"])
        self.assertAlmostEqual(s.starting_balance, 1000.0)

    def test_second_number_in_description_is_not_taken_for_balance(self):
        rows = ["15/09/2026 Rata 3,50 -25,40", "16/09/2026 Stipendio Acme 200,00", "17/09/2026 Pagamento POS Bar -1,20"]
        s = parse(statement(rows, opening="1.000,00", closing="1.173,40"))
        self.assertEqual(list(s.transactions["amount"]), [-25.40, 200.00, -1.20])
        self.assertIn("Rata 3,50", s.transactions["description"].iloc[0])

    def test_wrapped_description_lines_are_joined(self):
        rows = ["15/09/2026 Pagamento POS Supermercato -25,40", "Esselunga Milano Via Roma", "16/09/2026 Stipendio Acme 200,00"]
        s = parse(statement(rows))
        self.assertIn("Esselunga Milano", s.transactions["description"].iloc[0])
        self.assertEqual(len(s.transactions), 2)

    def test_dates_without_year_use_the_statement_period(self):
        rows = ["15.09. Pagamento POS Supermercato -25,40", "16.09. Stipendio Acme 200,00"]
        s = parse(statement(rows))
        self.assertEqual(str(s.transactions["date"].iloc[0].date()), "2026-09-15")

    def test_yearless_dates_across_new_year(self):
        rows = ["28.12. Pagamento POS Negozio -10,00", "05.01. Stipendio Acme 100,00"]
        s = parse(statement(rows, opening="500,00", closing="590,00", period=("01/12/2026", "31/01/2027")))
        self.assertEqual([str(d.date()) for d in s.transactions["date"]], ["2026-12-28", "2027-01-05"])

    def test_us_style_dates_are_detected_from_evidence(self):
        pdf = make_pdf([["Revolut Statement", "09/25/2026 Coffee Shop -3.50 EUR", "09/26/2026 Lunch -12.00 EUR",
                         "Closing balance: 84.50 EUR"]])
        s = parse(pdf, "rev.pdf")
        self.assertEqual([str(d.date()) for d in s.transactions["date"]], ["2026-09-25", "2026-09-26"])

    def test_foreign_currency_is_labelled_not_silently_euro(self):
        pdf = make_pdf([["Revolut Statement", "15 Sep 2026 Uber Trip -22.50 USD", "16 Sep 2026 Coffee -4.00 USD",
                         "Closing balance: 1,250.00 USD"]])
        s = parse(pdf, "rev_usd.pdf")
        self.assertEqual(s.currency, "USD")
        self.assertTrue(any("USD" in w and "non sono convertiti" in w for w in s.metadata["warnings"]))

    def test_balance_lines_are_not_transactions(self):
        rows = ["01/09/2026 Saldo iniziale 1.000,00", "15/09/2026 Pagamento POS Bar -25,40", "30/09/2026 Saldo finale 974,60"]
        s = parse(statement(rows, opening=None, closing=None))
        self.assertEqual(len(s.transactions), 1)


class TestSameDayOrdering(unittest.TestCase):
    def _row(self, day, amount, balance):
        import pandas as pd
        return {"date": pd.Timestamp(day), "amount": amount, "balance_after": balance}

    def test_rows_of_a_day_follow_the_balance_chain(self):
        from banking.pdf_statement import order_rows_within_days
        rows = [self._row("2026-09-01", -10.0, 90.0),
                self._row("2026-09-02", 5.0, 75.0),       # elencato prima del suo antecedente
                self._row("2026-09-02", -20.0, 70.0),
                self._row("2026-09-02", -5.0, 70.0)]
        out = order_rows_within_days(rows)
        # 90 -> -20 -> 70 -> +5 -> 75 -> -5 -> 70
        self.assertEqual([(r["amount"], r["balance_after"]) for r in out],
                         [(-10.0, 90.0), (-20.0, 70.0), (5.0, 75.0), (-5.0, 70.0)])
        prev = None
        for r in out:
            if prev is not None:
                self.assertAlmostEqual(prev + r["amount"], r["balance_after"])
            prev = r["balance_after"]

    def test_rows_without_balances_keep_input_order_per_day(self):
        import pandas as pd
        from banking.pdf_statement import order_rows_within_days
        rows = [{"date": pd.Timestamp("2026-09-02"), "amount": 1.0, "description": "b"},
                {"date": pd.Timestamp("2026-09-01"), "amount": 2.0, "description": "a"},
                {"date": pd.Timestamp("2026-09-02"), "amount": 3.0, "description": "c"}]
        self.assertEqual([r["description"] for r in order_rows_within_days(rows)], ["a", "b", "c"])


class TestSectionedStatements(unittest.TestCase):
    """Estratti trimestrali a sezioni: più coppie iniziale/finale e totali dichiarati ma poche righe elencate."""

    LINES = [
        "Banca Widiba - Estratto conto", f"IBAN {SAMPLE_IBAN_SPACED}", "Periodo dal 01/04/2026 al 30/06/2026",
        "Saldo iniziale al 31/03/2026 1.000,00", "Totale entrate 500,00", "Totale uscite 200,00",
        "Saldo finale al 30/06/2026 1.300,00",
        "15/05/2026 ADDEBITO commissioni -20,00",
        "Sintesi interessi", "Saldo iniziale al 31/03/2026 50,00", "Saldo finale al 30/06/2026 60,00",
    ]

    def test_closing_is_the_one_consistent_with_declared_totals(self):
        s = parse(make_pdf([self.LINES]), "trimestre.pdf")
        self.assertAlmostEqual(s.ending_balance, 1300.0)          # non 60 (sezione interessi, ultima nel testo)
        self.assertAlmostEqual(s.starting_balance, 1000.0)
        self.assertTrue(any("più saldi finali" in w for w in s.metadata["warnings"]))

    def test_incomplete_movement_list_is_named_as_such(self):
        s = parse(make_pdf([self.LINES]), "trimestre.pdf")
        self.assertTrue(s.metadata["movements_incomplete"])
        self.assertFalse(s.metadata["reconciled"])
        w = [x for x in s.metadata["warnings"] if "elenco incompleto" in x]
        self.assertTrue(w)
        self.assertIn("entrate 500,00", w[0])
        self.assertIn("uscite 200,00", w[0])

    def test_most_recent_dated_closing_wins_without_totals(self):
        lines = ["Banca Widiba - Estratto conto", f"IBAN {SAMPLE_IBAN_SPACED}",
                 "Saldo finale al 31/03/2026 900,00", "Saldo finale al 30/06/2026 1.100,00",
                 "15/05/2026 ADDEBITO commissioni -20,00"]
        s = parse(make_pdf([lines]), "due_saldi.pdf")
        self.assertAlmostEqual(s.ending_balance, 1100.0)


class TestInstitutionAndIdentity(unittest.TestCase):
    def test_substrings_do_not_misidentify_the_bank(self):
        s = parse(statement(SEPT_ROWS, bank="Posteriore Finanziaria", extra=["Intestato a George Smith"]))
        self.assertEqual(s.institution, "Estratto Conto PDF")

    def test_known_bank_is_detected_from_header(self):
        self.assertEqual(parse(statement(SEPT_ROWS, bank="Fineco Bank")).institution, "FinecoBank")

    def test_account_id_comes_from_iban_not_from_file_name(self):
        a = parse(statement(SEPT_ROWS), "gennaio.pdf")
        b = parse(statement(OCT_ROWS, opening="1.174,60", closing="1.124,60", period=("01/10/2026", "31/10/2026")),
                  "febbraio.pdf")
        self.assertEqual(a.account_id, b.account_id)
        self.assertTrue(a.account_id.endswith("3456"))
        self.assertNotIn("gennaio", a.account_id)

    def test_other_iban_means_other_account(self):
        other = "DE89 3704 0044 0532 0130 00"
        a = parse(statement(SEPT_ROWS))
        b = parse(statement(SEPT_ROWS, iban=other))
        self.assertNotEqual(a.account_id, b.account_id)

    def test_no_iban_known_bank_is_one_account_with_warning(self):
        a = parse(statement(SEPT_ROWS, iban=None), "a.pdf")
        b = parse(statement(OCT_ROWS, iban=None, opening="1.174,60", closing="1.124,60",
                            period=("01/10/2026", "31/10/2026")), "b.pdf")
        self.assertEqual(a.account_id, b.account_id)
        self.assertTrue(any("nessun IBAN" in w for w in a.metadata["warnings"]))

    def test_unknown_bank_without_iban_stays_separate_per_file(self):
        a = parse(statement(SEPT_ROWS, iban=None, bank="Banca Sconosciuta"), "uno.pdf")
        b = parse(statement(SEPT_ROWS, iban=None, bank="Banca Sconosciuta"), "due.pdf")
        self.assertNotEqual(a.account_id, b.account_id)


class TestUnreadablePdfs(unittest.TestCase):
    def test_scanned_pdf_has_actionable_message(self):
        with self.assertRaises(ValueError) as ctx:
            parse(make_pdf([[], []]), "scansione.pdf")
        self.assertIn("testo selezionabile", str(ctx.exception))
        self.assertNotIn("Formato non riconosciuto", str(ctx.exception))

    def test_password_protected_pdf_message(self):
        with self.assertRaises(ValueError) as ctx:
            parse(make_pdf([["x" * 50]], user_password="segreta"), "protetto.pdf")
        self.assertIn("password", str(ctx.exception))

    def test_unrecognised_layout_points_to_manual_entry(self):
        with self.assertRaises(ValueError) as ctx:
            parse(make_pdf([["Lorem ipsum dolor sit amet consectetur", "nessun movimento qui dentro"]]), "libro.pdf")
        self.assertIn("Patrimonio nel tempo", str(ctx.exception))

    def test_dataframe_has_no_private_helper_columns(self):
        s = parse(statement(["15/09/2026 Pagamento POS Supermercato 25,40 974,60", "16/09/2026 Stipendio 200,00 1.174,60"]))
        self.assertFalse([c for c in s.transactions.columns if c.startswith("_")])


class TestConsolidation(unittest.TestCase):
    def _sept_oct(self, oct_opening="1.174,60"):
        sept = parse(statement(SEPT_ROWS), "sett.pdf")
        octo = parse(statement(OCT_ROWS, opening=oct_opening, closing="1.124,60", period=("01/10/2026", "31/10/2026")),
                     "ott.pdf")
        return sept, octo

    def test_two_months_of_one_account_are_not_summed(self):
        sept, octo = self._sept_oct()
        agg = PortfolioAggregator([sept, octo])
        summary = agg.aggregate()
        self.assertEqual(len(summary.accounts_summary), 1)
        self.assertAlmostEqual(summary.total_net_worth, 1124.60)
        self.assertEqual(len(summary.all_transactions), 3)
        self.assertEqual([w for w in agg.warnings if "non coincide" in w or "nessun dato" in w], [])

    def test_continuity_mismatch_between_months_is_reported(self):
        sept, octo = self._sept_oct(oct_opening="1.100,00")
        agg = PortfolioAggregator([sept, octo])
        agg.aggregate()
        self.assertTrue(any("non coincide con il saldo iniziale" in w and "+74,60" in w for w in agg.warnings), agg.warnings)

    def test_missing_month_is_reported(self):
        sept = parse(statement(SEPT_ROWS), "sett.pdf")
        dec = parse(statement(OCT_ROWS, opening="1.174,60", closing="1.124,60", period=("01/12/2026", "31/12/2026")),
                    "dic.pdf")
        agg = PortfolioAggregator([sept, dec])
        agg.aggregate()
        self.assertTrue(any("nessun dato tra il 30/09/2026 e il 01/12/2026" in w for w in agg.warnings))

    def test_overlapping_statements_do_not_double_count(self):
        a = parse(statement(SEPT_ROWS), "a.pdf")
        b = parse(statement(SEPT_ROWS + OCT_ROWS, opening="1.000,00", closing="1.124,60",
                            period=("15/09/2026", "31/10/2026")), "b.pdf")
        agg = PortfolioAggregator([a, b])
        summary = agg.aggregate()
        self.assertEqual(len(summary.all_transactions), 3)

    def test_overlap_keeps_legit_identical_rows(self):
        twin = ["15/09/2026 Pagamento POS Bar Roma -1,20", "15/09/2026 Pagamento POS Bar Roma -1,20"]
        a = parse(statement(twin, opening="100,00", closing="97,60"), "a.pdf")
        b = parse(statement(twin + OCT_ROWS, opening="100,00", closing="47,60", period=("15/09/2026", "31/10/2026")),
                  "b.pdf")
        summary = PortfolioAggregator([a, b]).aggregate()
        self.assertEqual(len(summary.all_transactions), 3)           # 2 caffè + benzina, non 1 + benzina

    def test_stale_account_is_flagged(self):
        old = parse(statement(
            ["15/03/2024 Pagamento POS Supermercato -25,40", "16/03/2024 Stipendio Acme 200,00"],
            period=("01/03/2024", "31/03/2024")), "vecchio.pdf")
        agg = PortfolioAggregator([old])
        agg.aggregate()
        self.assertTrue(any("potrebbe non essere aggiornato" in w for w in agg.warnings))

    def test_recent_account_is_not_flagged_as_stale(self):
        import pandas as pd
        today = pd.Timestamp.today().normalize()
        d = (today - pd.Timedelta(days=3)).strftime("%d/%m/%Y")
        s = parse(statement([f"{d} Pagamento POS Bar -1,20"], opening="10,00", closing="8,80",
                            period=((today - pd.Timedelta(days=20)).strftime("%d/%m/%Y"), d)))
        agg = PortfolioAggregator([s])
        agg.aggregate()
        self.assertEqual([w for w in agg.warnings if "aggiornato" in w], [])


def table_pdf(header, rows, preamble):
    """PDF con una vera tabella a griglia (pdfplumber la riconosce dalle linee)."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(t, styles["Normal"]) for t in preamble] + [Spacer(1, 12)]
    table = Table([header] + rows)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    story.append(table)
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


PREAMBLE = ["UniCredit - Estratto conto", f"IBAN {SAMPLE_IBAN_SPACED}", "Saldo iniziale 1.000,00 EUR",
            "Saldo finale 1.174,60 EUR"]


class TestRuledTables(unittest.TestCase):
    def test_in_out_columns(self):
        pdf = table_pdf(["Data", "Descrizione", "Entrate", "Uscite", "Saldo"],
                        [["15/09/2026", "Pagamento POS Supermercato", "", "25,40", "974,60"],
                         ["16/09/2026", "Stipendio Acme", "200,00", "", "1.174,60"]], PREAMBLE)
        s = parse(pdf)
        self.assertEqual(s.metadata["row_source"], "table")
        self.assertEqual(list(s.transactions["amount"]), [-25.40, 200.00])
        self.assertTrue(s.metadata["reconciled"])
        self.assertEqual(s.account_id, parse(statement(SEPT_ROWS)).account_id)

    def test_dare_avere_columns_follow_the_accounting_meaning(self):
        pdf = table_pdf(["Data", "Causale", "Dare", "Avere"],
                        [["15/09/2026", "Pagamento POS Supermercato", "25,40", ""],
                         ["16/09/2026", "Stipendio Acme", "", "200,00"]], PREAMBLE)
        s = parse(pdf)
        self.assertEqual(list(s.transactions["amount"]), [-25.40, 200.00])
        self.assertTrue(s.metadata["reconciled"])

    def test_identical_table_rows_are_kept(self):
        pdf = table_pdf(["Data", "Descrizione", "Importo"],
                        [["15/09/2026", "Pagamento POS Bar Roma", "-1,20"], ["15/09/2026", "Pagamento POS Bar Roma", "-1,20"]],
                        ["UniCredit - Estratto conto", f"IBAN {SAMPLE_IBAN_SPACED}", "Saldo iniziale 100,00 EUR",
                         "Saldo finale 97,60 EUR"])
        s = parse(pdf)
        self.assertEqual(len(s.transactions), 2)
        self.assertTrue(s.metadata["reconciled"])

    def test_date_cells_are_never_read_as_amounts(self):
        pdf = table_pdf(["Data operazione", "Data valuta", "Descrizione", "Importo"],
                        [["15/09/2026", "16/09/2026", "Pagamento POS Supermercato", "-25,40"]],
                        ["UniCredit - Estratto conto", f"IBAN {SAMPLE_IBAN_SPACED}"])
        s = parse(pdf)
        self.assertEqual(list(s.transactions["amount"]), [-25.40])


class TestWarningPropagation(unittest.TestCase):
    def test_pdf_warnings_reach_load_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bad.pdf").write_bytes(statement(SEPT_ROWS, closing="1.500,00"))
            (d / "scan.pdf").write_bytes(make_pdf([[]]))
            (d / "ok.pdf").write_bytes(statement(OCT_ROWS, iban="DE89 3704 0044 0532 0130 00", opening="1.174,60",
                                                 closing="1.124,60", period=("01/10/2026", "31/10/2026")))
            _, summary = bdm.load_all_bank_statements(str(d))
        w = summary.load_warnings
        self.assertTrue(any(x.startswith("bad.pdf:") and "non quadrano" in x for x in w), w)
        self.assertTrue(any(x.startswith("scan.pdf:") and "testo selezionabile" in x for x in w), w)
        self.assertFalse(any(x.startswith("ok.pdf:") and "non quadrano" in x for x in w), w)

    def test_agent_summary_carries_data_warnings(self):
        import loris_service as svc
        from agents import PortfolioContext, build_portfolio_registry
        fixtures = TESTS_DIR / "fixtures" / "mock_statements"
        data = svc.load_portfolio(fixtures, apply_overrides=False)
        data.summary.load_warnings = ["estratto.pdf: i movimenti non quadrano con i saldi dichiarati (scarto +25,40 EUR)"]
        reg = build_portfolio_registry(PortfolioContext(data.summary, data.df_tx, data.stats, 2.5))
        res = reg.execute("get_portfolio_summary", {})
        self.assertTrue(res.ok, res.error)
        self.assertTrue(any("non quadrano" in w for w in res.data["data_quality_warnings"]))

    def test_cli_prints_warnings_even_without_accounts(self):
        import contextlib
        import io
        import cli

        class S:
            load_warnings = ["scan.pdf: il PDF non contiene testo selezionabile"]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_data_warnings(S(), "it")
        self.assertIn("Avvisi sui dati (1)", out.getvalue())
        self.assertIn("scan.pdf", out.getvalue())

    def test_orphaned_manual_balance_is_reported(self):
        sept = parse(statement(SEPT_ROWS), "sett.pdf")
        agg = PortfolioAggregator([sept])
        summary = agg.aggregate()
        _, new_summary = bdm.apply_user_overrides(
            agg.effective_statements, summary, {"balance_overrides": {"PDF_vecchio_nome_file": 5.0}})
        self.assertTrue(any("non esiste più" in w and "PDF_vecchio_nome_file" in w for w in new_summary.load_warnings))


if __name__ == "__main__":
    unittest.main()
