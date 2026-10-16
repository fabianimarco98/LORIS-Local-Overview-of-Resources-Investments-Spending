# ============================================================
# BANKING MODULE — UNIVERSAL BANK STATEMENT PARSERS
# ============================================================
"""
Parser universale per estratti conto multi-banca:
- Trade Republic (Cash, PAC, Titoli, Interessi, Carta)
- Erste Bank / Sparkasse (George Austria)
- Banche Italiane (UniCredit, Intesa Sanpaolo, Fineco, Widiba, Poste)
- Banche Digitali (Revolut, N26)
- Rilevatore euristico universale per qualsiasi CSV, Excel (.xlsx/.xls) e PDF.
"""

from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .user_profile import employer_keywords, owner_names

# Supporto per PDF (pdfplumber e pypdf)
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


@dataclass
class BankStatement:
    """Rappresentazione unificata e normalizzata di un estratto conto bancario."""
    account_id: str
    institution: str
    account_type: str  # 'Checking', 'HighYieldCash', 'Brokerage', 'MultiCurrency', 'CreditCard'
    asset_class: str   # 'LIQUID_CASH', 'HIGH_YIELD_CASH', 'INVESTMENTS', 'OTHER'
    currency: str = "EUR"
    start_date: Optional[pd.Timestamp] = None
    end_date: Optional[pd.Timestamp] = None
    starting_balance: Optional[float] = None
    ending_balance: Optional[float] = None
    transactions: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_file: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def _decode_text(data: bytes) -> str:
    """Decodifica robusta di file testuali bancari: BOM UTF-16/UTF-8, UTF-8, ripiego su cp1252 (Windows/Excel)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        # Campione troncato a metà carattere: il resto è UTF-8 valido
        if e.start >= len(data) - 4:
            return data.decode("utf-8", errors="ignore")
        return data.decode("cp1252", errors="replace")



def clean_numeric_amount(val: Any) -> float:
    """
    Converte importi da formati europei (es. '-1.250,50 €', '1.250,50-', '150,00 S')
    o anglosassoni ('-1,250.50', '1,250.50 DR') in un float standard Python.
    """
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip().replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    if not s:
        return 0.0

    # Gestione segno contabile:
    # 1. Marcatori Soll (S = debit), DR (debit), Uscita / Addebito
    # 2. Marcatori Haben (H = credit), CR (credit), Entrata / Accredito
    # 3. Meno iniziale o finale (100,00- o -100,00) o parentesi contabili (100.00)
    is_neg = False
    upper_s = s.upper()

    if re.search(r"\bS\b|\bSOLL\b|\bDR\b|\bDEBIT\b|\bUSCITA\b|\bADDEBITO\b", upper_s):
        is_neg = True
    elif re.search(r"\bH\b|\bHABEN\b|\bCR\b|\bCREDIT\b|\bENTRATA\b|\bACCREDITO\b", upper_s):
        is_neg = False
    elif (upper_s.startswith("(") and upper_s.endswith(")")) or upper_s.startswith("-") or upper_s.endswith("-") or re.search(r"-\s*[\d.,]+", upper_s):
        is_neg = True

    # Protezione anti-IBAN, codici identificativi, numeri di conto, ISIN o telefoni:
    pure_digits = re.sub(r"\D", "", s)
    if ("." not in s and "," not in s) and len(pure_digits) > 6:
        return 0.0
    if len(pure_digits) > 11:
        return 0.0

    # Rimuovi tutto ciò che non è cifra, punto o virgola
    s_digits = re.sub(r"[^\d.,]", "", s)
    if not re.search(r"\d", s_digits):
        return 0.0

    # Se contiene sia virgola che punto (es. 1.250,50 oppure 1,250.50)
    if "." in s_digits and "," in s_digits:
        if s_digits.rfind(",") > s_digits.rfind("."):
            # Formato europeo: 1.250,50 -> 1250.50
            s_digits = s_digits.replace(".", "").replace(",", ".")
        else:
            # Formato anglosassone: 1,250.50 -> 1250.50
            s_digits = s_digits.replace(",", "")
    elif "," in s_digits or "." in s_digits:
        # Un solo tipo di separatore: migliaia (1.250 / 1.250.000 / 12,345) o decimale (1250,50 / 0.500)
        sep = "," if "," in s_digits else "."
        head, _, tail = s_digits.partition(sep)
        is_thousands = s_digits.count(sep) > 1 or (len(tail) == 3 and 1 <= len(head) <= 3 and head != "0")
        s_digits = s_digits.replace(sep, "") if is_thousands else s_digits.replace(",", ".")

    try:
        res = float(s_digits)
        if abs(res) > 50_000_000:
            return 0.0
        return -res if is_neg else res
    except ValueError:
        return 0.0


MONTH_MAP = {
    # IT
    "gennaio": "Jan", "gen": "Jan",
    "febbraio": "Feb", "feb": "Feb",
    "marzo": "Mar", "mar": "Mar",
    "aprile": "Apr", "apr": "Apr",
    "maggio": "May", "mag": "May",
    "giugno": "Jun", "giu": "Jun",
    "luglio": "Jul", "lug": "Jul",
    "agosto": "Aug", "ago": "Aug",
    "settembre": "Sep", "set": "Sep", "sett": "Sep",
    "ottobre": "Oct", "ott": "Oct",
    "novembre": "Nov", "nov": "Nov",
    "dicembre": "Dec", "dic": "Dec",
    # DE
    "märz": "Mar", "mär": "Mar", "maer": "Mar",
    "mai": "May",
    "juni": "Jun",
    "juli": "Jul",
    "oktober": "Oct", "okt": "Oct",
    "dezember": "Dec", "dez": "Dec",
}


def parse_flexible_date(val: Any) -> Optional[pd.Timestamp]:
    """Interpreta date in molteplici formati europei, internazionali e con nomi mese."""
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, pd.Timestamp):
        return val.normalize()
    if hasattr(val, "strftime") and not isinstance(val, str):
        try:
            return pd.to_datetime(val).normalize()
        except Exception:
            pass
    if isinstance(val, (int, float)):
        return None

    s = str(val).strip()
    if not s:
        return None

    # Tenta formati comuni numerici espliciti
    formats = [
        "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
        "%d/%m/%y", "%d.%m.%y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"
    ]
    for fmt in formats:
        try:
            return pd.to_datetime(s, format=fmt).normalize()
        except (ValueError, TypeError):
            continue

    # Normalizza eventuali nomi di mesi in IT o DE a EN per pd.to_datetime
    s_norm = s.lower()
    for m_local, m_en in MONTH_MAP.items():
        if m_local in s_norm:
            s_norm = re.sub(r"\b" + re.escape(m_local) + r"\b", m_en, s_norm)
            break

    # Formati con mese testuale (es. "15 Jul 2026", "15. Juli 2026", "Jul 15, 2026")
    text_formats = [
        "%d %b %Y", "%d %B %Y",
        "%d. %b %Y", "%d. %B %Y",
        "%b %d, %Y", "%B %d, %Y",
        "%d-%b-%Y", "%d-%b-%y",
    ]
    for fmt in text_formats:
        try:
            return pd.to_datetime(s_norm, format=fmt).normalize()
        except (ValueError, TypeError):
            continue

    try:
        # Fallback euristico di pandas
        return pd.to_datetime(s_norm, dayfirst=True).normalize()
    except Exception:
        return None


class BaseBankParser:
    """Classe base per i singoli parser bancari."""
    INSTITUTION_NAME = "Generic"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        raise NotImplementedError

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        raise NotImplementedError


# ============================================================
# PARSER 1: TRADE REPUBLIC
# ============================================================
class TradeRepublicParser(BaseBankParser):
    INSTITUTION_NAME = "Trade Republic"
    DEFAULT_ASSET_CLASS = "HIGH_YIELD_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False
        if "trade" in fn or "republic" in fn:
            return True
        if isinstance(file_content, bytes):
            sample = _decode_text(file_content[:2048])
        else:
            sample = file_content[:2048]
        # Se ha intestazioni austriache/tedesche di George, è Erste Bank
        if "buchungsdatum" in sample.lower() or "partner-iban" in sample.lower():
            return False
        indicators = [
            "trade republic", "zinsen", "sparplan", "isin", "order-id", "cash-konto",
            "interessi", "pac", "cedola", "dividendo", "kartentransaktion", "republic",
            "tagesgeld", "kontoauszug", "estratto conto", "interest payment", "saveback"
        ]
        return sum(1 for ind in indicators if ind.lower() in sample.lower()) >= 1

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        if isinstance(file_content, bytes):
            text = _decode_text(file_content)
        else:
            text = file_content

        # Tenta lettura CSV con separatore virgola, punto e virgola, tabulazione o pipe
        df = None
        for sep in [",", ";", "\t", "|"]:
            for skip in [0, 1, 2, 3]:
                try:
                    temp_df = pd.read_csv(io.StringIO(text), sep=sep, skiprows=skip, on_bad_lines="skip")
                    if len(temp_df.columns) >= 3 and len(temp_df) > 0:
                        df = temp_df
                        break
                except Exception:
                    continue
            if df is not None:
                break

        if df is None or len(df) == 0:
            raise ValueError(f"Impossibile leggere il file Trade Republic: {filename}")

        # Normalizza nomi colonne
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Identifica colonne chiave (Multilingua: IT, EN, DE, FR)
        date_col = next((c for c in df.columns if any(k in c for k in ["datum", "date", "timestamp", "data", "giorno", "time"])), df.columns[0])
        amt_col = next((c for c in df.columns if any(k in c for k in ["betrag", "amount", "wert", "value", "importo", "valore", "prezzo", "totale", "montant"])), None)
        type_col = next((c for c in df.columns if any(k in c for k in ["typ", "type", "art", "tipo", "operazione", "transazione", "action"])), None)
        desc_col = next((c for c in df.columns if any(k in c for k in ["name", "beschreibung", "description", "titel", "descrizione", "causale", "dettaglio", "note", "payee"])), None)
        bal_col = next((c for c in df.columns if any(k in c for k in ["saldo", "balance", "kontostand", "solde", "disponibile"])), None)

        rows = []
        for _, r in df.iterrows():
            d = parse_flexible_date(r[date_col])
            if d is None:
                continue

            raw_amt = r[amt_col] if amt_col else 0.0
            amount = clean_numeric_amount(raw_amt)
            tx_type = str(r[type_col]).strip() if type_col else "Movimento"
            tx_desc = str(r[desc_col]).strip() if desc_col else tx_type
            tx_bal = clean_numeric_amount(r[bal_col]) if bal_col and bal_col in r and not pd.isna(r[bal_col]) else None

            # Dettaglio categoria e asset
            cat = "Altro"
            is_internal = False
            tx_lower = (tx_type + " " + tx_desc).lower()

            if any(k in tx_lower for k in ["zins", "interest", "interessi", "intérêts", "saveback", "bonus"]):
                cat = "Interessi Attivi"
            elif any(k in tx_lower for k in ["sparplan", "pac", "etf", "kauf", "buy", "aktie", "shares", "azioni", "ordine", "achat", "handel"]):
                cat = "Investimento ETF / Azioni"
            elif any(k in tx_lower for k in ["einzahlung", "deposit", "deposito", "bonifico in entrata", "incoming transfer", "virement entrant"]):
                cat = "Giroconto Entrata"
                is_internal = True
            elif any(k in tx_lower for k in ["auszahlung", "withdrawal", "prelievo", "bonifico in uscita", "outgoing transfer", "virement sortant"]):
                cat = "Giroconto Uscita"
                is_internal = True
            elif any(k in tx_lower for k in ["karte", "card", "spend", "kartentransaktion", "carta"]):
                cat = "Spesa Carta"

            rows.append({
                "date": d,
                "amount": amount,
                "currency": "EUR",
                "description": tx_desc,
                "counterparty": "Trade Republic",
                "category": cat,
                "tx_type": tx_type,
                "balance_after": tx_bal,
                "is_internal_transfer": is_internal,
            })

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None

        # Calcolo saldo: se presente colonna saldo, usa l'ultimo non-nullo; altrimenti somma
        if not tx_df.empty and "balance_after" in tx_df.columns and tx_df["balance_after"].notna().any():
            net_cash = float(tx_df["balance_after"].dropna().iloc[-1])
        else:
            net_cash = float(tx_df["amount"].sum()) if not tx_df.empty else 0.0

        return BankStatement(
            account_id="Trade_Republic_Cash",
            institution="Trade Republic",
            account_type="HighYieldCash",
            asset_class="HIGH_YIELD_CASH",
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=net_cash,
            transactions=tx_df,
            source_file=filename,
            metadata={"total_transactions": len(tx_df), "platform": "Trade Republic"}
        )


# ============================================================
# PARSER 2: ERSTE BANK / SPARKASSE (GEORGE AUSTRIA)
# ============================================================
class ErsteBankParser(BaseBankParser):
    INSTITUTION_NAME = "Erste Bank (George)"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False
        if "erste" in fn or "george" in fn or "sparkasse" in fn:
            return True
        if isinstance(file_content, bytes):
            sample = _decode_text(file_content[:2048])
        else:
            sample = file_content[:2048]
        indicators = ["Buchungsdatum", "Partnername", "Partner-IBAN", "Buchungstext", "Valutadatum"]
        return sum(1 for ind in indicators if ind.lower() in sample.lower()) >= 2

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        if isinstance(file_content, bytes):
            text = _decode_text(file_content)
        else:
            text = file_content

        df = None
        for sep in [";", ",", "\t"]:
            try:
                temp_df = pd.read_csv(io.StringIO(text), sep=sep)
                if len(temp_df.columns) >= 4 and len(temp_df) > 0:
                    df = temp_df
                    break
            except Exception:
                continue

        if df is None or len(df) == 0:
            raise ValueError(f"Impossibile leggere il file Erste Bank: {filename}")

        df.columns = [str(c).strip().lower() for c in df.columns]

        date_col = next((c for c in df.columns if "buchungsdatum" in c or "date" in c), df.columns[0])
        amt_col = next((c for c in df.columns if "betrag" in c or "amount" in c), None)
        partner_col = next((c for c in df.columns if "partnername" in c or "empfänger" in c), None)
        text_col = next((c for c in df.columns if "buchungstext" in c or "verwendungszweck" in c), None)
        iban_col = next((c for c in df.columns if "iban" in c), None)

        rows = []
        for _, r in df.iterrows():
            d = parse_flexible_date(r[date_col])
            if d is None:
                continue

            amount = clean_numeric_amount(r[amt_col]) if amt_col else 0.0
            partner = str(r[partner_col]).strip() if partner_col and not pd.isna(r[partner_col]) else ""
            btext = str(r[text_col]).strip() if text_col and not pd.isna(r[text_col]) else ""
            full_desc = f"{partner} - {btext}".strip(" -")
            p_iban = str(r[iban_col]).strip() if iban_col and not pd.isna(r[iban_col]) else ""

            # Rilevamento stipendio o trasferimenti interni
            is_internal = False
            cat = "Spesa Generale"
            desc_lower = full_desc.lower()

            if "gehalt" in desc_lower or any(k in desc_lower for k in employer_keywords()):
                cat = "Salary"
            elif any(k in desc_lower for k in ["trade republic", "revolut", "girokonto", "übertrag"]):
                cat = "Giroconto / Trasferimento"
                is_internal = True
            elif amount > 0:
                cat = "Entrata"

            rows.append({
                "date": d,
                "amount": amount,
                "currency": "EUR",
                "description": full_desc if full_desc else "Operazione George",
                "counterparty": partner if partner else "Altro",
                "counterparty_iban": p_iban,
                "category": cat,
                "is_internal_transfer": is_internal,
            })

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None

        return BankStatement(
            account_id="Erste_Bank_Girokonto",
            institution="Erste Bank",
            account_type="Checking",
            asset_class="LIQUID_CASH",
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=float(tx_df["amount"].sum()) if not tx_df.empty else 0.0,
            transactions=tx_df,
            source_file=filename,
            metadata={"bank": "Erste Bank Österreich"}
        )


# ============================================================
# PARSER 3: BANCHE ITALIANE (UNICREDIT, INTESA, FINECO, ECC.)
# ============================================================
class ItalianBankParser(BaseBankParser):
    INSTITUTION_NAME = "Banca Italiana"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False
        if any(b in fn for b in ["unicredit", "intesa", "fineco", "widiba", "poste", "bpm", "bper", "sanpaolo"]):
            return True
        if isinstance(file_content, bytes):
            sample = _decode_text(file_content[:2048])
        else:
            sample = file_content[:2048]
        indicators = ["Data Operazione", "Data Valuta", "Causale", "Descrizione", "Entrate", "Uscite", "Saldo Contabile"]
        return sum(1 for ind in indicators if ind.lower() in sample.lower()) >= 2

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        if isinstance(file_content, bytes):
            text = _decode_text(file_content)
        else:
            text = file_content

        df = None
        for sep in [";", ",", "\t"]:
            try:
                # Alcuni estratti hanno righe di intestazione: prova con skiprows
                for skip in [0, 1, 2, 3, 5, 8]:
                    temp_df = pd.read_csv(io.StringIO(text), sep=sep, skiprows=skip)
                    if len(temp_df.columns) >= 3 and len(temp_df) > 0:
                        cols_lower = [str(c).lower() for c in temp_df.columns]
                        if any("data" in c for c in cols_lower):
                            df = temp_df
                            break
                if df is not None:
                    break
            except Exception:
                continue

        if df is None or len(df) == 0:
            raise ValueError(f"Impossibile leggere l'estratto conto italiano: {filename}")

        df.columns = [str(c).strip().lower() for c in df.columns]

        date_col = next((c for c in df.columns if any(k in c for k in ["data operazione", "data contabile", "data"])), df.columns[0])
        desc_col = next((c for c in df.columns if any(k in c for k in ["causale", "descrizione", "operazione"])), None)
        bal_col = next((c for c in df.columns if any(k in c for k in ["saldo", "saldo contabile", "saldo disponibile"])), None)

        # Controlla se gli importi sono su colonna unica o divisi in entrate/uscite
        amt_col = next((c for c in df.columns if any(k in c for k in ["importo", "amount"])), None)
        in_col = next((c for c in df.columns if any(k in c for k in ["entrate", "avere", "accrediti"])), None)
        out_col = next((c for c in df.columns if any(k in c for k in ["uscite", "dare", "addebiti"])), None)

        rows = []
        for _, r in df.iterrows():
            d = parse_flexible_date(r[date_col])
            if d is None:
                continue

            if amt_col:
                amount = clean_numeric_amount(r[amt_col])
            elif in_col and out_col:
                in_val = clean_numeric_amount(r[in_col])
                out_val = clean_numeric_amount(r[out_col])
                amount = in_val if in_val != 0 else -abs(out_val)
            else:
                amount = 0.0

            desc = str(r[desc_col]).strip() if desc_col and not pd.isna(r[desc_col]) else "Operazione Bancaria"
            bal = clean_numeric_amount(r[bal_col]) if bal_col and not pd.isna(r[bal_col]) else None

            is_internal = any(k in desc.lower() for k in ["giroconto", "trade republic", "revolut", "trasferimento"])

            rows.append({
                "date": d,
                "amount": amount,
                "currency": "EUR",
                "description": desc,
                "counterparty": "Banca Italiana",
                "category": "Entrata" if amount > 0 else "Uscita",
                "balance_after": bal,
                "is_internal_transfer": is_internal,
            })

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None
        end_bal = tx_df["balance_after"].dropna().iloc[-1] if not tx_df.empty and tx_df["balance_after"].notna().any() else float(tx_df["amount"].sum())

        return BankStatement(
            account_id="Conto_Corrente_Italia",
            institution="Banca Italiana",
            account_type="Checking",
            asset_class="LIQUID_CASH",
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=end_bal,
            transactions=tx_df,
            source_file=filename,
        )


# ============================================================
# PARSER 4: REVOLUT & N26
# ============================================================
class DigitalBankParser(BaseBankParser):
    INSTITUTION_NAME = "Revolut / N26"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False
        if "revolut" in fn or "n26" in fn:
            return True
        if isinstance(file_content, bytes):
            sample = _decode_text(file_content[:2048])
        else:
            sample = file_content[:2048]
        indicators = ["Started Date", "Completed Date", "Payment reference", "Transaction type", "Amount (EUR)"]
        return any(ind.lower() in sample.lower() for ind in indicators)

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        if isinstance(file_content, bytes):
            text = _decode_text(file_content)
        else:
            text = file_content

        df = pd.read_csv(io.StringIO(text))
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Revolut standard
        started_col = next((c for c in df.columns if "started date" in c), None)
        completed_col = next((c for c in df.columns if "completed date" in c), None)
        date_col = started_col or completed_col or next((c for c in df.columns if "date" in c), df.columns[0])
        amt_col = next((c for c in df.columns if "amount" in c or "betrag" in c), None)
        desc_col = next((c for c in df.columns if "description" in c or "payee" in c or "payment reference" in c), None)
        bal_col = next((c for c in df.columns if "balance" in c), None)
        state_col = next((c for c in df.columns if "state" in c), None)
        type_col = next((c for c in df.columns if "type" in c), None)

        rows = []
        for _, r in df.iterrows():
            # Filtra transazioni annullate o fallite
            if state_col and str(r.get(state_col, "")).strip().upper() == "REVERTED":
                continue

            d = None
            if completed_col and not pd.isna(r[completed_col]):
                d = parse_flexible_date(r[completed_col])
            if d is None and started_col and not pd.isna(r[started_col]):
                d = parse_flexible_date(r[started_col])
            if d is None:
                d = parse_flexible_date(r[date_col])
            if d is None:
                continue

            amount = clean_numeric_amount(r[amt_col]) if amt_col else 0.0
            desc = str(r[desc_col]).strip() if desc_col and not pd.isna(r[desc_col]) else "Revolut payment"
            bal = clean_numeric_amount(r[bal_col]) if bal_col and not pd.isna(r[bal_col]) else None
            
            t_type = str(r[type_col]).strip().lower() if type_col and not pd.isna(r[type_col]) else ""
            desc_l = desc.lower()

            is_internal = (
                t_type == "exchange"
                or any(k in desc_l for k in [
                    "top up", "top-up", "ricarica", "transfer to", "transfer from",
                    "pocket", "vault", "exchanged to", "exchanged from",
                    "between your accounts", "giroconto",
                    "trasferimento interno", "internal transfer", "deposit by", "google pay deposit",
                    *owner_names(),
                ])
            )

            rows.append({
                "date": d,
                "amount": amount,
                "currency": "EUR",
                "description": desc,
                "counterparty": desc,
                "category": "Giroconto" if is_internal else ("Entrata" if amount > 0 else "Spesa"),
                "balance_after": bal,
                "is_internal_transfer": is_internal,
            })

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None
        end_bal = tx_df["balance_after"].dropna().iloc[-1] if not tx_df.empty and tx_df["balance_after"].notna().any() else float(tx_df["amount"].sum())

        return BankStatement(
            account_id="Revolut_Current",
            institution="Revolut",
            account_type="MultiCurrency",
            asset_class="LIQUID_CASH",
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=end_bal,
            transactions=tx_df,
            source_file=filename,
        )


# ============================================================
# PARSER 4.5: WALLET APP (BUDGETBAKERS / EXPENSE TRACKER CSV)
# ============================================================
class WalletAppParser(BaseBankParser):
    """
    Parser specializzato per file CSV esportati da 'Wallet' (BudgetBakers).
    Estrae le transazioni con le loro categorie dettagliate, metodi di pagamento
    (inclusi contanti CASH / Contanti), note e convenzione contabile standard.

    IMPORTANTE:
    Essendo un registro di spese e contanti (Expense Tracker) e NON un conto corrente bancario con debito,
    il suo saldo patrimoniale è impostato a 0.0 (asset_class='EXPENSE_TRACKER') per non alterare né sottrarre
    la liquidità reale dei conti bancari ufficiali.
    """
    INSTITUTION_NAME = "Wallet App (BudgetBakers)"
    DEFAULT_ASSET_CLASS = "EXPENSE_TRACKER"

    WALLET_CATEGORY_MAPPINGS = {
        "pub e ristoranti fuori": "Ristoranti & Svago",
        "deliveroo a casa": "Ristoranti & Svago",
        "ristoranti": "Ristoranti & Svago",
        "ristoranti & svago": "Ristoranti & Svago",
        "eating out": "Ristoranti & Svago",
        "drinking out": "Ristoranti & Svago",
        "bar": "Ristoranti & Svago",
        "caffetteria": "Ristoranti & Svago",
        "spesa": "Spesa & Alimentari",
        "drogheria, farmacia": "Spesa & Alimentari",
        "alimentari": "Spesa & Alimentari",
        "supermercato": "Spesa & Alimentari",
        "affitto": "Affitto",
        "energia, utenze": "Bollette & Utenze",
        "utenze": "Bollette & Utenze",
        "casa, giardino": "Casa & Arredo",
        "manutenzione, riparazioni": "Casa & Arredo",
        "salute": "Salute & Farmacia",
        "salute e bellezza": "Salute & Farmacia",
        "sport attivo, fitness": "Palestra & Sport",
        "fitness": "Palestra & Sport",
        "software, app, giochi": "Abbonamenti & IT",
        "libri, audio, abbonamenti": "Abbonamenti & IT",
        "tv, streaming": "Abbonamenti & IT",
        "trasporti": "Trasporti & Viaggi",
        "trasporto pubblico": "Trasporti & Viaggi",
        "lunga distanza": "Trasporti & Viaggi",
        "taxi": "Trasporti & Viaggi",
        "vacanze, viaggi, hotel": "Trasporti & Viaggi",
        "abbigliamento e scarpe": "Shopping & Abbigliamento",
        "shopping": "Shopping & Abbigliamento",
        "elettronica, accessori": "Shopping & Abbigliamento",
        "regali, piaceri": "Svago & Tempo Libero",
        "hobby": "Svago & Tempo Libero",
        "tempo libero": "Svago & Tempo Libero",
        "vita e intrattenimento": "Svago & Tempo Libero",
        "eventi della vita": "Svago & Tempo Libero",
        "alcol, tabacco": "Svago & Tempo Libero",
        "consulenza": "Servizi & Consulenze",
        "servizi": "Servizi & Consulenze",
    }

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False

        if isinstance(file_content, bytes):
            sample = _decode_text(file_content[:4096])
        else:
            sample = str(file_content)[:4096]

        sample_lower = sample.lower()

        # Firma univoca colonne Wallet (BudgetBakers)
        wallet_signatures = [
            "ref_currency_amount",
            "payment_type_local",
            "envelope_id",
            "warranty_in_month",
            "custom_category"
        ]
        if any(sig in sample_lower for sig in wallet_signatures):
            return True

        if "account" in sample_lower and "category" in sample_lower and "payment_type" in sample_lower:
            return True

        if "wallet" in fn and ("category" in sample_lower or "amount" in sample_lower):
            return True

        return False

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        if isinstance(file_content, bytes):
            text = _decode_text(file_content)
        else:
            text = str(file_content)

        # Rileva separatore (; o , o \t)
        first_line = text.split("\n")[0] if "\n" in text else text
        sep = ";" if ";" in first_line else ("," if "," in first_line else "\t")

        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, on_bad_lines="skip")
        except Exception:
            df = pd.read_csv(io.StringIO(text), on_bad_lines="skip")

        if df is None or df.empty or len(df.columns) == 0:
            return BankStatement(
                account_id="Wallet_App",
                institution=self.INSTITUTION_NAME,
                account_type="ExpenseTracker",
                asset_class=self.DEFAULT_ASSET_CLASS,
                currency="EUR",
                starting_balance=0.0,
                ending_balance=0.0,
                transactions=pd.DataFrame(),
                source_file=filename,
            )

        df = df.dropna(how="all").copy()
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Mappatura colonne chiave
        date_col = next((c for c in df.columns if c in ["date", "data", "datum"]), "date")
        amt_col = next((c for c in df.columns if c in ["ref_currency_amount", "amount", "importo"]), "amount")
        cat_col = next((c for c in df.columns if c in ["category", "categoria"]), "category")
        type_col = next((c for c in df.columns if c in ["type", "tipo"]), "type")
        ptype_col = next((c for c in df.columns if c in ["payment_type", "payment_type_local", "metodo_pagamento"]), "payment_type")
        ptype_loc_col = next((c for c in df.columns if c in ["payment_type_local"]), ptype_col)
        note_col = next((c for c in df.columns if c in ["note", "nota", "description", "descrizione"]), None)
        payee_col = next((c for c in df.columns if c in ["payee", "beneficiario"]), None)
        acc_col = next((c for c in df.columns if c in ["account", "conto"]), None)
        tr_col = next((c for c in df.columns if c in ["transfer", "trasferimento"]), None)

        rows = []
        for _, r in df.iterrows():
            d = parse_flexible_date(r[date_col]) if date_col in r and not pd.isna(r[date_col]) else None
            if d is None:
                continue

            raw_amt_str = str(r[amt_col]) if amt_col in r and not pd.isna(r[amt_col]) else "0"
            amt = clean_numeric_amount(raw_amt_str)

            # Riconoscimento tipo operazione
            t_val = str(r.get(type_col, "")).strip().lower()
            if t_val in ["spese", "expense", "debit", "uscita"] and amt > 0:
                amt = -amt
            elif t_val in ["entrate", "income", "credit", "accredito"] and amt < 0:
                amt = abs(amt)

            # Controllo trasferimenti interni tra buste/conti di Wallet
            is_internal = False
            if tr_col in r and str(r[tr_col]).strip().lower() in ["true", "1", "yes"]:
                is_internal = True
            if t_val in ["transfer", "trasferimento"]:
                is_internal = True

            wallet_cat = str(r.get(cat_col, "")).strip() if cat_col in r and not pd.isna(r[cat_col]) else "Varie"
            mapped_cat = self.WALLET_CATEGORY_MAPPINGS.get(wallet_cat.lower(), wallet_cat)

            ptype = str(r.get(ptype_col, "OTHER")).strip().upper() if ptype_col in r and not pd.isna(r[ptype_col]) else "OTHER"
            ptype_loc = str(r.get(ptype_loc_col, "")).strip() if ptype_loc_col in r and not pd.isna(r[ptype_loc_col]) else ptype
            is_cash = (ptype == "CASH" or "contanti" in ptype_loc.lower())

            note_val = str(r[note_col]).strip() if note_col and note_col in r and not pd.isna(r[note_col]) else ""
            payee_val = str(r[payee_col]).strip() if payee_col and payee_col in r and not pd.isna(r[payee_col]) else ""

            # Descrizione parlante
            if payee_val and note_val:
                desc = f"{payee_val} — {note_val}"
            elif payee_val:
                desc = payee_val
            elif note_val:
                desc = f"{wallet_cat} — {note_val}"
            else:
                desc = f"[{ptype_loc or ptype}] {wallet_cat}"

            rows.append({
                "date": d,
                "amount": amt,
                "currency": "EUR",
                "description": desc,
                "counterparty": payee_val or desc,
                "category": "Giroconto" if is_internal else mapped_cat,
                "wallet_category": wallet_cat,
                "payment_type": ptype,
                "payment_type_local": ptype_loc,
                "is_cash": is_cash,
                "balance_after": None,
                "is_internal_transfer": is_internal,
                "source_type": "wallet_app",
            })

        tx_df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None

        # Statistiche interne al file
        debits = tx_df[tx_df["amount"] < 0]
        credits = tx_df[tx_df["amount"] > 0]
        cash_debits = debits[debits["is_cash"]] if not debits.empty and "is_cash" in debits.columns else pd.DataFrame()
        elec_debits = debits[~debits["is_cash"]] if not debits.empty and "is_cash" in debits.columns else debits

        tot_expenses = float(abs(debits["amount"].sum())) if not debits.empty else 0.0
        tot_cash_exp = float(abs(cash_debits["amount"].sum())) if not cash_debits.empty else 0.0
        tot_elec_exp = float(abs(elec_debits["amount"].sum())) if not elec_debits.empty else 0.0

        meta = {
            "is_expense_tracker": True,
            "total_expenses_tracked": tot_expenses,
            "total_inflows_tracked": float(credits["amount"].sum()) if not credits.empty else 0.0,
            "cash_expenses_total": tot_cash_exp,
            "electronic_expenses_total": tot_elec_exp,
            "cash_ratio_pct": (tot_cash_exp / tot_expenses * 100.0) if tot_expenses > 0 else 0.0,
            "tracked_transactions_count": len(tx_df),
            "cash_transactions_count": int(tx_df["is_cash"].sum()) if not tx_df.empty and "is_cash" in tx_df.columns else 0,
            "top_wallet_categories": debits.groupby("wallet_category")["amount"].agg(lambda s: float(abs(s.sum()))).to_dict() if not debits.empty else {},
        }

        # Determinazione nome conto
        orig_acc = "Budget"
        if acc_col and acc_col in df.columns:
            non_empty_acc = df[acc_col].dropna()
            if not non_empty_acc.empty:
                orig_acc = str(non_empty_acc.iloc[0]).strip()

        return BankStatement(
            account_id=f"Wallet_{orig_acc.replace(' ', '_')}",
            institution=self.INSTITUTION_NAME,
            account_type="ExpenseTracker",
            asset_class=self.DEFAULT_ASSET_CLASS,
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=0.0,  # FONDAMENTALE: zero impatto sul saldo dei conti bancari reali
            transactions=tx_df,
            source_file=filename,
            metadata=meta,
        )


# ============================================================
# PARSER 5: GENERIC HEURISTIC PARSER (CSV, EXCEL & PDF)
# ============================================================
class GenericBankParser(BaseBankParser):
    """
    Parser di fallback euristico che si adatta a qualunque file bancario
    CSV, TSV, Excel (.xlsx, .xls) o PDF.
    """
    INSTITUTION_NAME = "Conto Generico"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        return True  # Fallback universale

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        ext = Path(filename).suffix.lower()

        if ext in [".xlsx", ".xls"]:
            # Lettura Excel
            if isinstance(file_content, str):
                df = pd.read_excel(file_content)
            else:
                df = pd.read_excel(io.BytesIO(file_content))
            return self._parse_dataframe(df, filename)

        elif ext == ".pdf":
            # Estrazione da PDF
            return self._parse_pdf(file_content, filename)

        else:
            # Lettura CSV/TSV
            if isinstance(file_content, bytes):
                text = _decode_text(file_content)
            else:
                text = str(file_content)

            if not text or not text.strip():
                return self._parse_dataframe(pd.DataFrame(), filename)

            df = None
            for sep in [",", ";", "\t", "|"]:
                for skip in [0, 1, 2, 3, 5, 8]:
                    try:
                        temp = pd.read_csv(io.StringIO(text), sep=sep, skiprows=skip, on_bad_lines='skip')
                        if len(temp.columns) >= 2 and len(temp) > 0:
                            # Controlla che vi sia una colonna plausibile per la data
                            has_date = any(
                                any(k in str(c).lower() for k in ["data", "date", "datum", "time", "giorno"])
                                for c in temp.columns
                            )
                            if has_date:
                                df = temp
                                break
                    except Exception:
                        continue
                if df is not None:
                    break

            if df is None:
                # Tenta lettura base senza skiprows
                try:
                    df = pd.read_csv(io.StringIO(text), on_bad_lines='skip')
                except Exception:
                    df = pd.DataFrame()

            return self._parse_dataframe(df, filename)

    def _parse_dataframe(self, df: pd.DataFrame, filename: str) -> BankStatement:
        if df is None or df.empty or len(df.columns) == 0:
            return BankStatement(
                account_id=f"GEN_{Path(filename).stem}",
                institution="Generic",
                account_type="Checking",
                asset_class="LIQUID_CASH",
                currency="EUR",
                starting_balance=0.0,
                ending_balance=0.0,
                transactions=pd.DataFrame(columns=["date", "amount", "description", "category", "account_id", "institution"]),
                source_file=filename,
            )

        df = df.dropna(how="all").copy()
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Rilevamento colonne data
        date_candidates = [c for c in df.columns if any(k in c for k in ["data", "date", "datum", "giorno", "time"])]
        date_col = date_candidates[0] if date_candidates else df.columns[0]

        # Rilevamento colonne importo
        amt_candidates = [c for c in df.columns if any(k in c for k in ["importo", "amount", "betrag", "valore", "wert", "value", "prezzo", "totale"])]
        amt_col = amt_candidates[0] if amt_candidates else None

        # Rilevamento entrate / uscite
        in_col = next((c for c in df.columns if any(k in c for k in ["entrate", "avere", "accredito", "in", "credit"])), None)
        out_col = next((c for c in df.columns if any(k in c for k in ["uscite", "dare", "addebito", "out", "debit"])), None)

        # Rilevamento descrizione
        desc_candidates = [c for c in df.columns if any(k in c for k in ["descrizione", "causale", "description", "testo", "dettaglio", "partner", "payee"])]
        desc_col = desc_candidates[0] if desc_candidates else None

        # Rilevamento saldo
        bal_candidates = [c for c in df.columns if any(k in c for k in ["saldo", "balance", "kontostand", "totale"])]
        bal_col = bal_candidates[0] if bal_candidates else None

        rows = []
        for _, r in df.iterrows():
            d = parse_flexible_date(r[date_col])
            if d is None:
                continue

            if amt_col:
                amount = clean_numeric_amount(r[amt_col])
            elif in_col and out_col:
                v_in = clean_numeric_amount(r[in_col])
                v_out = clean_numeric_amount(r[out_col])
                amount = v_in if v_in != 0 else -abs(v_out)
            else:
                # Tenta prima colonna numerica
                amount = 0.0

            desc = str(r[desc_col]).strip() if desc_col and not pd.isna(r[desc_col]) else "Movimento Bancario"
            bal = clean_numeric_amount(r[bal_col]) if bal_col and not pd.isna(r[bal_col]) else None

            is_internal = any(k in desc.lower() for k in ["giroconto", "trasferimento interno", "trade republic", "revolut"])

            rows.append({
                "date": d,
                "amount": amount,
                "currency": "EUR",
                "description": desc,
                "counterparty": desc,
                "category": "Giroconto" if is_internal else ("Entrata" if amount > 0 else "Uscita"),
                "balance_after": bal,
                "is_internal_transfer": is_internal,
            })

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None
        end_bal = tx_df["balance_after"].dropna().iloc[-1] if not tx_df.empty and tx_df["balance_after"].notna().any() else float(tx_df["amount"].sum())

        # Asset class euristica dal nome del file
        fn_l = filename.lower()
        if any(k in fn_l for k in ["invest", "etf", "broker", "titoli", "deposito"]):
            asset_cls = "INVESTMENTS"
            acc_type = "Brokerage"
        elif any(k in fn_l for k in ["republic", "deposito", "savings", "remunerat"]):
            asset_cls = "HIGH_YIELD_CASH"
            acc_type = "HighYieldCash"
        else:
            asset_cls = "LIQUID_CASH"
            acc_type = "Checking"

        return BankStatement(
            account_id=Path(filename).stem.replace(" ", "_"),
            institution="Banca / Istituto Riconosciuto",
            account_type=acc_type,
            asset_class=asset_cls,
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=end_bal,
            transactions=tx_df,
            source_file=filename,
        )

    def _parse_pdf(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        """Delega a PdfBankParser per l'elaborazione dei PDF."""
        return PdfBankParser().parse(file_content, filename)


