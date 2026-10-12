# ============================================================
# REIMBURSEMENT & LOAN MANAGER — Spese Universitarie,
# Anticipi, Rimborsi, Prestiti Eccezionali & Google Sheets Scraper
# ============================================================
"""
Modulo per gestire in modo trasparente e contabile:
1. Spese Universitarie (acme / Missioni / Summer School / Conferenze):
   - Anticipi ricevuti dalla cassa di dipartimento/grant
   - Soldi spesi di tasca propria per viaggi/hotel/iscrizioni
   - Rimborsi già incassati e crediti pendenti da recuperare
2. Prestiti Eccezionali:
   - Soldi prestati a familiari/amici (crediti personali attivi)
   - Soldi ricevuti in prestito (debiti da restituire)
   - Saldo netto e scadenze di restituzione
3. Scraper / Importer Google Sheets & CSV:
   - Lettura diretta da Google Sheets pubblico o link condiviso
   - Import/Export CSV locale e sincronizzazione con gli Scheduled Shocks
"""

import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import requests

DEFAULT_CSV_NAME = "spese_universitarie_e_prestiti.csv"
GS_CONFIG_FILE = "google_sheet_url.txt"

SAMPLE_ENTRIES = [
    {
        "id": "UNIV-001",
        "category_type": "UNIVERSITA",
        "date": "2026-06-15",
        "counterparty": "acme Wien (Dipartimento)",
        "description": "Anticipo missione estiva e iscrizione corsi",
        "transaction_type": "ANTICIPO_RICEVUTO",
        "amount": 300.0,
        "expected_settlement_date": "2026-06",
        "status": "COMPLETATO",
        "notes": "Accreditato su Girokonto Erste Bank",
    },
    {
        "id": "UNIV-002",
        "category_type": "UNIVERSITA",
        "date": "2026-07-10",
        "counterparty": "acme Wien",
        "description": "Summer School Europe (Volo e alloggio anticipati di tasca mia)",
        "transaction_type": "SPESA_SOSTENUTA",
        "amount": 450.0,
        "expected_settlement_date": "2026-11",
        "status": "IN_ATTESA",
        "notes": "Modulo rimborso acme inviato a settembre, attesa delibera",
    },
    {
        "id": "UNIV-003",
        "category_type": "UNIVERSITA",
        "date": "2026-08-20",
        "counterparty": "acme Wien",
        "description": "Volo conferenza Bochum (Anticipato di tasca mia)",
        "transaction_type": "SPESA_SOSTENUTA",
        "amount": 250.0,
        "expected_settlement_date": "2026-10",
        "status": "IN_ATTESA",
        "notes": "Rimborso spese viaggio previsto ad ottobre 2026",
    },
    {
        "id": "UNIV-004",
        "category_type": "UNIVERSITA",
        "date": "2026-09-05",
        "counterparty": "acme Wien",
        "description": "Rimborso parziale spese missione giugno",
        "transaction_type": "RIMBORSO_RICEVUTO",
        "amount": 150.0,
        "expected_settlement_date": "2026-09",
        "status": "COMPLETATO",
        "notes": "Bonifico ricevuto su Erste Bank",
    },
    {
        "id": "LOAN-001",
        "category_type": "PRESTITO",
        "date": "2025-11-20",
        "counterparty": "Genitori",
        "description": "Prestito eccezionale per acquisto auto",
        "transaction_type": "PRESTITO_EROGATO",
        "amount": 2500.0,
        "expected_settlement_date": "2026-12",
        "status": "IN_ATTESA",
        "notes": "Restituzione prevista a Dicembre 2026 (inclusa negli shock)",
    },
    {
        "id": "LOAN-002",
        "category_type": "PRESTITO",
        "date": "2026-05-10",
        "counterparty": "Amico",
        "description": "Anticipo biglietti concerto ed evento",
        "transaction_type": "PRESTITO_EROGATO",
        "amount": 80.0,
        "expected_settlement_date": "2026-08",
        "status": "COMPLETATO",
        "notes": "Restituiti integralmente via Revolut",
    },
    {
        "id": "LOAN-003",
        "category_type": "PRESTITO",
        "date": "2026-08-15",
        "counterparty": "Amico",
        "description": "Restituzione anticipo biglietti concerto",
        "transaction_type": "RESTITUZIONE_RICEVUTA",
        "amount": 80.0,
        "expected_settlement_date": "2026-08",
        "status": "COMPLETATO",
        "notes": "Ricevuti su Revolut",
    },
]


def get_default_df() -> pd.DataFrame:
    """Restituisce il DataFrame di base con lo schema completo."""
    return pd.DataFrame(SAMPLE_ENTRIES)


