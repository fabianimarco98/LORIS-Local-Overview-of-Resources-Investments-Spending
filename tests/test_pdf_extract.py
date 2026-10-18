import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
for p in (str(SRC_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from banking.pdf_extract import PdfReadError, extract_pdf, normalize_pdf_text
from pdf_factory import make_pdf

BODY = ["Banca Esempio - Estratto conto", "15/09/2026 Pagamento POS Supermercato -25,40", "16/09/2026 Stipendio 3.200,00"]


class TestExtraction(unittest.TestCase):
    def test_reads_text_pages(self):
        res = extract_pdf(make_pdf([BODY]))
        self.assertIn("Stipendio", res.text)
        self.assertEqual(res.page_count, 1)
        self.assertEqual(res.warnings, [])

    def test_empty_and_non_pdf_raise_clear_errors(self):
        for data, needle in ((b"", "vuoto"), (b"hello world", "non è un PDF"), (b"<html>no</html>" * 10, "non è un PDF")):
            with self.assertRaises(PdfReadError) as ctx:
                extract_pdf(data)
            self.assertIn(needle, str(ctx.exception))

    def test_leading_garbage_before_header_is_tolerated(self):
        res = extract_pdf(b"\r\n  junk bytes\n" + make_pdf([BODY]))
        self.assertIn("Stipendio", res.text)

    def test_blank_pdf_is_reported_as_scanned(self):
        with self.assertRaises(PdfReadError) as ctx:
            extract_pdf(make_pdf([[], []]))
        self.assertIn("testo selezionabile", str(ctx.exception))
        self.assertIn("Patrimonio nel tempo", str(ctx.exception))

    def test_blank_page_among_text_pages_is_warned_not_fatal(self):
        res = extract_pdf(make_pdf([BODY, [], BODY]))
        self.assertEqual(res.pages_empty, [2])
        self.assertTrue(any("senza testo" in w for w in res.warnings))
        self.assertIn("Stipendio", res.text)

    def test_password_protected_pdf_is_rejected_with_clear_message(self):
        with self.assertRaises(PdfReadError) as ctx:
            extract_pdf(make_pdf([BODY], user_password="segreta"))
        self.assertIn("password", str(ctx.exception))

    def test_owner_password_only_pdf_is_readable(self):
        res = extract_pdf(make_pdf([BODY], user_password=""))
        self.assertTrue(res.encrypted)
        self.assertIn("Stipendio", res.text)

    def test_truncated_pdf_never_raises_unexpected_exceptions(self):
        data = make_pdf([BODY, BODY])
        for cut in (len(data) // 2, len(data) - 40, 200):
            try:
                res = extract_pdf(data[:cut])
                self.assertIsInstance(res.text, str)
            except PdfReadError:
                pass   # errore pulito e mostrabile: accettato

    def test_many_pages_is_bounded(self):
        res = extract_pdf(make_pdf([BODY] * 12))
        self.assertEqual(res.page_count, 12)
        self.assertEqual(len(res.page_texts), 12)


class TestNormalization(unittest.TestCase):
    def test_unicode_minus_nbsp_and_invisibles(self):
        raw = "Saldo finale: −1.250,50 €​\nPagamento– test­"
        out = normalize_pdf_text(raw)
        self.assertEqual(out.splitlines()[0], "Saldo finale: -1.250,50 €")
        self.assertEqual(out.splitlines()[1], "Pagamento- test")

    def test_ligatures_and_fullwidth_digits(self):
        self.assertEqual(normalize_pdf_text("ﬁrma １２,５０"), "firma 12,50")

    def test_cid_garbage_is_dropped_from_extracted_text(self):
        res = extract_pdf(make_pdf([BODY]))
        self.assertNotIn("(cid:", res.text)

    def test_collapses_whitespace_and_strips(self):
        self.assertEqual(normalize_pdf_text("  a \t  b  \r\n c "), "a b\nc")
        self.assertEqual(normalize_pdf_text(""), "")


if __name__ == "__main__":
    unittest.main()
