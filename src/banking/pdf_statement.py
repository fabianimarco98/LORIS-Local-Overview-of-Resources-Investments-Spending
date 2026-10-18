# ============================================================
# BANKING MODULE — INTERPRETAZIONE DEL TESTO DI UN ESTRATTO CONTO PDF
# ============================================================
"""
Dal testo/tabelle estratti (vedi pdf_extract) a: identità del conto, periodo, valuta, saldi e movimenti,
con controlli di coerenza che trasformano gli errori silenziosi in avvisi:

- l'IBAN (validato col checksum mod-97) identifica il conto, così più PDF dello stesso conto si
  consolidano invece di sommarsi come conti diversi;
- saldo iniziale e finale sono riconosciuti separatamente (mai l'uno al posto dell'altro);
- se le righe hanno la colonna saldo, i segni degli importi si ricavano dalla variazione del saldo
  (più affidabile delle parole chiave) e la catena dei saldi segnala righe perse o lette male;
- iniziale + movimenti deve quadrare con il finale; altrimenti l'avviso riporta lo scarto in euro;
- nessuna riga viene scartata come "duplicato": due caffè identici nello stesso giorno restano due.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .parsers import clean_numeric_amount, parse_flexible_date

BALANCE_TOLERANCE = 0.011


def fmt_it(value: float) -> str:
    """1.234,50 (formato italiano) per i messaggi mostrati all'utente."""
    return f"{value:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_signed_it(value: float) -> str:
    """+1.234,50 (formato italiano, sempre col segno) per i messaggi mostrati all'utente."""
    return f"{value:+,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


# ---------------- pattern di base ----------------

_NUM = r"\d+(?:[.,'’]\d{3})*[.,]\d{2}"
_CUR = r"(?:€|EUR|USD|GBP|CHF|\$|£)"
# Importo con segno prima/dopo, valuta opzionale, marcatori contabili (S/H/DR/CR). Non deve far parte di una data.
AMT = rf"(?<![\d.,/])[+-]?\s?{_CUR}?\s?{_NUM}(?![\d.,/])(?:\s?(?:[-+]|\b(?:[SH]|DR|CR)\b))?"

DATE_NUM = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
DATE_ISO = r"\d{4}-\d{1,2}-\d{1,2}"
DATE_TXT = r"\d{1,2}\.?\s+[A-Za-zäöüÄÖÜéèàùÉÈ]{3,9}\.?,?\s+\d{2,4}"
DATE_SHORT = r"\d{1,2}[./]\d{1,2}\.?(?![\d.,/])"
DATE_ANY = rf"(?:{DATE_ISO}|{DATE_NUM}|{DATE_TXT})"

_STOP_PREFIX = re.compile(
    r"^(?:saldo|balance|kontostand|totale|total|summe|riporto|a\s+riportare|opening|closing|"
    r"giacenza|solde|report|übertrag)\b", re.IGNORECASE)
_BOILERPLATE = re.compile(
    r"pagina|page\s+\d|seite|iban|bic\b|swift|estratto\s+conto|kontoauszug|statement|data\s+valuta|"
    r"descrizione|importo|entrate|uscite|p\.?\s?iva|www\.|@|riporto|saldo|totale|total\b|"
    r"intestat|filiale|agenzia|\bcap\b|codice\s+fiscale",
    re.IGNORECASE)
_UNSIGNED_DEBIT_WORDS = re.compile(
    r"\b(addebito|rid|spesa|pagamento|prelievo|giroconto\s+verso|commissione|commission|uscita)\b", re.IGNORECASE)
_CREDIT_WORDS = re.compile(r"\b(stipendio|accredito|salary|rimborso|entrata|bonifico\s+a\s+vostro\s+favore)\b", re.IGNORECASE)
_INTERNAL_WORDS = ("giroconto", "trasferimento interno", "internal transfer", "own account", "trade republic",
                   "revolut", "ricarica", "top up")