# ============================================================
# PARSER SPECIALIZZATO: PDF BANK STATEMENTS
# ============================================================
class PdfBankParser(BaseBankParser):
    """
    Parser universale avanzato per estratti conto bancari in formato PDF.
    Utilizza pdfplumber per estrarre tabelle strutturate e layout di testo,
    con fallback su pypdf e scanner euristico regex avanzato.
    Supporta: Erste Bank/George, Trade Republic, Revolut, UniCredit, Intesa Sanpaolo,
    Fineco, N26, Deutsche Bank, Poste Italiane, ecc.
    """
    INSTITUTION_NAME = "Estratto Conto PDF"
    DEFAULT_ASSET_CLASS = "LIQUID_CASH"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf"):
            return True
        if isinstance(file_content, bytes) and file_content.startswith(b"%PDF"):
            return True
        return False

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        pdf_bytes = None
        if isinstance(file_content, (str, Path)) and os.path.exists(file_content):
            with open(file_content, "rb") as f:
                pdf_bytes = f.read()
        elif isinstance(file_content, bytes):
            pdf_bytes = file_content
        elif isinstance(file_content, str):
            pdf_bytes = file_content.encode("latin-1", errors="ignore")

        if not pdf_bytes:
            raise ValueError(f"File PDF vuoto o non accessibile: {filename}")

        full_text = ""
        extracted_tables = []

        # 1. Estrazione con pdfplumber (preferito per layout e tabelle)
        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    for page in pdf.pages:
                        page_tables = page.extract_tables() or []
                        if not page_tables:
                            page_tables = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"}) or []
                        for t in page_tables:
                            if t and len(t) > 1:
                                extracted_tables.append(t)
                        t_text = page.extract_text(layout=False) or ""
                        full_text += t_text + "\n"
            except Exception:
                pass

        # 2. Integrazione o fallback con pypdf
        if (not full_text.strip() or not HAS_PDFPLUMBER) and HAS_PYPDF:
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    t_text = page.extract_text() or ""
                    full_text += t_text + "\n"
            except Exception:
                pass

        # Rilevamento prioritario istituto bancario (dall'intestazione o nome file)
        header_text = (filename + " " + full_text[:2500]).lower()
        inst_name = "Estratto Conto PDF"
        if "trade republic" in header_text or "trade_republic" in header_text or "traderepublic" in header_text or ("account" in filename.lower() and "trade" in filename.lower()):
            inst_name = "Trade Republic"
        elif "unicredit" in header_text:
            inst_name = "UniCredit"
        elif "intesa" in header_text or "sanpaolo" in header_text:
            inst_name = "Intesa Sanpaolo"
        elif "fineco" in header_text:
            inst_name = "FinecoBank"
        elif re.search(r"\berste\s+bank\b|\bsparkasse\b|\bgeorge\b", header_text):
            inst_name = "Erste Bank / Sparkasse"
        elif "revolut" in header_text:
            inst_name = "Revolut"
        elif "n26" in header_text:
            inst_name = "N26"
        elif "poste" in header_text or "bancoposta" in header_text:
            inst_name = "Poste Italiane"
        elif "mediolanum" in header_text:
            inst_name = "Banca Mediolanum"
        elif "widiba" in header_text:
            inst_name = "Banca Widiba"
        elif "deutsche bank" in header_text:
            inst_name = "Deutsche Bank"
        elif "ing direct" in header_text or "ing bank" in header_text:
            inst_name = "ING"

        # Se il documento è un estratto conto Trade Republic, usa il parser dedicato ad alta fedeltà
        if inst_name == "Trade Republic":
            return self._parse_trade_republic_pdf(full_text, filename)

        rows = []
        seen_keys = set()

        # FASE A: Estrazione da tabelle strutturate (pdfplumber)
        for table in extracted_tables:
            if not table or len(table) < 2:
                continue

            header_idx = -1
            date_col = -1
            desc_col = -1
            amt_col = -1
            in_col = -1
            out_col = -1
            bal_col = -1

            for r_i, r in enumerate(table[:3]):
                r_cells = [str(c or "").lower().strip() for c in r]
                has_d = any(any(k in c for k in ["data", "date", "datum"]) for c in r_cells)
                has_a = any(any(k in c for k in ["importo", "amount", "betrag", "entrate", "uscite", "soll", "haben", "valore"]) for c in r_cells)
                if has_d or has_a:
                    header_idx = r_i
                    for c_i, c in enumerate(r_cells):
                        if any(k in c for k in ["data", "date", "datum", "buchung", "valuta"]) and date_col == -1:
                            date_col = c_i
                        elif any(k in c for k in ["descrizione", "causale", "buchungstext", "partner", "payee", "description", "verwendungszweck", "dettaglio", "text"]) and desc_col == -1:
                            desc_col = c_i
                        elif any(k in c for k in ["entrate", "accrediti", "money in", "credit", "haben"]) and not any(k in c for k in ["uscite", "addebiti"]):
                            in_col = c_i
                        elif any(k in c for k in ["uscite", "addebiti", "money out", "debit", "soll"]) and not any(k in c for k in ["entrate", "accrediti"]):
                            out_col = c_i
                        elif any(k in c for k in ["importo", "amount", "betrag", "valore", "entrate", "uscite"]) and amt_col == -1:
                            amt_col = c_i
                        elif any(k in c for k in ["saldo", "balance", "kontostand"]) and bal_col == -1:
                            bal_col = c_i
                    break

            start_row = header_idx + 1 if header_idx >= 0 else 0
            for row in table[start_row:]:
                if not row or len(row) < 2:
                    continue
                d = None
                d_idx = date_col if date_col != -1 else None
                if d_idx is not None and d_idx < len(row):
                    d = parse_flexible_date(row[d_idx])
                if d is None:
                    for c_i, cell in enumerate(row):
                        parsed_d = parse_flexible_date(cell)
                        if parsed_d is not None:
                            d = parsed_d
                            if date_col == -1:
                                date_col = c_i
                            break

                if d is None:
                    continue

                amt = 0.0
                if in_col != -1 and out_col != -1 and in_col != out_col and in_col < len(row) and out_col < len(row):
                    v_in = clean_numeric_amount(row[in_col])
                    v_out = clean_numeric_amount(row[out_col])
                    amt = v_in if v_in != 0 else -abs(v_out)
                elif amt_col != -1 and amt_col < len(row):
                    amt = clean_numeric_amount(row[amt_col])
                else:
                    for c_i, cell in enumerate(row):
                        if c_i == date_col:
                            continue
                        val = clean_numeric_amount(cell)
                        if val != 0.0:
                            amt = val
                            break

                if amt == 0.0:
                    continue

                desc = ""
                if desc_col != -1 and desc_col < len(row) and row[desc_col]:
                    desc = str(row[desc_col]).strip()
                else:
                    other_cells = [str(c).strip() for c_i, c in enumerate(row) if c_i not in (date_col, amt_col, in_col, out_col, bal_col) and str(c or "").strip()]
                    desc = " - ".join(other_cells) if other_cells else f"Movimento {inst_name}"

                desc_l = desc.lower()
                if amt > 0 and any(w in desc_l for w in ["addebito", "rid", "spesa", "pagamento", "prelievo", "giroconto verso", "commission", "uscita"]) and not any(w in desc_l for w in ["stipendio", "accredito", "salary", "rimborso", "entrata"]):
                    amt = -abs(amt)

                key = (d, round(amt, 2), desc[:25].lower())
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                is_internal = any(k in desc.lower() for k in ["giroconto", "trasferimento interno", "internal transfer", "own account", "trade republic", "revolut", "ricarica", "top up"])
                rows.append({
                    "date": d,
                    "amount": amt,
                    "currency": "EUR",
                    "description": desc,
                    "counterparty": desc,
                    "category": "Giroconto" if is_internal else ("Entrata" if amt > 0 else "Uscita"),
                    "is_internal_transfer": is_internal,
                })

        # FASE B: Estrazione da testo (se tabelle non hanno prodotto righe)
        if len(rows) == 0 and full_text.strip():
            # Pattern con due importi (Importo transazione + Saldo a fine riga)
            pat_double_amt = re.compile(
                r"^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(?:(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+)?(.+?)\s+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)\s+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)\s*(?:€|EUR|USD|\b)?$",
                re.IGNORECASE
            )

            # Pattern standard con singolo importo a fine riga
            text_patterns = [
                # 1. Standard Europeo: 15.09.2026 [16.09.2026] Testo causale -120,50 EUR
                re.compile(r"^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(?:(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+)?(.+?)\s+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)\s*(?:€|EUR|USD|\b)?$", re.IGNORECASE),
                # 2. Revolut / Inglese: 15 Sep 2026 Description -120.50 EUR
                re.compile(r"^(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\s+(.+?)\s+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)\s*(?:€|EUR|USD|\b)?$", re.IGNORECASE),
                # 3. ISO Date: 2026-09-15 Description -120.50
                re.compile(r"^(\d{4}[./-]\d{1,2}[./-]\d{1,2})\s+(.+?)\s+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)\s*(?:€|EUR|USD|\b)?$", re.IGNORECASE),
            ]

            for raw_line in full_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                matched = False
                # Prova prima pattern a doppio importo (Data, Causale, Movimento, Saldo)
                m_double = pat_double_amt.match(line)
                if m_double:
                    raw_date, raw_desc, raw_amt, raw_bal = m_double.groups()
                    d = parse_flexible_date(raw_date)
                    if d is not None:
                        amt = clean_numeric_amount(raw_amt)
                        bal_after = clean_numeric_amount(raw_bal)
                        clean_desc = raw_desc.strip()
                        clean_desc = re.sub(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+", "", clean_desc).strip()

                        # Se l'importo è positivo ma la causale è chiaramente un addebito
                        desc_l = clean_desc.lower()
                        if amt > 0 and any(w in desc_l for w in ["addebito", "rid", "spesa", "pagamento", "prelievo", "giroconto verso", "commission"]) and not any(w in desc_l for w in ["stipendio", "accredito", "salary", "rimborso"]):
                            amt = -abs(amt)

                        key = (d, round(amt, 2), clean_desc[:25].lower())
                        if key not in seen_keys:
                            seen_keys.add(key)
                            is_internal = any(k in desc_l for k in ["giroconto", "trasferimento interno", "internal transfer", "own account", "trade republic", "revolut", "ricarica", "top up"])
                            rows.append({
                                "date": d,
                                "amount": amt,
                                "currency": "EUR",
                                "description": clean_desc,
                                "counterparty": clean_desc,
                                "category": "Giroconto" if is_internal else ("Entrata" if amt > 0 else "Uscita"),
                                "balance_after": bal_after,
                                "is_internal_transfer": is_internal,
                            })
                            matched = True

                if not matched:
                    for pat in text_patterns:
                        m = pat.match(line)
                        if m:
                            raw_date, raw_desc, raw_amt = m.groups()
                            d = parse_flexible_date(raw_date)
                            if d is None:
                                continue
                            amt = clean_numeric_amount(raw_amt)
                            if amt == 0.0:
                                continue
                            clean_desc = raw_desc.strip()
                            clean_desc = re.sub(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+", "", clean_desc).strip()

                            desc_l = clean_desc.lower()
                            if amt > 0 and any(w in desc_l for w in ["addebito", "rid", "spesa", "pagamento", "prelievo", "giroconto verso", "commission"]) and not any(w in desc_l for w in ["stipendio", "accredito", "salary", "rimborso"]):
                                amt = -abs(amt)

                            key = (d, round(amt, 2), clean_desc[:25].lower())
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)

                            is_internal = any(k in desc_l for k in ["giroconto", "trasferimento interno", "internal transfer", "own account", "trade republic", "revolut", "ricarica", "top up"])
                            rows.append({
                                "date": d,
                                "amount": amt,
                                "currency": "EUR",
                                "description": clean_desc,
                                "counterparty": clean_desc,
                                "category": "Giroconto" if is_internal else ("Entrata" if amt > 0 else "Uscita"),
                                "is_internal_transfer": is_internal,
                            })
                            break

        tx_df = pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()
        s_date = tx_df["date"].min() if not tx_df.empty else None
        e_date = tx_df["date"].max() if not tx_df.empty else None

        # Ricerca del saldo finale nel testo
        end_bal = None
        bal_match = re.search(
            r"(?:saldo\s+(?:finale|contabile|al|disponibile|nuovo)|closing\s+balance|ending\s+balance|final\s+balance|schlusssaldo|endstand|alter\s+kontostand|neuer\s+kontostand)[:\s]+([+-]?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*(?:[-+]|[SH]|DR|CR)?)",
            full_text,
            re.IGNORECASE
        )
        if bal_match:
            end_bal = clean_numeric_amount(bal_match.group(1))
        elif not tx_df.empty:
            end_bal = float(tx_df["amount"].sum())

        fn_l = filename.lower()
        if any(k in fn_l for k in ["broker", "titoli", "invest", "portfolio", "deposito titoli", "wertpapier"]):
            asset_cls = "INVESTMENTS"
            acc_type = "Brokerage"
        elif any(k in fn_l for k in ["savings", "deposito", "remunerat", "tagesgeld"]):
            asset_cls = "HIGH_YIELD_CASH"
            acc_type = "HighYieldCash"
        elif "trade republic" in inst_name.lower():
            asset_cls = "HIGH_YIELD_CASH"
            acc_type = "HighYieldCash"
        else:
            asset_cls = "LIQUID_CASH"
            acc_type = "Checking"

        return BankStatement(
            account_id=f"PDF_{Path(filename).stem.replace(' ', '_')}",
            institution=inst_name,
            account_type=acc_type,
            asset_class=asset_cls,
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=end_bal or 0.0,
            transactions=tx_df,
            source_file=filename,
            metadata={"raw_text_length": len(full_text), "tables_found": len(extracted_tables)}
        )

    def _parse_trade_republic_pdf(self, full_text: str, filename: str) -> BankStatement:
        """
        Parser dedicato ad alta precisione per estratti conto Trade Republic (Austria, Germania, Italia, Francia, Internazionali).
        Supporta estrazione bilingue/multilingua di date, tipi operazione, partner bancari custodi e saldi finali.
        """
        MONTH_TR_MAP = {
            # Tedesco / Austriaco
            'jän': '01', 'jänner': '01', 'jan': '01', 'januar': '01',
            'feb': '02', 'februar': '02',
            'mär': '03', 'märz': '03',
            'apr': '04', 'april': '04',
            'mai': '05',
            'jun': '06', 'juni': '06',
            'jul': '07', 'juli': '07',
            'aug': '08', 'august': '08',
            'sep': '09', 'sept': '09', 'september': '09',
            'okt': '10', 'oktober': '10',
            'nov': '11', 'november': '11',
            'dez': '12', 'dezember': '12',
            # Italiano
            'gen': '01', 'gennaio': '01',
            'febbraio': '02',
            'marzo': '03',
            'aprile': '04',
            'mag': '05', 'maggio': '05',
            'giu': '06', 'giugno': '06',
            'lug': '07', 'luglio': '07',
            'ago': '08', 'agosto': '08',
            'set': '09', 'settembre': '09',
            'ott': '10', 'ottobre': '10',
            'novembre': '11',
            'dic': '12', 'dicembre': '12',
            # Inglese
            'january': '01',
            'february': '02',
            'march': '03',
            'may': '05',
            'june': '06',
            'july': '07',
            'october': '10', 'oct': '10',
            'december': '12', 'dec': '12',
            # Francese
            'janv': '01', 'janvier': '01',
            'févr': '02', 'février': '02',
            'mars': '03',
            'avril': '04',
            'juin': '06',
            'juil': '07', 'juillet': '07',
            'août': '08',
            'déc': '12', 'décembre': '12',
        }

        month_pattern = re.compile(
            r'\b(' + '|'.join(sorted(MONTH_TR_MAP.keys(), key=len, reverse=True)) + r')\.?\b',
            re.IGNORECASE
        )

        # Ricerca anno di riferimento (es. 01 Jän. 2026 - 09 Okt. 2026 oppure 01/01/2026 - 31/10/2026)
        m_year = re.search(r'(\d{4})\s+-\s+\d{1,2}\s+[A-Za-zäöüÄÖÜ.]+\s+(\d{4})', full_text)
        if not m_year:
            m_year = re.search(r'\b(202\d)\b', full_text)
            current_year = m_year.group(1) if m_year else str(pd.Timestamp.now().year)
        else:
            current_year = m_year.group(2)

        # Ricerca dell'Endsaldo / Saldo Finale ufficiale dal documento
        end_bal = None
        m_endsaldo = re.search(r'Cashkonto\s+€\s*[\d.,]+\s+€\s*[\d.,]+\s+€\s*[\d.,]+\s+€\s*([\d.,]+)', full_text)
        if not m_endsaldo:
            m_endsaldo = re.search(r'(?:ENDSALDO|SALDO\s+FINALE|CLOSING\s+BALANCE|SOLDE\s+FINAL)\s*\n.*?€\s*([\d.,]+)', full_text, re.DOTALL | re.IGNORECASE)
        if not m_endsaldo:
            # Ricerca conti di deposito fiduciari (HSBC, Deutsche Bank, J.P. Morgan, Citibank, Solaris)
            m_endsaldo = re.search(r'(?:HSBC|Deutsche\s+Bank|J\.?P\.?\s*Morgan|Citibank|Solaris(?:bank)?)\s+€\s*([\d.,]+)', full_text, re.IGNORECASE)
        if not m_endsaldo:
            m_endsaldo = re.search(r'(?:Saldo\s+contabile\s+finale|Saldo\s+al\s+\d{1,2}[./]\d{1,2}[./]\d{4})\s*[:\s]+€?\s*([\d.,]+)', full_text, re.IGNORECASE)
        if m_endsaldo:
            end_bal = clean_numeric_amount(m_endsaldo.group(1))

        # Pattern riga transazione Trade Republic: <Prefix> € <Amount> € <Saldo>
        tx_pattern = re.compile(r'^(.*?)\s+€\s*([\d.,]+)\s+€\s*([\d.,]+)$')

        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        rows = []
        prev_balance = None
        current_day = '01'
        current_month = '01'
        tx_year = current_year

        for i, l in enumerate(lines):
            # 1. Rilevamento data combinata giorno + mese sulla stessa riga (es. '14 Juli', '01 Jän.', '15 Maggio')
            dm_match = re.match(r'^(\d{1,2})\s+([A-Za-zäöüÄÖÜ.]+)', l)
            if dm_match:
                d_val = dm_match.group(1).zfill(2)
                m_word = dm_match.group(2).lower().rstrip('.')
                if m_word in MONTH_TR_MAP:
                    current_day = d_val
                    current_month = MONTH_TR_MAP[m_word]
            elif re.match(r'^\d{1,2}$', l) and 1 <= int(l) <= 31:
                current_day = l.zfill(2)

            # 2. Rilevamento mese isolato o all'interno della riga
            m_found = month_pattern.search(l)
            if m_found:
                w = m_found.group(1).lower().rstrip('.')
                if w in MONTH_TR_MAP:
                    current_month = MONTH_TR_MAP[w]

            # 3. Rilevamento anno se specificato
            if re.match(r'^(202\d)$', l):
                tx_year = l

            m = tx_pattern.match(l)
            if m:
                prefix, amt_str, bal_str = m.groups()
                if any(k in prefix.lower() for k in ['cashkonto', 'anfangssaldo', 'produkt', 'kontouebersicht', 'saldo iniziale']):
                    continue

                bal_after = clean_numeric_amount(bal_str)
                raw_amt = clean_numeric_amount(amt_str)
                if raw_amt == 0.0:
                    continue

                # Controllo se il prefisso stesso contiene indicazioni su giorno o mese
                dm_p = re.match(r'^(\d{1,2})\s+([A-Za-zäöüÄÖÜ.]+)', prefix)
                if dm_p:
                    d_p = dm_p.group(1).zfill(2)
                    m_p = dm_p.group(2).lower().rstrip('.')
                    if m_p in MONTH_TR_MAP:
                        current_day = d_p
                        current_month = MONTH_TR_MAP[m_p]
                else:
                    p_found = month_pattern.search(prefix)
                    if p_found and p_found.group(1).lower().rstrip('.') in MONTH_TR_MAP:
                        current_month = MONTH_TR_MAP[p_found.group(1).lower().rstrip('.')]

                # Cerca anno nelle righe adiacenti
                for near_l in lines[max(0, i-2):min(len(lines), i+3)]:
                    m_y = re.match(r'^(202\d)$', near_l)
                    if m_y:
                        tx_year = m_y.group(1)
                        break

                try:
                    # Validazione e clamping data
                    day_int = max(1, min(int(current_day), 31))
                    month_int = max(1, min(int(current_month), 12))
                    # Normalizza giorni dei mesi più corti (es. febbraio)
                    if month_int == 2 and day_int > 28:
                        is_leap = (int(tx_year) % 4 == 0 and (int(tx_year) % 100 != 0 or int(tx_year) % 400 == 0))
                        day_int = 29 if is_leap else 28
                    elif month_int in [4, 6, 9, 11] and day_int > 30:
                        day_int = 30
                    date_val = pd.to_datetime(f"{tx_year}-{month_int:02d}-{day_int:02d}").normalize()
                except Exception:
                    date_val = pd.Timestamp.now().normalize()

                # Calcolo segno matematico esatto dal delta del saldo
                if prev_balance is not None:
                    delta = round(bal_after - prev_balance, 2)
                    if abs(delta) > 0 and abs(abs(delta) - raw_amt) < 0.05:
                        real_amt = delta
                    elif any(k in prefix.lower() for k in ['kartentransaktion', 'gebühr', 'sparplan', 'auszahlung', 'sepa-lastschrift', 'card', 'spesa']):
                        real_amt = -abs(raw_amt)
                    elif any(k in prefix.lower() for k in ['überweisung', 'transfer']) and i > 0 and any(k in lines[i-1].lower() for k in ['incoming', 'entrata', 'einzahlung']):
                        real_amt = abs(raw_amt)
                    elif any(k in prefix.lower() for k in ['zinsen', 'bonus', 'saveback', 'interest', 'interessi']):
                        real_amt = abs(raw_amt)
                    else:
                        real_amt = -abs(raw_amt) if bal_after < prev_balance else abs(raw_amt)
                else:
                    real_amt = -abs(raw_amt)

                prev_balance = bal_after

                # Composizione descrizione pulita
                desc_parts = []
                prev_l = lines[i-1] if i > 0 else ''
                if not re.match(r'^\d{1,2}$', prev_l) and not re.match(r'^(202\d)$', prev_l) and not any(k in prev_l.upper() for k in ['TRADE REPUBLIC', 'DATUM TYP', 'KONTOÜBERSICHT']):
                    desc_parts.append(prev_l)

                clean_prefix = re.sub(r'^[A-Za-zäöüÄÖÜ.]+\s+', '', prefix).strip()
                desc_parts.append(clean_prefix)
                full_desc = ' - '.join(desc_parts)

                # Categorizzazione accurata multilingua
                cat = "Altro"
                desc_l = full_desc.lower()
                is_internal = False

                if any(k in desc_l for k in ['zinsen', 'interest', 'saveback', 'bonus', 'interessi', 'intérêts']):
                    cat = "Interessi Attivi"
                elif any(k in desc_l for k in ['sparplan', 'handel', 'buy trade', 'vanguard', 'etf', 'amundi', 'shares', 'azioni', 'pac', 'ordine']):
                    cat = "Investimento ETF / Azioni"
                elif any(k in desc_l for k in ['incoming transfer', 'deposit', 'einzahlung', 'giroconto', 'bonifico in entrata', 'virement entrant']):
                    cat = "Giroconto Entrata"
                    is_internal = True
                elif any(k in desc_l for k in ['outgoing transfer', 'auszahlung', 'revolut', 'bonifico in uscita', 'virement sortant']):
                    cat = "Giroconto Uscita"
                    is_internal = True
                elif any(k in desc_l for k in ['kartentransaktion', 'card transaction', 'operazione carta', 'carta']):
                    cat = "Spesa Carta"
                elif any(k in desc_l for k in ['sepa-lastschrift', 'direct debit', 'addebito diretto']):
                    cat = "Bollette & Utenze"

                rows.append({
                    'date': date_val,
                    'amount': real_amt,
                    'currency': 'EUR',
                    'description': full_desc,
                    'counterparty': 'Trade Republic',
                    'category': cat,
                    'balance_after': bal_after,
                    'is_internal_transfer': is_internal
                })

        tx_df = pd.DataFrame(rows).sort_values('date') if rows else pd.DataFrame()
        s_date = tx_df['date'].min() if not tx_df.empty else None
        e_date = tx_df['date'].max() if not tx_df.empty else None

        if end_bal is None and not tx_df.empty and 'balance_after' in tx_df.columns:
            end_bal = float(tx_df['balance_after'].iloc[-1])

        return BankStatement(
            account_id="Trade_Republic_Cash",
            institution="Trade Republic",
            account_type="HighYieldCash",
            asset_class="HIGH_YIELD_CASH",
            currency="EUR",
            start_date=s_date,
            end_date=e_date,
            starting_balance=0.0,
            ending_balance=end_bal or 0.0,
            transactions=tx_df,
            source_file=filename,
            metadata={"total_transactions": len(tx_df), "platform": "Trade Republic PDF"}
        )


# ============================================================
# PARSER SPECIALIZZATO: PORTAFOGLIO INVESTIMENTI & LISTA ETF
# ============================================================
class InvestmentPortfolioParser(BaseBankParser):
    """
    Parser per portafogli titoli, liste di ETF e asset azionari/obbligazionari.
    Supporta esportazioni da broker (Scalable, Trade Republic Securities, Degiro,
    Interactive Brokers, Directa, Fineco) o elenchi personalizzati CSV/Excel/JSON.
    Riconosce colonne: Ticker, ISIN, Quote/Shares, Prezzo Acquisto, Prezzo Attuale,
    Controvalore/Market Value, P&L.
    """
    INSTITUTION_NAME = "Portafoglio ETF & Titoli"
    DEFAULT_ASSET_CLASS = "INVESTMENTS"

    def can_parse(self, file_content: Union[str, bytes], filename: str) -> bool:
        fn = filename.lower()
        if fn.endswith(".pdf") or (isinstance(file_content, bytes) and file_content.startswith(b"%PDF")):
            return False
        if any(k in fn for k in ["etf", "portfolio", "titoli", "holdings", "invest", "depot", "broker", "scalable", "degiro", "directa"]):
            return True
        try:
            sample = _decode_text(file_content[:4096]) if isinstance(file_content, bytes) else str(file_content)[:4096]
            sample_low = sample.lower()
            investment_terms = ["ticker", "isin", "shares", "quote", "quantita", "quantità", "market_value", "controvalore", "cost_basis", "prezzo_carico", "prezzo medio", "asset_class"]
            matches = sum(1 for term in investment_terms if term in sample_low)
            return matches >= 2
        except Exception:
            return False

    def parse(self, file_content: Union[str, bytes], filename: str) -> BankStatement:
        fn = filename.lower()
        df = None

        # 1. Lettura file in DataFrame
        if fn.endswith((".xlsx", ".xls")):
            buf = io.BytesIO(file_content) if isinstance(file_content, bytes) else file_content
            try:
                df = pd.read_excel(buf)
            except Exception as e:
                raise ValueError(f"Impossibile leggere file Excel portafoglio {filename}: {e}")
        else:
            text = _decode_text(file_content) if isinstance(file_content, bytes) else str(file_content)
            for sep in [",", ";", "\t", "|"]:
                try:
                    temp_df = pd.read_csv(io.StringIO(text), sep=sep, comment="#")
                    if len(temp_df.columns) >= 2 and len(temp_df) > 0:
                        df = temp_df
                        break
                except Exception:
                    continue

        if df is None or df.empty:
            raise ValueError(f"File portafoglio vuoto o non interpretabile: {filename}")

        col_norm = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}

        def _find_col(candidates):
            for cand in candidates:
                for norm_c, orig_c in col_norm.items():
                    if cand == norm_c or cand in norm_c:
                        return orig_c
            return None

        ticker_col = _find_col(["ticker", "symbol", "simbolo", "isin", "asset", "code"])
        name_col = _find_col(["name", "nome", "titolo", "descrizione", "instrument", "description", "security"])
        shares_col = _find_col(["shares", "units", "quote", "quantita", "quantità", "pezzi", "qty", "quantity"])
        buy_col = _find_col(["buy_price", "cost_basis", "prezzo_acquisto", "prezzo_carico", "pmc", "purchase_price", "prezzo_medio"])
        price_col = _find_col(["current_price", "market_price", "prezzo_attuale", "quotazione", "ultimo_prezzo", "price", "prezzo"])
        val_col = _find_col(["market_value", "controvalore", "valore_attuale", "valore_totale", "total_value", "importo", "totale", "value"])
        asset_class_col = _find_col(["asset_class", "classe", "categoria", "type", "tipo"])

        holdings = []
        total_market_value = 0.0
        total_cost_basis = 0.0

        for _, row in df.iterrows():
            ticker = str(row[ticker_col]).strip() if ticker_col and not pd.isna(row[ticker_col]) else ""
            name = str(row[name_col]).strip() if name_col and not pd.isna(row[name_col]) else ticker
            if not ticker and not name:
                continue

            shares = clean_numeric_amount(row[shares_col]) if shares_col and not pd.isna(row[shares_col]) else 1.0
            shares = abs(shares) if shares != 0.0 else 1.0

            buy_price = clean_numeric_amount(row[buy_col]) if buy_col and not pd.isna(row[buy_col]) else 0.0
            curr_price = clean_numeric_amount(row[price_col]) if price_col and not pd.isna(row[price_col]) else buy_price

            if val_col and not pd.isna(row[val_col]):
                mv = clean_numeric_amount(row[val_col])
            else:
                mv = shares * curr_price if curr_price > 0 else (shares * buy_price)

            cb = shares * buy_price if buy_price > 0 else mv
            pnl = mv - cb
            pnl_pct = (pnl / cb * 100.0) if cb > 0 else 0.0
            ac = str(row[asset_class_col]).strip() if asset_class_col and not pd.isna(row[asset_class_col]) else "Equity ETF"

            total_market_value += mv
            total_cost_basis += cb

            holdings.append({
                "ticker": ticker or name[:8].upper(),
                "name": name,
                "shares": shares,
                "buy_price": round(buy_price, 2),
                "current_price": round(curr_price, 2),
                "market_value": round(mv, 2),
                "cost_basis": round(cb, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "asset_class": ac,
            })

        tx_rows = []
        now_dt = pd.Timestamp.now().normalize()
        for h in holdings:
            tx_rows.append({
                "date": now_dt,
                "amount": h["market_value"],
                "currency": "EUR",
                "description": f"Quota ETF/Titoli: {h['ticker']} ({h['name']})",
                "counterparty": h["ticker"],
                "category": "Investimento ETF / Azioni",
                "balance_after": round(total_market_value, 2),
                "is_internal_transfer": False,
            })

        tx_df = pd.DataFrame(tx_rows) if tx_rows else pd.DataFrame()

        return BankStatement(
            account_id="Investment_Portfolio",
            institution="Portafoglio Titoli & ETF",
            account_type="Brokerage",
            asset_class="INVESTMENTS",
            currency="EUR",
            start_date=now_dt,
            end_date=now_dt,
            starting_balance=round(total_cost_basis, 2),
            ending_balance=round(total_market_value, 2),
            transactions=tx_df,
            source_file=filename,
            metadata={
                "holdings": holdings,
                "total_cost_basis": round(total_cost_basis, 2),
                "total_market_value": round(total_market_value, 2),
                "total_pnl": round(total_market_value - total_cost_basis, 2),
                "holdings_count": len(holdings),
            }
        )


# ============================================================
# REGISTRO DEI PARSER DISPONIBILI
# ============================================================
AVAILABLE_PARSERS: List[BaseBankParser] = [
    PdfBankParser(),            # Primario: gestisce tutti i file PDF bancari
    InvestmentPortfolioParser(),# Gestione liste ETF, portafogli titoli e broker
    WalletAppParser(),          # App tracciamento spese (BudgetBakers Wallet CSV)
    ErsteBankParser(),          # CSV/TSV
    TradeRepublicParser(),      # CSV/TSV
    DigitalBankParser(),        # CSV/TSV (Revolut, N26)
    ItalianBankParser(),        # CSV/TSV
    GenericBankParser(),        # Fallback CSV/Excel/Text
]


def parse_bank_statement(
    file_content: Union[str, bytes, Path],
    filename: Optional[str] = None,
    override_asset_class: Optional[str] = None,
    override_institution: Optional[str] = None
) -> BankStatement:
    """
    Funzione di ingresso unificata: seleziona automaticamente il parser
    più appropriato in base a firma e intestazioni del file.
    Accetta contenuti (str/bytes) oppure oggetti Path / percorsi di file.
    """
    if isinstance(file_content, Path) or (isinstance(file_content, str) and os.path.exists(file_content)):
        p = Path(file_content)
        if filename is None:
            filename = p.name
        try:
            with open(p, "rb") as f:
                file_content = f.read()
        except Exception:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                file_content = f.read()
    elif filename is None:
        filename = "statement.csv"

    errors: List[str] = []
    for parser in AVAILABLE_PARSERS:
        try:
            if parser.can_parse(file_content, filename):
                stmt = parser.parse(file_content, filename)
                if override_asset_class:
                    stmt.asset_class = override_asset_class
                if override_institution:
                    stmt.institution = override_institution
                return stmt
        except Exception as e:
            errors.append(f"{type(parser).__name__}: {e}")
            continue

    # Fallback finale
    fallback = GenericBankParser()
    try:
        stmt = fallback.parse(file_content, filename)
    except Exception as e:
        detail = "; ".join(errors[-2:] + [f"GenericBankParser: {e}"])
        raise ValueError(f"Formato non riconosciuto per '{filename}' ({detail})") from e
    if override_asset_class:
        stmt.asset_class = override_asset_class
    if override_institution:
        stmt.institution = override_institution
    return stmt
