# ============================================================
# BANKING MODULE — ESTRAZIONE ROBUSTA DA PDF
# ============================================================
"""
Estrae testo e tabelle da un PDF senza mai fallire in silenzio:

- file vuoto, non-PDF, cifrato con password, danneggiato o scansionato -> `PdfReadError`
  con un messaggio pensato per l'utente (finisce nei `load_warnings`);
- una pagina illeggibile non butta via le altre: viene segnalata e saltata;
- pdfplumber è il motore principale, pypdf il ripiego pagina per pagina;
- il testo è normalizzato (spazi non separabili, trattini Unicode, caratteri invisibili,
  legature) così che le regex dei parser vedano sempre gli stessi caratteri.

Tutto è locale: nessuna rete, nessun OCR esterno.
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, List

# Le librerie PDF sono molto verbose sui file imperfetti (spesso innocui): i problemi veri li segnaliamo noi
for _noisy in ("pypdf", "pdfminer", "pdfplumber"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:  # pragma: no cover - dipende dall'ambiente
    HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:  # pragma: no cover - dipende dall'ambiente
    HAS_PYPDF = False

MAX_PAGES = 400                 # oltre, il resto è ignorato con un avviso (memoria/tempo)
MIN_CHARS_TOTAL = 10            # sotto questa soglia il PDF non ha un livello di testo
MAX_PDF_BYTES = 60 * 1024 * 1024

SCANNED_MESSAGE = (
    "il PDF non contiene testo selezionabile (probabile scansione o foto): scarica l'estratto originale "
    "dalla tua banca, oppure inserisci i saldi a mano in 'Patrimonio nel tempo'"
)


class PdfReadError(ValueError):
    """PDF non leggibile. Il messaggio è mostrabile così com'è all'utente."""


@dataclass
class PdfExtraction:
    text: str = ""                                            # testo normalizzato di tutte le pagine
    page_texts: List[str] = field(default_factory=list)
    tables: List[Any] = field(default_factory=list)           # tabelle con linee (affidabili)
    text_tables: List[Any] = field(default_factory=list)      # tabelle dedotte dall'allineamento (rumorose)
    page_count: int = 0
    pages_failed: List[int] = field(default_factory=list)     # 1-based
    pages_empty: List[int] = field(default_factory=list)      # 1-based, senza testo
    encrypted: bool = False
    warnings: List[str] = field(default_factory=list)


_INVISIBLE = dict.fromkeys(
    map(ord, "­​‌‍‎‏⁠﻿‪‫‬‭‮"), None
)
_DASHES = {ord(c): "-" for c in "‐‑‒–—―−﹣－"}
_CID = re.compile(r"\(cid:\d+\)")


def normalize_pdf_text(text: str) -> str:
    """Testo canonico: NFKC (nbsp, legature, cifre a larghezza piena), trattini e invisibili uniformati."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_INVISIBLE).translate(_DASHES)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", text)
    lines = [re.sub(r"[ \t - 　]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines)


def _open_reader(data: bytes, res: PdfExtraction):
    """Apre con pypdf gestendo la cifratura. Restituisce il reader oppure None se la struttura è rotta."""
    if not HAS_PYPDF:
        return None
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            res.encrypted = True
            if not reader.decrypt(""):
                raise PdfReadError(
                    "il PDF è protetto da password: rimuovi la protezione o scarica una copia non protetta"
                )
        return reader
    except PdfReadError:
        raise
    except Exception as exc:
        if "dependency" in type(exc).__name__.lower() or "cryptography" in str(exc).lower():
            raise PdfReadError(
                "il PDF usa una cifratura che richiede il pacchetto 'cryptography' (pip install cryptography)"
            ) from exc
        res.warnings.append(f"struttura del PDF danneggiata, lettura parziale ({type(exc).__name__})")
        return None


def extract_pdf(data: bytes) -> PdfExtraction:
    """Estrae testo e tabelle. Solleva PdfReadError se il file non è utilizzabile."""
    if not data:
        raise PdfReadError("il file PDF è vuoto")
    if len(data) > MAX_PDF_BYTES:
        raise PdfReadError(f"il PDF è troppo grande ({len(data) // (1024 * 1024)} MB, massimo {MAX_PDF_BYTES // (1024 * 1024)} MB)")
    start = data.find(b"%PDF", 0, 2048)
    if start < 0:
        raise PdfReadError("il file non è un PDF valido (manca l'intestazione %PDF)")
    data = data[start:]

    res = PdfExtraction()
    reader = _open_reader(data, res)

    raw_pages: List[str] = []
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(data), password="") as pdf:
                total = len(pdf.pages)
                res.page_count = total
                if total > MAX_PAGES:
                    res.warnings.append(f"il PDF ha {total} pagine: lette solo le prime {MAX_PAGES}")
                for i, page in enumerate(pdf.pages[:MAX_PAGES]):
                    txt = ""
                    try:
                        txt = page.extract_text(layout=False) or ""
                    except Exception:
                        res.pages_failed.append(i + 1)
                    try:
                        ruled = [t for t in (page.extract_tables() or []) if t and len(t) > 1]
                        res.tables.extend(ruled)
                        if not ruled:
                            loose = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"}) or []
                            res.text_tables.extend(t for t in loose if t and len(t) > 1)
                    except Exception:
                        pass
                    finally:
                        try:
                            page.flush_cache()
                        except Exception:
                            pass
                    raw_pages.append(txt)
        except Exception as exc:
            res.warnings.append(f"lettura con pdfplumber non riuscita ({type(exc).__name__}): uso il motore alternativo")
            raw_pages, res.tables, res.text_tables = [], [], []

    # Ripiego pagina per pagina con pypdf dove pdfplumber non ha dato testo
    if reader is not None:
        try:
            n = min(len(reader.pages), MAX_PAGES)
        except Exception:
            n = 0
        res.page_count = res.page_count or n
        for i in range(n):
            if i < len(raw_pages) and raw_pages[i].strip():
                continue
            try:
                alt = reader.pages[i].extract_text() or ""
            except Exception:
                if (i + 1) not in res.pages_failed:
                    res.pages_failed.append(i + 1)
                alt = ""
            if i < len(raw_pages):
                raw_pages[i] = alt
            else:
                raw_pages.append(alt)

    if not raw_pages:
        raise PdfReadError("il PDF è danneggiato e non è stato possibile leggerlo")

    pages: List[str] = []
    for i, raw in enumerate(raw_pages):
        cleaned = normalize_pdf_text(raw)
        cid_hits = len(_CID.findall(cleaned))
        if cid_hits:
            cleaned = normalize_pdf_text(_CID.sub(" ", cleaned))
        pages.append(cleaned)
        if len(re.sub(r"\s", "", cleaned)) < 3:
            res.pages_empty.append(i + 1)

    res.page_texts = pages
    res.text = "\n".join(pages)
    res.page_count = res.page_count or len(pages)

    if len(re.sub(r"\s", "", res.text)) < MIN_CHARS_TOTAL:
        raise PdfReadError(SCANNED_MESSAGE)

    if res.pages_empty:
        listed = ", ".join(str(p) for p in res.pages_empty[:10])
        res.warnings.append(f"pagine senza testo (scansioni?) ignorate: {listed}")
    still_failed = [p for p in res.pages_failed if p not in res.pages_empty]
    if still_failed:
        res.warnings.append("pagine non leggibili ignorate: " + ", ".join(str(p) for p in still_failed[:10]))
    return res