INSTITUTIONS: List[Tuple[str, str]] = [
    ("Trade Republic", r"trade[\s_-]?republic|traderepublic"),
    ("UniCredit", r"\bunicredit\b"),
    ("Intesa Sanpaolo", r"\bintesa\b|\bsan\s?paolo\b|\bsanpaolo\b"),
    ("FinecoBank", r"\bfineco(?:bank)?\b"),
    ("Erste Bank / Sparkasse", r"\berste\s+bank\b|\bsparkasse\b|\bgeorge\s+(?:banking|business)\b"),
    ("Revolut", r"\brevolut\b"),
    ("N26", r"\bn26\b"),
    ("Poste Italiane", r"\bposte\s+italiane\b|\bbancoposta\b|\bposte\b"),
    ("Banca Mediolanum", r"\bmediolanum\b"),
    ("Banca Widiba", r"\bwidiba\b"),
    ("Deutsche Bank", r"\bdeutsche\s+bank\b"),
    ("ING", r"\bing[\s-]?(?:direct|bank|diba)\b"),
]
GENERIC_INSTITUTION = "Estratto Conto PDF"

IBAN_LENGTHS = {
    "IT": 27, "DE": 22, "AT": 20, "FR": 27, "ES": 24, "NL": 18, "BE": 16, "CH": 21, "LI": 21, "GB": 22,
    "LU": 20, "PT": 25, "IE": 22, "GR": 27, "FI": 18, "SE": 24, "DK": 18, "NO": 15, "PL": 28, "CZ": 24,
    "SK": 24, "SI": 19, "HR": 21, "HU": 28, "RO": 24, "BG": 22, "EE": 20, "LV": 21, "LT": 20, "MT": 31,
    "CY": 28, "SM": 27, "MC": 27,
}


# ---------------- risultato ----------------

@dataclass
class PdfAnalysis:
    institution: str = GENERIC_INSTITUTION
    currency: str = "EUR"
    iban: Optional[str] = None
    account_tail: Optional[str] = None
    period: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None
    rows: List[Dict[str, Any]] = field(default_factory=list)
    opening: Optional[float] = None
    opening_explicit: bool = False
    closing: Optional[float] = None
    closing_source: str = "none"          # label | available | running | derived | estimated | none
    balance_estimated: bool = False
    reconciled: Optional[bool] = None
    reconciliation_diff: Optional[float] = None
    movements_incomplete: bool = False    # i totali dichiarati quadrano coi saldi ma le righe elencate no
    row_source: str = "none"              # table | text | table-loose | none
    date_order: str = "dmy"
    warnings: List[str] = field(default_factory=list)


# ---------------- identità del conto ----------------

def validate_iban(candidate: str) -> bool:
    s = re.sub(r"\s", "", candidate).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    expected = IBAN_LENGTHS.get(s[:2])
    if expected is not None and len(s) != expected:
        return False
    digits = "".join(str(int(ch, 36)) for ch in s[4:] + s[:4])
    return int(digits) % 97 == 1


def find_iban(text: str, header_chars: int = 3500) -> Optional[str]:
    """Primo IBAN valido nell'intestazione (gli IBAN delle controparti stanno nelle righe, più sotto)."""
    for m in re.finditer(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{2,4}){3,8}\b", text[:header_chars]):
        compact = re.sub(r"\s", "", m.group(0))
        length = IBAN_LENGTHS.get(compact[:2])
        cand = compact[:length] if length and len(compact) >= length else compact
        if validate_iban(cand):
            return cand
    return None


def find_account_tail(text: str) -> Optional[str]:
    m = re.search(r"(?:conto\s*(?:corrente)?\s*(?:n\.?|n°|numero)|konto[-\s]?(?:nr\.?|nummer)|account\s*(?:no\.?|number))"
                  r"\s*[:.]?\s*([0-9][0-9 ./-]{5,24})", text[:3500], re.IGNORECASE)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return digits[-4:] if len(digits) >= 6 else None


def detect_institution(header_text: str, filename: str = "") -> str:
    fn = filename.lower()
    if re.search(r"trade[\s_-]?republic|traderepublic", fn) or ("trade" in fn and "account" in fn):
        return "Trade Republic"
    low = header_text.lower()
    for name, pattern in INSTITUTIONS:
        if re.search(pattern, low):
            return name
    return GENERIC_INSTITUTION


def detect_currency(text: str) -> str:
    counts = Counter({
        "EUR": len(re.findall(r"€|\bEUR\b", text)),
        "USD": len(re.findall(r"\$|\bUSD\b", text)),
        "GBP": len(re.findall(r"£|\bGBP\b", text)),
        "CHF": len(re.findall(r"\bCHF\b", text)),
    })
    cur, n = counts.most_common(1)[0]
    return cur if n >= 2 else "EUR"


# ---------------- date ----------------

