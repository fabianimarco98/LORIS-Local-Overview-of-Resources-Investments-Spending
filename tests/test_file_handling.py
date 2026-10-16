import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import bank_data_manager as bdm
from banking.parsers import clean_numeric_amount, parse_bank_statement

FIX = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


class TestAmountParsing(unittest.TestCase):
    def test_unicode_minus_is_negative(self):
        self.assertEqual(clean_numeric_amount("−12,50"), -12.5)

    def test_single_separator_thousands(self):
        self.assertEqual(clean_numeric_amount("1.250"), 1250.0)
        self.assertEqual(clean_numeric_amount("1.250.000"), 1250000.0)
        self.assertEqual(clean_numeric_amount("12,345"), 12345.0)

    def test_single_separator_decimals(self):
        self.assertEqual(clean_numeric_amount("1250,50"), 1250.5)
        self.assertEqual(clean_numeric_amount("0.500"), 0.5)
        self.assertEqual(clean_numeric_amount("12.5"), 12.5)

    def test_mixed_separators_unchanged(self):
        self.assertEqual(clean_numeric_amount("1.250,50"), 1250.5)
        self.assertEqual(clean_numeric_amount("1,250.50"), 1250.5)


class TestEncodings(unittest.TestCase):
    def setUp(self):
        self.text = (FIX / "Erste_Bank_Girokonto_Sep2026.csv").read_text(encoding="utf-8")

    def test_encodings_parse_same_transactions(self):
        expected = len(parse_bank_statement(self.text.encode("utf-8"), "Erste.csv").transactions)
        self.assertGreater(expected, 0)
        for enc in ("utf-16", "utf-8-sig", "cp1252"):
            n = len(parse_bank_statement(self.text.encode(enc), "Erste.csv").transactions)
            self.assertEqual(n, expected, enc)

    def test_garbage_raises_clear_error(self):
        with self.assertRaises(ValueError):
            parse_bank_statement(bytes(range(256)) * 20, "junk.csv")


class TestFolderLoading(unittest.TestCase):
    def test_same_account_twice_is_merged_and_junk_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            shutil.copy(FIX / "Erste_Bank_Girokonto_Sep2026.csv", d / "a.csv")
            shutil.copy(FIX / "Erste_Bank_Girokonto_Sep2026.csv", d / "b_copy.csv")
            shutil.copy(FIX / "Revolut_Statement_Sep2026.csv", d / "rev.csv")
            (d / "empty.csv").write_text("")
            (d / "junk.csv").write_bytes(bytes(range(256)) * 20)
            stmts, summary = bdm.load_all_bank_statements(d)
        ids = [s.account_id for s in stmts]
        self.assertEqual(len(ids), len(set(ids)), "un solo statement per conto")
        self.assertTrue(any("saldo" in w and "stimato" in w for w in summary.load_warnings))
        self.assertTrue(any("empty.csv" in w for w in summary.load_warnings))
        self.assertTrue(any("junk.csv" in w for w in summary.load_warnings))

    def test_estimated_balance_accumulates_over_months(self):
        header = "Buchungsdatum;Partnername;Partner-IBAN;Betrag;Währung;Buchungstext\n"
        sep = header + "02.09.2026;Billa;AT120000000000000001;-100,00;EUR;Kartenzahlung\n"
        oct_ = header + "02.10.2026;Billa;AT120000000000000001;-50,00;EUR;Kartenzahlung\n"
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Erste_Sep.csv").write_text(sep)
            (d / "Erste_Oct.csv").write_text(oct_)
            stmts, summary = bdm.load_all_bank_statements(d)
        erste = [x for x in stmts if x.institution == "Erste Bank"]
        self.assertEqual(len(erste), 1)
        self.assertAlmostEqual(erste[0].ending_balance, -150.0)   # somma di entrambi i mesi, non solo dell'ultimo
        self.assertTrue(erste[0].metadata["balance_estimated"])


if __name__ == "__main__":
    unittest.main()