def load_university_and_loans_data(data_dir: Path) -> pd.DataFrame:
    """Carica i dati dal CSV locale, creandolo con i valori demo se non esiste."""
    csv_path = data_dir / DEFAULT_CSV_NAME
    if not csv_path.exists():
        df = get_default_df()
        save_university_and_loans_data(df, data_dir)
        return df

    try:
        df = pd.read_csv(csv_path)
        # Assicura tipi numerici e colonne richieste
        expected_cols = [
            "id", "category_type", "date", "counterparty", "description",
            "transaction_type", "amount", "expected_settlement_date", "status", "notes"
        ]
        for c in expected_cols:
            if c not in df.columns:
                df[c] = ""
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        return df
    except Exception as e:
        print(f"[WARN] Impossibile leggere {csv_path}: {e}")
        return get_default_df()


def save_university_and_loans_data(df: pd.DataFrame, data_dir: Path):
    """Salva il DataFrame su disco."""
    csv_path = data_dir / DEFAULT_CSV_NAME
    df.to_csv(csv_path, index=False)


def get_saved_google_sheet_url(data_dir: Path) -> str:
    """Restituisce l'URL salvato del Google Sheet se presente, altrimenti stringa vuota."""
    cfg = data_dir / GS_CONFIG_FILE
    if cfg.exists():
        try:
            return cfg.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def save_google_sheet_url(url: str, data_dir: Path):
    """Salva l'URL del Google Sheet per consentire la sincronizzazione automatica persistente."""
    cfg = data_dir / GS_CONFIG_FILE
    cfg.write_text(url.strip(), encoding="utf-8")


def sync_from_saved_google_sheet(data_dir: Path) -> Tuple[pd.DataFrame, bool, str]:
    """
    Sincronizza automaticamente i dati dal Google Sheet salvato.
    Ritorna (df, successo, messaggio). In caso di errore o offline, ritorna il DataFrame locale di backup.
    """
    url = get_saved_google_sheet_url(data_dir)
    if not url:
        return load_university_and_loans_data(data_dir), False, "Nessun URL Google Sheet configurato."
    try:
        df_scraped = scrape_google_sheet(url, data_dir=data_dir)
        save_university_and_loans_data(df_scraped, data_dir)
        return df_scraped, True, f"Sincronizzate {len(df_scraped)} righe da Google Sheets con successo."
    except Exception as e:
        df_local = load_university_and_loans_data(data_dir)
        return df_local, False, f"Impossibile contattare Google Sheets ({e}). Usati dati locali di backup."