def detect_date_order(text: str) -> str:
    """'dmy' di default; 'mdy' solo se i dati con la barra lo dimostrano (secondo numero > 12, mai il primo)."""
    first_gt12 = second_gt12 = False
    for a, b in re.findall(r"\b(\d{1,2})/(\d{1,2})/\d{2,4}\b", text):
        first_gt12 |= int(a) > 12
        second_gt12 |= int(b) > 12
    return "mdy" if second_gt12 and not first_gt12 else "dmy"


def parse_pdf_date(raw: str, order: str = "dmy") -> Optional[pd.Timestamp]:
    raw = raw.strip().rstrip(".,")
    if order == "mdy":
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
        if m:
            raw = f"{m.group(2)}/{m.group(1)}/{m.group(3)}"
    d = parse_flexible_date(raw)
    if d is None or not (2000 <= d.year <= 2100):
        return None
    return d


def first_date_in(cell: Any, order: str = "dmy") -> Optional[pd.Timestamp]:
    """Prima data valida contenuta in una cella (le celle possono contenere data operazione e data valuta)."""
    m = re.search(DATE_ANY, str(cell or ""))
    return parse_pdf_date(m.group(0), order) if m else None


def _parse_short_date(raw: str, year_hint: int, period_end: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})\.?", raw.strip())
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    year = year_hint
    # Estratto a cavallo d'anno: un mese molto successivo a quello di fine periodo appartiene all'anno prima
    if period_end is not None and month - period_end.month >= 6:
        year -= 1
    try:
        return pd.Timestamp(year=year, month=month, day=day)
    except ValueError:
        return None


def find_period(text: str) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
    pat = re.compile(
        rf"(?P<a>{DATE_NUM}|{DATE_TXT})\s*(?:al|a|to|bis|-)\s*(?P<b>{DATE_NUM}|{DATE_TXT})", re.IGNORECASE)
    for m in pat.finditer(text[:6000]):
        a, b = parse_pdf_date(m.group("a")), parse_pdf_date(m.group("b"))
        if a is not None and b is not None and a <= b and (b - a).days <= 400:
            return a, b
    return None


# ---------------- saldi ----------------

_AMT_CAP = rf"(?P<amt>[+-]?\s?{_CUR}?\s?{_NUM}(?![\d.,/])(?:\s?(?:[-+]|\b(?:[SH]|DR|CR)\b))?)"
_OPEN = (r"saldo\s+(?:iniziale|precedente|contabile\s+iniziale|(?:di\s+)?apertura|a\s+inizio\s+periodo)|opening\s+balance|"
         r"beginning\s+balance|previous\s+balance|balance\s+brought\s+forward|anfangssaldo|alter\s+kontostand|"
         r"kontostand\s+alt|saldo\s+vortrag|solde\s+(?:initial|précédent|d'ouverture)")
_CLOSE = (r"saldo\s+(?:finale|contabile\s+finale|contabile|nuovo|a\s+fine\s+periodo|(?:di\s+)?chiusura|attuale)|"
          r"nuovo\s+saldo|closing\s+balance|ending\s+balance|final\s+balance|balance\s+carried\s+forward|"
          r"schlusssaldo|endsaldo|endstand|neuer\s+kontostand|kontostand\s+neu|solde\s+(?:final|de\s+clôture)|nouveau\s+solde")
_AVAILABLE = r"saldo\s+disponibile|available\s+balance|verfügbarer\s+betrag|verfügbarer\s+saldo"
_AT_DATE = rf"(?:\s+(?:al|del|at|on|am|au)\s+(?P<dt>{DATE_NUM}|{DATE_TXT}))?"


def _label_re(label: str) -> "re.Pattern":
    return re.compile(rf"(?P<label>{label}){_AT_DATE}\s*[:\-]?\s*{_AMT_CAP}", re.IGNORECASE)


_OPEN_RE, _CLOSE_RE, _AVAIL_RE = _label_re(_OPEN), _label_re(_CLOSE), _label_re(_AVAILABLE)
_SALDO_AL_RE = re.compile(rf"saldo\s+al\s+(?P<dt>{DATE_NUM}|{DATE_TXT})\s*[:\-]?\s*{_AMT_CAP}", re.IGNORECASE)


_TOT_IN_RE = re.compile(rf"totale\s+(?:entrate|accrediti)\s*[:\-]?\s*{_AMT_CAP}", re.IGNORECASE)
_TOT_OUT_RE = re.compile(rf"totale\s+(?:uscite|addebiti)\s*[:\-]?\s*{_AMT_CAP}", re.IGNORECASE)


