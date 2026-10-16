# ============================================================
# BANKING MODULE — PII SCRUBBER & ANONYMIZER (100% LOCALE)
# ============================================================
"""
Modulo per l'anonimizzazione preventiva e totale (PII Scrubber) di estratti conto bancari.
Tutti i dati sensibili (IBAN, carte, nomi, codici fiscali, causali personali) vengono
sostituiti con identificatori pseudonimizzati deterministici e sicuri prima di qualunque
elaborazione o passaggio a modelli di intelligenza artificiale locali.

Zero dati escono dal dispositivo. Il mapping di riscrittura risiede unicamente in RAM.
"""

import re
from typing import Dict, List, Optional, Tuple
import pandas as pd


class PIIScrubber:
    """
    Scrubber di informazioni personali identificabili (PII) specificamente
    calibrato per estratti conto bancari europei (Italia, Austria, Germania, UK).
    """

    # Regex per IBAN europei (SEPA standard)
    IBAN_REGEX = re.compile(
        r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b", re.IGNORECASE
    )

    # Regex per carte di credito/debito (intere o parzialmente mascherate)
    CARD_REGEX = re.compile(
        r"\b(?:\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|\d{4}[*X\s-]{4,10}\d{4})\b"
    )

    # Regex per Codice Fiscale italiano
    CF_REGEX = re.compile(
        r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b", re.IGNORECASE
    )

    # Regex per BIC / SWIFT
    BIC_REGEX = re.compile(
        r"\b([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b"
    )

    # Regex per email
    EMAIL_REGEX = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )

    # Regex per numeri telefonici (solo formato internazionale con "+", per non toccare importi)
    PHONE_REGEX = re.compile(
        r"(?<![\w.,])\+\d{1,3}[\s.-]?\d{2,4}(?:[\s.-]?\d{2,4}){2,3}(?!\d)"
    )

    # BIC/SWIFT solo se preceduto dalla parola chiave (evita di mascherare parole come BONIFICO)
    BIC_CONTEXT_REGEX = re.compile(
        r"\b((?:BIC|SWIFT)\s*[:\-]?\s*)([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b"
    )

    # Pattern per beneficiari, ordinanti e controparti in causali bancarie
    COUNTERPARTY_PATTERNS = [
        re.compile(r"(?:BENEFICIARIO|BENEFICIARY)\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,35})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
        re.compile(r"(?:ORDINANTE|ORDERING\s*PARTY)\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,35})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
        re.compile(r"(?:A\s+FAVORE\s+DI|DISPOSIZIONE\s+DI)\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,35})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
        re.compile(r"(?:EMPFÄNGER|AUFTRAGGEBER|ZAHLUNGSEMPFÄNGER)\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,35})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
        re.compile(r"(?:BONIFICO\s+SEPA\s+(?:DA|A))\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,35})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
        re.compile(r"\b(?i:to|from|an|von)\s+([A-Z][a-zà-ÿ]+(?:\s+[A-Z][a-zà-ÿ]+){1,2})\b"),
        re.compile(r"(?:RIMBORSO\s+(?:DA|A|PER))\s*[:\-]?\s*([A-Za-z0-9\s.,'&-]{3,30})(?=\s*-\s*|\s*IBAN|\s*BIC|\s*$|;)", re.IGNORECASE),
    ]

    def __init__(self):
        # Vault in memoria per mapping bidirezionale
        self._vault_to_fake: Dict[str, str] = {}
        self._vault_to_real: Dict[str, str] = {}
        self._counter_iban = 0
        self._counter_card = 0
        self._counter_cf = 0
        self._counter_person = 0
        self._counter_email = 0
        self._counter_phone = 0

    def reset_vault(self):
        """Azzera il mapping conservato in memoria."""
        self._vault_to_fake.clear()
        self._vault_to_real.clear()
        self._counter_iban = 0
        self._counter_card = 0
        self._counter_cf = 0
        self._counter_person = 0
        self._counter_email = 0
        self._counter_phone = 0

    def _get_or_create_token(self, original_val: str, prefix: str) -> str:
        cleaned = original_val.strip()
        if not cleaned:
            return original_val
        key = f"{prefix}::{cleaned.upper()}"
        if key in self._vault_to_fake:
            return self._vault_to_fake[key]

        if prefix == "IBAN":
            self._counter_iban += 1
            country = cleaned[:2].upper() if len(cleaned) >= 2 else "EU"
            token = f"[IBAN_{country}_{self._counter_iban:02d}]"
        elif prefix == "CARD":
            self._counter_card += 1
            last4 = re.sub(r"\D", "", cleaned)[-4:] if len(re.sub(r"\D", "", cleaned)) >= 4 else "XXXX"
            token = f"[CARD_****{last4}]"
        elif prefix == "CF":
            self._counter_cf += 1
            token = f"[TAX_ID_{self._counter_cf:02d}]"
        elif prefix == "PERSON":
            self._counter_person += 1
            token = f"[SOGGETTO_{self._counter_person:02d}]"
        elif prefix == "EMAIL":
            self._counter_email += 1
            token = f"[EMAIL_{self._counter_email:02d}]"
        elif prefix == "PHONE":
            self._counter_phone += 1
            token = f"[TEL_{self._counter_phone:02d}]"
        else:
            token = f"[{prefix}_ANON]"

        self._vault_to_fake[key] = token
        self._vault_to_real[token] = cleaned
        return token

    def anonymize_text(self, text: Optional[str]) -> str:
        """
        Scrubba un singolo testo (es. causale o descrizione) sostituendo tutte le PII.
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        cleaned = text

        # 1. Maschera IBAN
        def _replace_iban(match):
            raw = match.group(0)
            # Verifica minima di verosimiglianza lunghezza IBAN (15-34 caratteri)
            if 15 <= len(re.sub(r"\s", "", raw)) <= 34:
                return self._get_or_create_token(raw, "IBAN")
            return raw

        cleaned = self.IBAN_REGEX.sub(_replace_iban, cleaned)

        # 2. Maschera Carte
        def _replace_card(match):
            raw = match.group(0)
            return self._get_or_create_token(raw, "CARD")

        cleaned = self.CARD_REGEX.sub(_replace_card, cleaned)

        # 3. Maschera Codici Fiscali
        def _replace_cf(match):
            raw = match.group(0)
            return self._get_or_create_token(raw, "CF")

        cleaned = self.CF_REGEX.sub(_replace_cf, cleaned)

        # 4. Maschera Email
        def _replace_email(match):
            raw = match.group(0)
            return self._get_or_create_token(raw, "EMAIL")

        cleaned = self.EMAIL_REGEX.sub(_replace_email, cleaned)

        # 4b. Maschera BIC/SWIFT (con keyword) e telefoni internazionali
        cleaned = self.BIC_CONTEXT_REGEX.sub(
            lambda m: m.group(1) + self._get_or_create_token(m.group(2), "BIC"), cleaned
        )
        cleaned = self.PHONE_REGEX.sub(
            lambda m: self._get_or_create_token(m.group(0), "PHONE"), cleaned
        )

        # 5. Maschera Nomi e Controparti nelle causali
        for pattern in self.COUNTERPARTY_PATTERNS:
            def _replace_counterparty(match):
                entire = match.group(0)
                name_part = match.group(1).strip()
                # Evita di mascherare parole chiave bancarie generiche
                stopwords = {"SEPA", "BONIFICO", "COMMISSIONE", "IMPOSTA", "INTERESSI", "STIPENDIO", "CANONE"}
                if name_part.upper() in stopwords or len(name_part) < 3:
                    return entire
                fake_token = self._get_or_create_token(name_part, "PERSON")
                return entire.replace(name_part, fake_token)

            cleaned = pattern.sub(_replace_counterparty, cleaned)

        return cleaned

    def deanonymize_text(self, text: str) -> str:
        """Ripristina i valori reali (utile esclusivamente in memoria locale per render finale)."""
        if not text:
            return ""
        result = text
        for token, original in self._vault_to_real.items():
            result = result.replace(token, original)
        return result

    def anonymize_dataframe(
        self, df: pd.DataFrame, text_columns: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Produce una copia anonimizzata del DataFrame.
        """
        df_anon = df.copy()
        if text_columns is None:
            # Rileva automaticamente colonne testuali
            text_columns = [
                c for c in df.columns if df[c].dtype == object or df[c].dtype == "string"
            ]

        for col in text_columns:
            if col in df_anon.columns:
                df_anon[col] = df_anon[col].fillna("").astype(str).apply(self.anonymize_text)

        return df_anon

    def audit_cleanliness(self, text: str) -> Tuple[bool, List[str]]:
        """
        Esegue un audit diagnostico per verificare che non vi siano PII residue nel testo.
        Ritorna (is_clean, leaks_list).
        """
        leaks = []
        if self.IBAN_REGEX.search(text):
            for match in self.IBAN_REGEX.finditer(text):
                val = match.group(0)
                if not val.startswith("[IBAN_"):
                    leaks.append(f"Residuo IBAN non mascherato: {val}")
        if self.CF_REGEX.search(text):
            for match in self.CF_REGEX.finditer(text):
                val = match.group(0)
                if not val.startswith("[TAX_ID_"):
                    leaks.append(f"Residuo Codice Fiscale non mascherato: {val}")
        if self.EMAIL_REGEX.search(text):
            leaks.append("Residuo indirizzo email non mascherato")

        return len(leaks) == 0, leaks

    @property
    def total_scrubbed_count(self) -> int:
        return len(self._vault_to_fake)