def scrape_google_sheet(sheet_url_or_id: str, data_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Estrae dati da un Google Sheet pubblico o con link di condivisione ('Chiunque abbia il link').
    Supporta:
    1. Fogli multi-tab (es. Dashboard, Expense Log, Received Funds con spese, categorie e anticipi acme)
    2. Fogli tabulari classici con intestazioni standard o euristiche
    3. Conservazione di eventuali prestiti personali esistenti se data_dir è fornito
    """
    import io
    cleaned = sheet_url_or_id.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

    # Estrazione Spreadsheet ID
    match_id = re.search(r"/d/([a-zA-Z0-9-_]+)", cleaned)
    if match_id:
        spreadsheet_id = match_id.group(1)
    else:
        spreadsheet_id = cleaned.split("/")[0]

    match_gid = re.search(r"[#&?]gid=([0-9]+)", cleaned)
    explicit_gid = match_gid.group(1) if match_gid else None

    # Scoperta dinamica dei tab tramite htmlview
    tabs = {}
    try:
        html_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/htmlview"
        r_html = requests.get(html_url, headers=headers, timeout=12)
        if r_html.status_code == 200:
            found = re.findall(r'name:\s*\"([^\"]+)\"[^}]*gid:\s*\"([0-9]+)\"', r_html.text)
            tabs = {name.strip(): gid for name, gid in found}
    except Exception:
        pass

    has_exp_log = any("expense log" in k.lower() or "expenses" in k.lower() for k in tabs.keys())
    has_funds = any("received funds" in k.lower() or "funds" in k.lower() or "anticipi" in k.lower() for k in tabs.keys())

    rows: List[Dict[str, Any]] = []

    # STRATEGIA A: Struttura Spese Universitarie / acme Multi-Tab
    if has_exp_log or has_funds:
        # 1. Expense Log
        if has_exp_log:
            exp_tab_name = next(k for k in tabs if "expense log" in k.lower() or "expenses" in k.lower())
            gid_exp = tabs[exp_tab_name]
            url_exp = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid_exp}"
            resp_exp = requests.get(url_exp, headers=headers, timeout=12)
            if resp_exp.status_code == 200:
                df_exp = pd.read_csv(io.StringIO(resp_exp.text))
                for _, r in df_exp.iterrows():
                    d = str(r.get("Date", "")).strip()
                    if not d or d == "nan" or d.lower() == "date":
                        continue
                    ev = str(r.get("Conference / Event", "")).strip()
                    desc = str(r.get("Description", "")).strip()
                    cat = str(r.get("Category", "")).strip()
                    amt_raw = str(r.get("Amount (€)", "0")).replace("€", "").replace(" ", "").replace(",", ".")
                    try:
                        amt = float(amt_raw)
                    except Exception:
                        amt = 0.0
                    st_raw = str(r.get("Reimbursement Status", "")).strip().lower()
                    status = "IN_ATTESA" if any(w in st_raw for w in ["to claim", "pending", "attesa"]) else "COMPLETATO"
                    bank = str(r.get("Bank", "")).strip()
                    notes = str(r.get("Notes / Claim ID", "")).strip()
                    doc = str(r.get("document number", "")).strip()
                    note_str = f"{cat} | Pagato con: {bank}"
                    if notes and notes != "nan":
                        note_str += f" | {notes}"
                    if doc and doc != "nan":
                        note_str += f" | Doc #{doc}"

                    settle_date = d[:7] if len(d) >= 7 else "2026-10"
                    if status == "IN_ATTESA":
                        settle_date = "2026-10" if any(k in ev.lower() for k in ["bochum", "graz"]) else "2026-11"

                    rows.append({
                        "id": f"EXP-{len(rows)+1:03d}",
                        "category_type": "UNIVERSITA",
                        "date": d,
                        "counterparty": f"acme / {ev}" if ev else "acme Wien",
                        "description": f"{ev}: {desc}" if ev else desc,
                        "transaction_type": "SPESA_SOSTENUTA",
                        "amount": amt,
                        "expected_settlement_date": settle_date,
                        "status": status,
                        "notes": note_str,
                    })

        # 2. Received Funds
        if has_funds:
            fnd_tab_name = next(k for k in tabs if "received funds" in k.lower() or "funds" in k.lower() or "anticipi" in k.lower())
            gid_fnd = tabs[fnd_tab_name]
            url_fnd = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid_fnd}"
            resp_fnd = requests.get(url_fnd, headers=headers, timeout=12)
            if resp_fnd.status_code == 200:
                df_fnd = pd.read_csv(io.StringIO(resp_fnd.text))
                for _, r in df_fnd.iterrows():
                    d = str(r.get("Date Received", "")).strip()
                    if not d or d == "nan" or d.lower() == "date":
                        continue
                    ev = str(r.get("Conference / Event", "")).strip()
                    ft = str(r.get("Funding Type (Cash Advance, Lump Sum / Per Diem", "")).strip()
                    amt_raw = str(r.get("Amount (€)", "0")).replace("€", "").replace(" ", "").replace(",", "")
                    try:
                        amt = float(amt_raw)
                    except Exception:
                        amt = 0.0
                    bank = str(r.get("bank", "")).strip()
                    notes = str(r.get("Notes", "")).strip()
                    tx_type = "ANTICIPO_RICEVUTO" if any(k in ft.lower() for k in ["advance", "anticipo"]) else "RIMBORSO_RICEVUTO"
                    rows.append({
                        "id": f"FND-{len(rows)+1:03d}",
                        "category_type": "UNIVERSITA",
                        "date": d,
                        "counterparty": f"acme / {ev}" if ev else "acme Wien",
                        "description": f"Anticipo acme ({ft}) per {ev}" if ev else f"Anticipo acme ({ft})",
                        "transaction_type": tx_type,
                        "amount": amt,
                        "expected_settlement_date": d[:7] if len(d) >= 7 else "2026-10",
                        "status": "COMPLETATO",
                        "notes": f"Accreditato su: {bank} | {notes}",
                    })

        df_norm = pd.DataFrame(rows)

    # STRATEGIA B: Tab Singolo Standard / Fallback
    else:
        target_gid = explicit_gid or (list(tabs.values())[0] if tabs else "0")
        export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={target_gid}"
        resp = requests.get(export_url, headers=headers, timeout=12)

        if resp.status_code != 200:
            # Fallback senza gid
            export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
            resp = requests.get(export_url, headers=headers, timeout=12)

        if resp.status_code != 200:
            raise ValueError(
                f"Impossibile accedere al Google Sheet (HTTP {resp.status_code}). "
                "Verifica che il foglio sia condiviso con 'Chiunque abbia il link può visualizzare'."
            )

        content = resp.content.decode("utf-8", errors="replace")
        df_raw = pd.read_csv(io.StringIO(content))

        col_map = {}
        for c in df_raw.columns:
            c_low = str(c).strip().lower()
            if any(k in c_low for k in ["tipo", "categoria", "ambito"]):
                col_map[c] = "category_type"
            elif any(k in c_low for k in ["data", "giorno", "date"]):
                col_map[c] = "date"
            elif any(k in c_low for k in ["ente", "controparte", "persona", "beneficiario"]):
                col_map[c] = "counterparty"
            elif any(k in c_low for k in ["descrizione", "causale", "oggetto", "motivo"]):
                col_map[c] = "description"
            elif any(k in c_low for k in ["movimento", "tipo_movimento", "operazione"]):
                col_map[c] = "transaction_type"
            elif any(k in c_low for k in ["importo", "valore", "euro", "totale", "amount"]):
                col_map[c] = "amount"
            elif any(k in c_low for k in ["scadenza", "previsto", "data_prevista", "settlement"]):
                col_map[c] = "expected_settlement_date"
            elif any(k in c_low for k in ["stato", "status"]):
                col_map[c] = "status"
            elif any(k in c_low for k in ["note", "commenti", "dettagli"]):
                col_map[c] = "notes"

        df_norm = df_raw.rename(columns=col_map).copy()

        for col in ["category_type", "date", "counterparty", "description", "transaction_type", "amount", "expected_settlement_date", "status", "notes"]:
            if col not in df_norm.columns:
                df_norm[col] = ""

        if "id" not in df_norm.columns:
            df_norm["id"] = [f"ITEM-{i+1:03d}" for i in range(len(df_norm))]

        df_norm["amount"] = pd.to_numeric(
            df_norm["amount"].astype(str).str.replace("€", "").str.replace(" ", "").str.replace(",", "."),
            errors="coerce"
        ).fillna(0.0)

    # Conserva eventuali prestiti personali presenti nel file locale di backup
    if data_dir is not None:
        try:
            df_existing = load_university_and_loans_data(data_dir)
            df_loans = df_existing[df_existing["category_type"] == "PRESTITO"].copy()
            if not df_loans.empty:
                df_norm = pd.concat([df_norm, df_loans], ignore_index=True)
        except Exception:
            pass

    return df_norm


def compute_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calcola il bilancio analitico delle spese universitarie e dei prestiti eccezionali.
    """
    if df.empty:
        return {
            "univ_anticipi": 0.0,
            "univ_speso": 0.0,
            "univ_rimborsato": 0.0,
            "univ_credito_netto": 0.0,
            "univ_in_attesa_count": 0,
            "loan_erogati": 0.0,
            "loan_restituzioni_ricevute": 0.0,
            "loan_credito_residuo": 0.0,
            "loan_ricevuti": 0.0,
            "loan_restituzioni_effettuate": 0.0,
            "loan_debito_residuo": 0.0,
            "loan_saldo_netto": 0.0,
            "patrimonio_credito_totale": 0.0,
        }

    # 1. Spese Universitarie
    df_univ = df[df["category_type"] == "UNIVERSITA"].copy()
    anticipi = df_univ[df_univ["transaction_type"] == "ANTICIPO_RICEVUTO"]["amount"].sum()
    speso = df_univ[df_univ["transaction_type"] == "SPESA_SOSTENUTA"]["amount"].sum()
    rimborsato = df_univ[df_univ["transaction_type"] == "RIMBORSO_RICEVUTO"]["amount"].sum()

    # Il credito netto rappresenta i soldi che l'università deve ancora rifonderti
    credito_univ = float(speso - (anticipi + rimborsato))
    in_attesa_univ = int((df_univ["status"] == "IN_ATTESA").sum())

    # 2. Prestiti Eccezionali
    df_loans = df[df["category_type"] == "PRESTITO"].copy()
    p_erogati = df_loans[df_loans["transaction_type"] == "PRESTITO_EROGATO"]["amount"].sum()
    r_ricevute = df_loans[df_loans["transaction_type"] == "RESTITUZIONE_RICEVUTA"]["amount"].sum()
    credito_prestiti = float(p_erogati - r_ricevute)

    p_ricevuti = df_loans[df_loans["transaction_type"] == "PRESTITO_RICEVUTO"]["amount"].sum()
    r_effettuate = df_loans[df_loans["transaction_type"] == "RESTITUZIONE_EFFETTUATA"]["amount"].sum()
    debito_prestiti = float(p_ricevuti - r_effettuate)

    saldo_prestiti = float(credito_prestiti - debito_prestiti)
    totale_crediti = float(credito_univ + credito_prestiti)

    return {
        "univ_anticipi": float(anticipi),
        "univ_speso": float(speso),
        "univ_rimborsato": float(rimborsato),
        "univ_credito_netto": credito_univ,
        "univ_in_attesa_count": in_attesa_univ,
        "loan_erogati": float(p_erogati),
        "loan_restituzioni_ricevute": float(r_ricevute),
        "loan_credito_residuo": credito_prestiti,
        "loan_ricevuti": float(p_ricevuti),
        "loan_restituzioni_effettuate": float(r_effettuate),
        "loan_debito_residuo": debito_prestiti,
        "loan_saldo_netto": saldo_prestiti,
        "patrimonio_credito_totale": totale_crediti,
    }