def find_balances(text: str, period: Optional[Tuple[pd.Timestamp, pd.Timestamp]]) -> Dict[str, Any]:
    """
    Saldi dichiarati dal documento: {'opening', 'closing', 'closing_source', 'multiple_closings', 'totals'}.
    Gli estratti a sezioni (conto, deposito, sintesi interessi) hanno più coppie iniziale/finale: si sceglie la
    coppia coerente con "Totale entrate/uscite" (iniziale + entrate - uscite = finale); altrimenti il finale
    con la data più recente.
    """
    out: Dict[str, Any] = {"opening": None, "closing": None, "closing_source": "none",
                           "multiple_closings": False, "totals": None}
    opens = [clean_numeric_amount(m.group("amt")) for m in _OPEN_RE.finditer(text)]
    closes = [(clean_numeric_amount(m.group("amt")), parse_pdf_date(m.group("dt")) if m.group("dt") else None)
              for m in _CLOSE_RE.finditer(text)]
    ins = [abs(clean_numeric_amount(m.group("amt"))) for m in _TOT_IN_RE.finditer(text)]
    outs = [abs(clean_numeric_amount(m.group("amt"))) for m in _TOT_OUT_RE.finditer(text)]
    if opens:
        out["opening"] = opens[0]
    if closes:
        out["multiple_closings"] = len({round(v, 2) for v, _ in closes}) > 1
        chosen = None
        for o in opens:                                      # coppia coerente: iniziale + entrate - uscite = finale
            for e in ins:
                for u in outs:
                    hit = next((c for c in closes if abs(c[0] - round(o + e - u, 2)) <= BALANCE_TOLERANCE), None)
                    if hit is not None and chosen is None:
                        chosen, out["opening"], out["totals"] = hit, o, (e, u)
        if chosen is None:
            dated = [c for c in closes if c[1] is not None]
            chosen = max(reversed(dated), key=lambda c: c[1]) if dated else closes[-1]
        out["closing"], out["closing_source"] = chosen[0], "label"

    # "Saldo al <data>": la data più vecchia è l'apertura, la più recente la chiusura
    dated = []
    for m in _SALDO_AL_RE.finditer(text):
        d = parse_pdf_date(m.group("dt"))
        if d is not None:
            dated.append((d, clean_numeric_amount(m.group("amt"))))
    dated.sort(key=lambda x: x[0])
    if dated:
        if len(dated) >= 2:
            if out["opening"] is None:
                out["opening"] = dated[0][1]
            if out["closing"] is None:
                out["closing"], out["closing_source"] = dated[-1][1], "label"
        else:
            d, v = dated[0]
            is_opening = period is not None and d <= period[0]
            if is_opening and out["opening"] is None:
                out["opening"] = v
            elif not is_opening and out["closing"] is None:
                out["closing"], out["closing_source"] = v, "label"

    if out["closing"] is None:
        avail = [clean_numeric_amount(m.group("amt")) for m in _AVAIL_RE.finditer(text)]
        if avail:
            out["closing"], out["closing_source"] = avail[-1], "available"
    return out


# ---------------- righe di movimento ----------------

def _explicit_sign(token: str) -> bool:
    t = token.strip().upper()
    return bool(re.search(r"[+-]", t) or re.search(r"\b(?:S|H|DR|CR)\b", t))


def _line_regex(with_short: bool) -> "re.Pattern":
    date = DATE_ANY + (rf"|{DATE_SHORT}" if with_short else "")
    return re.compile(
        rf"^(?P<d1>{date})(?:\s+(?P<d2>{date}))?(?:\s+(?P<desc>.+?))?\s+(?P<a1>{AMT})(?:\s+(?P<a2>{AMT}))?"
        rf"(?:\s*{_CUR})?$", re.IGNORECASE)


def _clean_desc(desc: Optional[str], institution: str) -> str:
    d = re.sub(r"\s+", " ", (desc or "")).strip(" -")
    return d[:200] if d else f"Movimento {institution}"


def _new_row(date: pd.Timestamp, amt: float, desc: str, balance_after: Optional[float], currency: str) -> Dict[str, Any]:
    low = desc.lower()
    internal = any(k in low for k in _INTERNAL_WORDS)
    row = {
        "date": date, "amount": amt, "currency": currency, "description": desc, "counterparty": desc,
        "category": "Giroconto" if internal else ("Entrata" if amt > 0 else "Uscita"),
        "is_internal_transfer": internal,
    }
    if balance_after is not None:
        row["balance_after"] = balance_after
    return row


def parse_text_rows(text: str, order: str, year_hint: Optional[int], period_end: Optional[pd.Timestamp],
                    institution: str, currency: str, notes: List[str]) -> List[Dict[str, Any]]:
    """Movimenti dalle righe di testo. Le righe di continuazione si agganciano alla descrizione precedente."""
    line_re = _line_regex(with_short=year_hint is not None)
    cands: List[Dict[str, Any]] = []
    last: Optional[Dict[str, Any]] = None
    continuation = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        cand = None
        m = line_re.match(line)
        if m:
            desc = (m.group("desc") or "").strip()
            if desc and _STOP_PREFIX.match(desc):
                last = None
                continue
            d_raw = m.group("d1")
            if re.fullmatch(DATE_SHORT, d_raw):
                d = _parse_short_date(d_raw, year_hint, period_end) if year_hint else None
            else:
                d = parse_pdf_date(d_raw, order)
            if d is not None:
                cand = {"date": d, "desc": desc, "a1": m.group("a1"), "a2": m.group("a2")}
        if cand is not None:
            cands.append(cand)
            last, continuation = cand, 0
            continue
        # riga di continuazione della descrizione
        if last is not None and continuation < 3 and not _BOILERPLATE.search(line) and len(line) <= 90 \
                and re.search(r"[A-Za-zÀ-ÿ]", line) and not re.match(rf"^{DATE_ANY}", line) \
                and not re.search(_NUM, line):
            last["desc"] = f"{last['desc']} {line}".strip()
            continuation += 1
        else:
            last = None

    # Se meno della metà delle righe ha due numeri, il secondo non è un saldo: l'importo è l'ultimo
    # numero e il primo fa parte della descrizione ("Rata 3,50 -25,40").
    two = sum(1 for c in cands if c["a2"])
    second_is_balance = bool(cands) and two / len(cands) >= 0.5

    rows: List[Dict[str, Any]] = []
    inferred_signs = 0
    for c in cands:
        if c["a2"] and not second_is_balance:
            desc, amt_tok, bal = f"{c['desc']} {c['a1']}".strip(), c["a2"], None
        else:
            desc, amt_tok = c["desc"], c["a1"]
            bal = clean_numeric_amount(c["a2"]) if c["a2"] else None
        amt = clean_numeric_amount(amt_tok)
        if amt == 0.0:
            continue
        desc = _clean_desc(desc, institution)
        if bal is None and not _explicit_sign(amt_tok) and _UNSIGNED_DEBIT_WORDS.search(desc) \
                and not _CREDIT_WORDS.search(desc):
            amt, inferred_signs = -abs(amt), inferred_signs + 1
        row = _new_row(c["date"], amt, desc, bal, currency)
        row["_unsigned"] = bal is not None and not _explicit_sign(amt_tok)   # segno da verificare con la catena dei saldi
        rows.append(row)

    if inferred_signs:
        notes.append(f"{inferred_signs} importi senza segno interpretati dalla descrizione: controlla i totali")
    return rows


def rows_from_tables(tables: List[Any], order: str, institution: str, currency: str, notes: List[str]) -> List[Dict[str, Any]]:
    """Movimenti da tabelle strutturate: intestazioni riconosciute in IT/EN/DE, colonne entrate/uscite o importo unico."""
    rows: List[Dict[str, Any]] = []
    inferred_signs = 0
    for table in tables:
        if not table or len(table) < 2:
            continue
        date_col = desc_col = amt_col = in_col = out_col = bal_col = -1
        header_idx = -1
        for r_i, r in enumerate(table[:3]):
            cells = [str(c or "").lower().strip() for c in r]
            if any(k in c for c in cells for k in ("data", "date", "datum")) or \
               any(k in c for c in cells for k in ("importo", "amount", "betrag", "entrate", "uscite", "soll", "haben")):
                header_idx = r_i
                for c_i, c in enumerate(cells):
                    if any(k in c for k in ("data", "date", "datum", "buchung", "valuta")) and date_col == -1:
                        date_col = c_i
                    elif any(k in c for k in ("descrizione", "causale", "buchungstext", "partner", "payee", "description",
                                              "verwendungszweck", "dettaglio", "text")) and desc_col == -1:
                        desc_col = c_i
                    elif any(k in c for k in ("entrate", "accrediti", "money in", "credit", "haben", "avere")) \
                            and not any(k in c for k in ("uscite", "addebiti")):
                        in_col = c_i
                    elif any(k in c for k in ("uscite", "addebiti", "money out", "debit", "soll", "dare")) \
                            and not any(k in c for k in ("entrate", "accrediti")):
                        out_col = c_i
                    elif any(k in c for k in ("saldo", "balance", "kontostand")) and bal_col == -1:
                        bal_col = c_i
                    elif any(k in c for k in ("importo", "amount", "betrag", "valore")) and amt_col == -1:
                        amt_col = c_i
                break
        for row in table[header_idx + 1:]:
            if not row or len(row) < 2:
                continue
            d = first_date_in(row[date_col], order) if 0 <= date_col < len(row) else None
            if d is None:
                for c_i, cell in enumerate(row):
                    d = first_date_in(cell, order)
                    if d is not None:
                        date_col = c_i if date_col == -1 else date_col
                        break
            if d is None:
                continue
            amt, explicit = 0.0, True
            if in_col != -1 and out_col != -1 and in_col != out_col and max(in_col, out_col) < len(row):
                v_in, v_out = clean_numeric_amount(row[in_col]), clean_numeric_amount(row[out_col])
                amt = v_in if v_in != 0 else -abs(v_out)
            elif 0 <= amt_col < len(row):
                amt = clean_numeric_amount(row[amt_col])
                explicit = _explicit_sign(str(row[amt_col] or ""))
            else:
                for c_i, cell in enumerate(row):
                    if c_i == date_col or first_date_in(cell, order) is not None:
                        continue
                    v = clean_numeric_amount(cell)
                    if v != 0.0:
                        amt, explicit = v, _explicit_sign(str(cell or ""))
                        break
            if amt == 0.0:
                continue
            if 0 <= desc_col < len(row) and row[desc_col]:
                desc = str(row[desc_col])
            else:
                others = [str(c).strip() for c_i, c in enumerate(row)
                          if c_i not in (date_col, amt_col, in_col, out_col, bal_col) and str(c or "").strip()
                          and first_date_in(c, order) is None]
                desc = " - ".join(others)
            desc = _clean_desc(desc, institution)
            if _STOP_PREFIX.match(desc):
                continue
            if amt > 0 and not explicit and _UNSIGNED_DEBIT_WORDS.search(desc) and not _CREDIT_WORDS.search(desc):
                amt, inferred_signs = -abs(amt), inferred_signs + 1
            bal = clean_numeric_amount(row[bal_col]) if 0 <= bal_col < len(row) and str(row[bal_col] or "").strip() else None
            row = _new_row(d, amt, desc, bal, currency)
            row["_unsigned"] = bal is not None and not explicit
            rows.append(row)
    if inferred_signs:
        notes.append(f"{inferred_signs} importi senza segno interpretati dalla descrizione: controlla i totali")
    return rows


# ---------------- catena dei saldi ----------------

def _guess_unsigned(rows: List[Dict[str, Any]]) -> int:
    """Per le righe con importo senza segno che la catena dei saldi non ha potuto verificare: indizio dalla descrizione."""
    n = 0
    for r in rows:
        if r.pop("_unsigned", False) and r["amount"] > 0 and _UNSIGNED_DEBIT_WORDS.search(r["description"]) \
                and not _CREDIT_WORDS.search(r["description"]):
            r["amount"] = -r["amount"]
            r["category"] = "Giroconto" if r["is_internal_transfer"] else "Uscita"
            n += 1
    return n


def _note_guessed(n: int, notes: List[str]) -> None:
    if n:
        notes.append(f"{n} importi senza segno interpretati dalla descrizione: controlla i totali")


def check_balance_chain(rows: List[Dict[str, Any]], opening: Optional[float], notes: List[str]) -> Dict[str, Any]:
    """
    Se le righe hanno `balance_after`, verifica che ogni saldo = saldo precedente + importo.
    Corregge i segni spiegati dalla variazione del saldo, orienta le righe in ordine cronologico
    (gli estratti con il più recente in alto vengono rovesciati sul posto) e scarta la colonna saldo se
    incoerente. Restituisce {'valid', 'running_open', 'running_close'}.
    """
    info: Dict[str, Any] = {"valid": False, "running_open": None, "running_close": None}
    with_bal = [r for r in rows if r.get("balance_after") is not None]
    if len(with_bal) < 2:
        if len(rows) > 1:
            for r in rows:
                r.pop("balance_after", None)
        _note_guessed(_guess_unsigned(rows), notes)
        return info

    def matches(older: Dict[str, Any], newer: Dict[str, Any]) -> bool:
        """Il saldo di `newer` = saldo di `older` + importo di `newer`, a meno del segno."""
        delta = round(newer["balance_after"] - older["balance_after"], 2)
        return abs(abs(delta) - abs(newer["amount"])) <= BALANCE_TOLERANCE

    pairs = [(i - 1, i) for i in range(1, len(rows))
             if rows[i - 1].get("balance_after") is not None and rows[i].get("balance_after") is not None]
    fwd = sum(1 for a, b in pairs if matches(rows[a], rows[b]))     # righe in ordine cronologico
    bwd = sum(1 for a, b in pairs if matches(rows[b], rows[a]))     # più recente in alto
    if not pairs or max(fwd, bwd) / len(pairs) < 0.5:
        for r in rows:
            r.pop("balance_after", None)
        notes.append("la colonna saldo non è coerente con i movimenti: ignorata, controlla i totali")
        _note_guessed(_guess_unsigned(rows), notes)
        return info

    if bwd > fwd:
        rows.reverse()                                              # ora in ordine cronologico

    fixed = breaks = guessed = 0
    prev = opening
    for r in rows:
        bal = r.get("balance_after")
        if bal is None:
            continue
        if prev is not None:
            delta = round(bal - prev, 2)
            if abs(abs(delta) - abs(r["amount"])) <= BALANCE_TOLERANCE:
                if (delta > 0) != (r["amount"] > 0):
                    r["amount"], fixed = delta, fixed + 1
                    r["category"] = "Giroconto" if r["is_internal_transfer"] else ("Entrata" if delta > 0 else "Uscita")
            else:
                breaks += 1
        else:
            # Prima riga senza saldo precedente: nessuna variazione da confrontare, resta solo l'indizio dalla descrizione
            guessed += _guess_unsigned([r])
        prev = bal
    for r in rows:
        r.pop("_unsigned", None)
    _note_guessed(guessed, notes)

    first = next(r for r in rows if r.get("balance_after") is not None)
    last = next(r for r in reversed(rows) if r.get("balance_after") is not None)
    info.update(valid=True, running_close=last["balance_after"],
                running_open=round(first["balance_after"] - first["amount"], 2) if first is rows[0] else None)
    if fixed:
        notes.append(f"{fixed} segni corretti usando la variazione del saldo")
    if breaks:
        notes.append(f"{breaks} movimenti non quadrano con la colonna saldo: possibili righe non lette")
    return info


# ---------------- orchestrazione ----------------

def _year_hint(period, text: str) -> Optional[int]:
    if period is not None:
        return period[1].year
    years = re.findall(r"\b(20\d{2})\b", text[:4000])
    return int(Counter(years).most_common(1)[0][0]) if years else None


def analyze_pdf_text(text: str, tables: List[Any], loose_tables: List[Any], filename: str) -> PdfAnalysis:
    res = PdfAnalysis()
    header = f"{filename} {text[:4000]}"
    res.institution = detect_institution(header, filename)
    res.currency = detect_currency(text)
    res.iban = find_iban(text)
    res.account_tail = res.iban[-4:] if res.iban else find_account_tail(text)
    res.period = find_period(text)
    res.date_order = detect_date_order(text)
    year = _year_hint(res.period, text)
    period_end = res.period[1] if res.period else None

    if res.currency != "EUR":
        res.warnings.append(f"valuta {res.currency}: gli importi non sono convertiti in EUR")

    rows = rows_from_tables(tables, res.date_order, res.institution, res.currency, res.warnings) if tables else []
    res.row_source = "table" if rows else "none"
    if not rows:
        rows = parse_text_rows(text, res.date_order, year, period_end, res.institution, res.currency, res.warnings)
        res.row_source = "text" if rows else "none"
    if not rows and loose_tables:
        rows = rows_from_tables(loose_tables, res.date_order, res.institution, res.currency, res.warnings)
        res.row_source = "table-loose" if rows else "none"

    declared = find_balances(text, res.period)
    if declared["multiple_closings"]:
        res.warnings.append("trovati più saldi finali diversi (conto e sezioni accessorie): scelto quello coerente "
                            "con i totali o il più recente, controlla che sia il conto giusto")
    res.opening = declared["opening"]
    res.opening_explicit = declared["opening"] is not None
    chain = check_balance_chain(rows, res.opening, res.warnings) if rows else \
        {"valid": False, "running_open": None, "running_close": None}
    res.rows = rows

    if res.opening is None and chain["running_open"] is not None:
        res.opening = chain["running_open"]

    total = round(sum(r["amount"] for r in rows), 2)
    if declared["closing"] is not None:
        res.closing, res.closing_source = declared["closing"], declared["closing_source"]
        if res.closing_source == "available":
            res.warnings.append("usato il saldo disponibile (può differire dal saldo contabile)")
    elif chain["valid"] and chain["running_close"] is not None:
        res.closing, res.closing_source = chain["running_close"], "running"
    elif res.opening is not None and rows:
        res.closing, res.closing_source = round(res.opening + total, 2), "derived"
    elif rows:
        res.closing, res.closing_source = total, "estimated"
        res.balance_estimated = True

    # Quadratura: iniziale + movimenti = finale
    if rows and res.closing_source in ("label", "available") and res.opening is not None:
        diff = round(res.closing - (res.opening + total), 2)
        res.reconciliation_diff = diff
        res.reconciled = abs(diff) <= BALANCE_TOLERANCE
        if not res.reconciled:
            listed_in = round(sum(r["amount"] for r in rows if r["amount"] > 0), 2)
            listed_out = round(-sum(r["amount"] for r in rows if r["amount"] < 0), 2)
            totals = declared.get("totals")
            if totals and (abs(listed_in - totals[0]) > BALANCE_TOLERANCE or abs(listed_out - totals[1]) > BALANCE_TOLERANCE):
                # I totali dichiarati quadrano con i saldi: è l'elenco dei movimenti a essere incompleto
                res.movements_incomplete = True
                res.warnings.append(
                    f"il PDF dichiara entrate {fmt_it(totals[0])} e uscite {fmt_it(totals[1])} che quadrano con i saldi, "
                    f"ma i movimenti elencati sono solo {len(rows)} (entrate {fmt_it(listed_in)}, uscite {fmt_it(listed_out)}): "
                    "elenco incompleto, il saldo finale dichiarato è affidabile")
            else:
                res.warnings.append(
                    f"i movimenti non quadrano con i saldi dichiarati (scarto {fmt_signed_it(diff)} {res.currency}): "
                    "possibili righe non lette o doppie")
    elif rows and res.closing_source == "label" and chain["valid"] and chain["running_close"] is not None:
        diff = round(res.closing - chain["running_close"], 2)
        res.reconciliation_diff = diff
        res.reconciled = abs(diff) <= BALANCE_TOLERANCE
        if not res.reconciled:
            res.warnings.append(
                f"il saldo finale dichiarato differisce dall'ultimo saldo di riga (scarto {fmt_signed_it(diff)} {res.currency})")

    if not rows:
        res.warnings.append("nessun movimento riconosciuto nel PDF")
    return res


def _chain_day(day: List[Dict[str, Any]], start_balance: Optional[float]) -> List[Dict[str, Any]]:
    """Ordina i movimenti di un giorno in modo che ogni saldo = saldo precedente + importo (se possibile)."""
    remaining, out, cur = list(day), [], start_balance
    while remaining:
        pick = None
        if cur is not None:
            pick = next((r for r in remaining
                         if abs(round(cur + r["amount"] - r["balance_after"], 2)) <= BALANCE_TOLERANCE), None)
        if pick is None:
            pick = remaining[0]                       # nessun anello compatibile: si conserva l'ordine originale
        remaining.remove(pick)
        out.append(pick)
        cur = pick["balance_after"]
    return out


def order_rows_within_days(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ordine cronologico per data e, dentro ogni giorno, secondo la catena dei saldi. I PDF spesso elencano i
    movimenti dello stesso giorno in ordine diverso da quello di esecuzione: senza questo, il "saldo a una data"
    prenderebbe la riga sbagliata come ultima del giorno.
    """
    ordered = sorted(rows, key=lambda r: r["date"])           # stabile
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j]["date"] == ordered[i]["date"]:
            j += 1
        day = ordered[i:j]
        if len(day) > 1 and all(r.get("balance_after") is not None for r in day):
            start = out[-1].get("balance_after") if out else None
            day = _chain_day(day, start)
        out.extend(day)
        i = j
    return out


def build_transactions_frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(order_rows_within_days(rows)).reset_index(drop=True)
