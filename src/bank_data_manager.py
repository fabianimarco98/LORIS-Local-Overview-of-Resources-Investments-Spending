# ============================================================
# BANK DATA MANAGER — Caricamento Estratti Conto Multi-Banca,
# Categorizzazione, Statistiche di Spesa e Bridge Simulazione
# ============================================================
"""
Modulo principale per v4_speciale (indipendente al 100% da Monefy):
- Legge e aggrega molteplici estratti conto (CSV, Excel, PDF) da directory o caricamento UI.
- Filtra i giroconti / trasferimenti tra conti propri per evitare duplicazioni.
- Categorizza le transazioni tramite motore euristico offline o LLM locale (Ollama / llama.cpp).
- Calcola statistiche di spesa mensile (media, deviazione standard, burn rate, tasso di risparmio).
- Rileva automaticamente entrate stipendiali (es. acme Gehalt).
- Fornisce i parametri di cassa iniziale e spese per alimentare il Simulation Engine Monte Carlo.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np
import pandas as pd

import banking
from banking.parsers import BankStatement, parse_bank_statement, GenericBankParser
from banking.portfolio import PortfolioAggregator, PortfolioSummary
from banking.anonymizer import PIIScrubber
from banking.local_llm import LocalLLMClient


CATEGORY_KEYWORDS = {
    "Affitto": ["miete", "affitto", "rent", "mortgage", "mutuo", "housing", "landlord", "musterstrasse", "locazione", "canone", "wohn", "immobilien", "hausverwaltung"],
    "Spesa & Alimentari": ["billa", "spar", "hofer", "lidl", "coop", "conad", "esselunga", "carrefour", "supermarket", "supermercato", "grocery", "groceries", "alimentar", "penny", "rewe", "walmart", "tesco", "kroger", "trader joe", "whole foods", "aldi"],
    "Bollette & Utenze": ["wiener netze", "gas", "strom", "enel", "a2a", "utenze", "luce", "acqua", "hera", "telecom", "vodafone", "bolletta", "electric", "utility", "power", "energy", "internet", "water bill"],
    "Palestra & Sport": ["mcfit", "fitinn", "palestra", "sport", "gym", "decathlon", "fitness", "climbing", "swim", "yoga"],
    "Svago & Scommesse": ["betfair", "bet365", "snai", "eurobet", "sisal", "lottomatica", "planetwin", "pokerstars", "bwin", "goldbet", "william hill", "casino", "scommesse", "betting", "gambling", "poker"],
    "Ristoranti & Svago": ["ristorante", "pizzeria", "kino", "cinema", "bar", "cafe", "caffetteria", "trattoria", "osterie", "mcdonald", "burger", "uber eats", "deliveroo", "just eat", "restaurant", "pub", "coffee", "starbucks", "doordash", "grubhub"],
    "Trasporti & Viaggi": ["wiener linien", "öbb", "trenitalia", "italo", "ryanair", "easyjet", "wizz", "flughafen", "taxi", "uber", "benzina", "eni", "q8", "autostrada", "pedaggio", "flight", "airline", "subway", "metro", "transit", "train", "fuel", "gasoline", "shell", "bp"],
    "Abbonamenti & IT": ["netflix", "spotify", "amazon prime", "chatgpt", "openai", "github", "apple", "google", "cloud", "telefonia", "iliad", "tim", "wind", "dropbox", "aws", "hulu", "disney", "youtube", "adobe"],
    "Salute & Farmacia": ["apotheke", "farmacia", "medico", "arzt", "visita medica", "dentista", "sanit", "pharmacy", "doctor", "hospital", "clinic", "dental", "health", "medical"],
    "Investimenti & PAC": ["sparplan", "etf", "ishares", "vanguard", "amundi", "broker", "scalable", "degiro", "titoli", "trade republic", "investment", "shares", "stocks", "fidelity", "schwab"],
    "Interessi & Rendite": ["zinsen", "interessi", "dividendo", "cedola", "cashback", "interest", "dividend", "yield"],
    "Stipendio & Compensi": ["acme", "gehalt", "stipendio", "salary", "universität", "unibo", "emolumento", "compenso", "retribuzione", "payroll", "wage", "direct deposit", "employer"],
}


def _matches_keyword(kw: str, text: str) -> bool:
    """Verifica se una parola chiave è presente nel testo rispettando i confini di parola per termini brevi (es. 'etf')."""
    kw_clean = kw.strip().lower()
    text_clean = text.strip().lower()
    if not kw_clean or not text_clean:
        return False
    if len(kw_clean) <= 4 or kw_clean in {"etf", "pac", "gas", "bar", "rent", "acme", "spar", "aldi", "coop", "pam", "q8", "tim", "wind", "aws"}:
        return bool(re.search(r"\b" + re.escape(kw_clean) + r"\b", text_clean))
    return kw_clean in text_clean


def load_all_bank_statements(
    statements_dir: str = "input/bank_statements",
    as_of_date: Optional[str] = None,
    uploaded_files: Optional[List[Any]] = None
) -> Tuple[List[BankStatement], PortfolioSummary]:
    """
    Carica tutti gli estratti conto presenti nella directory specificata
    o passati come upload in memoria (Streamlit UploadedFiles).
    Supporta anche la scansione automatica di 'input/investments' per liste ETF e titoli.
    Garantisce la deduplicazione automatica dei file.
    """
    aggregator = PortfolioAggregator()
    cutoff = pd.to_datetime(as_of_date).normalize() if as_of_date else None
    seen_sources = set()

    # 1. Caricamento da file caricati via UI
    if uploaded_files:
        for uf in uploaded_files:
            fname = getattr(uf, "name", "sconosciuto")
            if fname in seen_sources:
                continue
            try:
                content = uf.getvalue()
                stmt = parse_bank_statement(content, fname)
                aggregator.add_statement(stmt)
                seen_sources.add(fname)
            except Exception as e:
                print(f"[WARN] Errore caricamento file {fname}: {e}")

    # 2. Caricamento da directory disco (bank_statements, investments e wallet)
    search_dirs = [Path(statements_dir), Path("input/investments"), Path("input/wallet")]
    valid_extensions = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".pdf", ".json"}

    for p_dir in search_dirs:
        if not p_dir.is_absolute() and not p_dir.exists():
            for candidate in [Path.cwd() / p_dir, Path(__file__).resolve().parent.parent / p_dir, Path("v4_speciale") / p_dir]:
                if candidate.exists():
                    p_dir = candidate
                    break

        if p_dir.exists():
            for fpath in sorted(p_dir.iterdir()):
                if fpath.name in seen_sources:
                    continue
                if fpath.suffix.lower() in valid_extensions and not fpath.name.startswith("."):
                    try:
                        stmt = parse_bank_statement(fpath)
                        aggregator.add_statement(stmt)
                        seen_sources.add(fpath.name)
                    except Exception as e:
                        print(f"[WARN] Errore parsing {fpath.name}: {e}")

    summary = aggregator.aggregate(as_of_date=cutoff)
    return aggregator.statements, summary


def classify_transaction(description: str, amount: float) -> str:
    """Classifica una singola transazione in base alla causale e segno importo."""
    desc_lower = str(description).lower()

    if amount > 0:
        for kw in CATEGORY_KEYWORDS["Stipendio & Compensi"]:
            if _matches_keyword(kw, desc_lower):
                return "Stipendio"
        for kw in CATEGORY_KEYWORDS["Interessi & Rendite"]:
            if _matches_keyword(kw, desc_lower):
                return "Interessi & Rendite"
        return "Entrate Varie"

    # Spese (amount < 0)
    for cat, kws in CATEGORY_KEYWORDS.items():
        if cat in ["Stipendio & Compensi", "Interessi & Rendite"]:
            continue
        for kw in kws:
            if _matches_keyword(kw, desc_lower):
                return cat

    return "Altre Spese"


def categorize_transactions(
    df_tx: pd.DataFrame,
    df_transfers: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Arricchisce il DataFrame delle transazioni con categoria e flag per giroconti.
    """
    if df_tx.empty:
        return df_tx

    df = df_tx.copy()
    if "category" not in df.columns:
        df["category"] = "Da Classificare"

    if "is_internal_transfer" not in df.columns:
        df["is_internal_transfer"] = False
    else:
        # Assicura tipo booleano coerente
        df["is_internal_transfer"] = df["is_internal_transfer"].fillna(False).astype(bool)

    # Identifica giroconti da tabella riconciliazione se forniti
    if df_transfers is not None and not df_transfers.empty:
        for _, tr in df_transfers.iterrows():
            amt = float(tr["amount"])
            from_d = tr.get("from_date", tr["date"])
            to_d = tr.get("to_date", tr["date"])
            mask_out = (
                (np.isclose(df["amount"], -amt, atol=0.01)) &
                (df["account_id"] == tr["from_account"]) &
                (df["date"] == from_d)
            )
            df.loc[mask_out, "is_internal_transfer"] = True
            df.loc[mask_out, "category"] = "Giroconto Interno"

            mask_in = (
                (np.isclose(df["amount"], amt, atol=0.01)) &
                (df["account_id"] == tr["to_account"]) &
                (df["date"] == to_d)
            )
            df.loc[mask_in, "is_internal_transfer"] = True
            df.loc[mask_in, "category"] = "Giroconto Interno"

    # Se già marcato giroconto dal parser
    mask_already_internal = (df["category"] == "Giroconto") | (df["is_internal_transfer"])
    df.loc[mask_already_internal, "is_internal_transfer"] = True
    df.loc[mask_already_internal, "category"] = "Giroconto Interno"

    # Classifica il resto
    for idx, row in df.iterrows():
        if df.loc[idx, "is_internal_transfer"]:
            continue
        curr_cat = df.loc[idx, "category"]
        if curr_cat in ["Da Classificare", "Generico", None, "", "Spesa", "Entrata"]:
            df.loc[idx, "category"] = classify_transaction(row.get("description", ""), row.get("amount", 0.0))

    return df


def compute_bank_monthly_statistics(
    df_tx: pd.DataFrame,
    filter_source: str = "all"
) -> Dict[str, Any]:
    """
    Calcola le statistiche mensili retrospettive di entrate e uscite basate sui dati bancari e/o tracker:
    - filter_source: 'all' (tutto integrato), 'banks' (solo estratti bancari), 'wallet' (solo app spese)
    - Esclude i giroconti interni per non duplicare i flussi
    - Calcola media e std mensile per categoria, burn rate, tasso di risparmio
    - Rileva stipendio o entrate ricorrenti regolari
    - Genera aggregazioni mensili, pivot di categoria e top destinatari
    """
    if df_tx.empty:
        return {
            "monthly_expenses_mean": 0.0,
            "monthly_expenses_std": 0.0,
            "detected_salary": 0.0,
            "total_tracked_months": 0,
            "total_inflow": 0.0,
            "total_outflow": 0.0,
            "net_savings": 0.0,
            "average_savings_rate": 0.0,
            "category_summary": pd.DataFrame(),
            "monthly_cashflow": pd.DataFrame(),
            "top_payees": pd.DataFrame(),
            "monthly_by_category": pd.DataFrame(),
            "discretionary_split": {"essentials": 0.0, "discretionary": 0.0, "ratio": 0.0},
            "has_wallet_data": False,
            "wallet_stats": {},
            "active_filter": filter_source,
        }

    df = df_tx.copy()

    # Filtro sorgente (tutto, solo banche, solo wallet)
    if "is_tracker" in df.columns:
        if filter_source == "banks":
            df = df[~df["is_tracker"].fillna(False)].copy()
        elif filter_source == "wallet":
            df = df[df["is_tracker"].fillna(False)].copy()

    if "is_internal_transfer" in df.columns:
        df = df[~df["is_internal_transfer"].fillna(False)].copy()

    if df.empty:
        return {
            "monthly_expenses_mean": 0.0,
            "monthly_expenses_std": 0.0,
            "detected_salary": 0.0,
            "total_tracked_months": 0,
            "total_inflow": 0.0,
            "total_outflow": 0.0,
            "net_savings": 0.0,
            "average_savings_rate": 0.0,
            "category_summary": pd.DataFrame(),
            "monthly_cashflow": pd.DataFrame(),
            "top_payees": pd.DataFrame(),
            "monthly_by_category": pd.DataFrame(),
            "discretionary_split": {"essentials": 0.0, "discretionary": 0.0, "ratio": 0.0},
            "has_wallet_data": False,
            "wallet_stats": {},
            "active_filter": filter_source,
        }

    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")

    # Spese ed Entrate
    debits = df[df["amount"] < 0].copy()
    credits = df[df["amount"] > 0].copy()

    monthly_deb = debits.groupby("month")["amount"].sum().abs()
    monthly_cred = credits.groupby("month")["amount"].sum()

    # Cashflow mensile unificato
    all_months = sorted(list(set(monthly_deb.index).union(set(monthly_cred.index))))
    m_flow = pd.DataFrame(index=all_months)
    m_flow["entrate"] = monthly_cred.reindex(all_months).fillna(0.0)
    m_flow["uscite"] = monthly_deb.reindex(all_months).fillna(0.0)
    m_flow["netto"] = m_flow["entrate"] - m_flow["uscite"]
    m_flow["savings_rate"] = np.where(
        m_flow["entrate"] > 0,
        (m_flow["netto"] / m_flow["entrate"]) * 100.0,
        0.0
    )

    tot_inflow = float(m_flow["entrate"].sum())
    tot_outflow = float(m_flow["uscite"].sum())
    net_savings = tot_inflow - tot_outflow
    avg_savings_rate = float((net_savings / tot_inflow * 100.0) if tot_inflow > 0 else 0.0)

    mean_exp = float(monthly_deb.mean()) if not monthly_deb.empty else 0.0
    std_exp = float(monthly_deb.std()) if len(monthly_deb) > 1 else 0.0

    # Rilevamento Stipendio / Flussi regolari di reddito
    salary_tx = credits[credits["category"] == "Stipendio"]
    if not salary_tx.empty:
        detected_salary = float(salary_tx["amount"].median())
    else:
        # Fallback a crediti ricorrenti > 1000 o mediana delle entrate mensili effettive
        large_inflows = credits[credits["amount"] >= 1000.0]
        if not large_inflows.empty:
            detected_salary = float(large_inflows["amount"].median())
        elif not monthly_cred.empty and (monthly_cred > 0).any():
            detected_salary = float(monthly_cred[monthly_cred > 0].median())
        else:
            detected_salary = 0.0

    # Statistiche per categoria di spesa
    if not debits.empty:
        cat_summary = debits.groupby("category")["amount"].agg(
            totale_uscito=lambda s: abs(float(s.sum())),
            conteggio_operazioni="count",
            media_operazione=lambda s: abs(float(s.mean()))
        ).reset_index()
        cat_summary["percentuale"] = (cat_summary["totale_uscito"] / cat_summary["totale_uscito"].sum()) * 100.0
        cat_summary = cat_summary.sort_values("totale_uscito", ascending=False)
    else:
        cat_summary = pd.DataFrame()

    # Pivot Mensile per Categoria
    if not debits.empty:
        debits["abs_amount"] = debits["amount"].abs()
        monthly_by_category = debits.pivot_table(
            index="month",
            columns="category",
            values="abs_amount",
            aggfunc="sum",
            fill_value=0.0
        )
    else:
        monthly_by_category = pd.DataFrame()

    # Top 10 Payees / Destinatari di spesa
    if not debits.empty:
        payee_col = "counterparty" if "counterparty" in debits.columns else "description"
        top_payees = debits.groupby(payee_col)["amount"].agg(
            totale=lambda s: abs(float(s.sum())),
            transazioni="count"
        ).reset_index()
        top_payees.columns = ["beneficiario", "totale_speso", "numero_transazioni"]
        top_payees = top_payees.sort_values("totale_speso", ascending=False).head(10)
    else:
        top_payees = pd.DataFrame()

    # Spese essenziali vs discrezionali
    essential_cats = {"Affitto", "Bollette & Utenze", "Spesa & Alimentari", "Salute & Farmacia", "Trasporti & Viaggi"}
    if not debits.empty:
        ess_total = abs(float(debits[debits["category"].isin(essential_cats)]["amount"].sum()))
        disc_total = abs(float(debits[~debits["category"].isin(essential_cats)]["amount"].sum()))
        disc_split = {
            "essentials": round(ess_total, 2),
            "discretionary": round(disc_total, 2),
            "ratio": round(disc_total / (ess_total + disc_total) * 100.0, 1) if (ess_total + disc_total) > 0 else 0.0
        }
    else:
        disc_split = {"essentials": 0.0, "discretionary": 0.0, "ratio": 0.0}

    # Calcolo statistiche specifiche per Wallet se presente
    has_wallet = ("is_tracker" in df_tx.columns and df_tx["is_tracker"].any())
    w_stats = {}
    if has_wallet:
        w_df = df_tx[df_tx["is_tracker"].fillna(False)].copy()
        w_deb = w_df[w_df["amount"] < 0]
        w_cash_deb = w_deb[w_deb["is_cash"].fillna(False).astype(bool)] if "is_cash" in w_deb.columns else pd.DataFrame()
        w_elec_deb = w_deb[~w_deb["is_cash"].fillna(False).astype(bool)] if "is_cash" in w_deb.columns else w_deb
        tot_w_exp = float(abs(w_deb["amount"].sum())) if not w_deb.empty else 0.0
        tot_w_cash = float(abs(w_cash_deb["amount"].sum())) if not w_cash_deb.empty else 0.0
        tot_w_elec = float(abs(w_elec_deb["amount"].sum())) if not w_elec_deb.empty else 0.0

        w_cat_summary = pd.DataFrame()
        if not w_deb.empty and "wallet_category" in w_deb.columns:
            w_cat_summary = w_deb.groupby("wallet_category")["amount"].agg(
                totale_speso=lambda s: abs(float(s.sum())),
                operazioni="count"
            ).reset_index().sort_values("totale_speso", ascending=False)

        w_stats = {
            "total_expenses": round(tot_w_exp, 2),
            "cash_expenses": round(tot_w_cash, 2),
            "electronic_expenses": round(tot_w_elec, 2),
            "cash_ratio_pct": round((tot_w_cash / tot_w_exp * 100.0), 1) if tot_w_exp > 0 else 0.0,
            "tx_count": len(w_df),
            "cash_tx_count": len(w_cash_deb),
            "wallet_category_summary": w_cat_summary,
        }

    return {
        "monthly_expenses_mean": round(mean_exp, 2),
        "monthly_expenses_std": round(std_exp, 2),
        "detected_salary": round(detected_salary, 2),
        "total_tracked_months": len(all_months),
        "total_inflow": round(tot_inflow, 2),
        "total_outflow": round(tot_outflow, 2),
        "net_savings": round(net_savings, 2),
        "average_savings_rate": round(avg_savings_rate, 1),
        "category_summary": cat_summary,
        "monthly_cashflow": m_flow,
        "top_payees": top_payees,
        "monthly_by_category": monthly_by_category,
        "discretionary_split": disc_split,
        "has_wallet_data": has_wallet,
        "wallet_stats": w_stats,
        "active_filter": filter_source,
    }


def detect_recurring_from_statements(df_tx: pd.DataFrame) -> pd.DataFrame:
    """
    Rileva automaticamente le spese fisse e ricorrenti direttamente dagli estratti conto
    (canoni, affitto, bollette, abbonamenti, palestra) senza richiedere alcun file esterno.
    """
    if df_tx.empty:
        return pd.DataFrame(columns=["name", "min_cost", "max_cost", "probability", "inflation_type"])

    df = df_tx.copy()
    if "is_internal_transfer" in df.columns:
        df = df[~df["is_internal_transfer"]].copy()

    # Filtra solo le uscite
    debits = df[df["amount"] < 0].copy()
    if debits.empty:
        return pd.DataFrame(columns=["name", "min_cost", "max_cost", "probability", "inflation_type"])

    # Categorie considerate naturalmente ricorrenti
    rec_cats = {"Affitto", "Bollette & Utenze", "Abbonamenti & IT", "Palestra & Sport"}
    recurring_items = []

    # 1. Per categoria nota ricorrente
    for cat in rec_cats:
        cat_tx = debits[debits["category"] == cat]
        if not cat_tx.empty:
            amounts = cat_tx["amount"].abs()
            recurring_items.append({
                "name": f"Spese fisse: {cat}",
                "min_cost": round(float(amounts.min()), 2),
                "max_cost": round(float(amounts.max()), 2),
                "probability": 1.0,
                "inflation_type": "continuous" if cat != "Affitto" else "annual",
            })

    # 2. Spese variabili aggregate (Spesa & Alimentari, Ristoranti, ecc.)
    var_tx = debits[~debits["category"].isin(rec_cats)]
    if not var_tx.empty:
        amounts = var_tx["amount"].abs()
        p25 = float(amounts.quantile(0.25))
        p75 = float(amounts.quantile(0.75))
        recurring_items.append({
            "name": "Spese variabili correnti (Alimentari, Trasporti, Varie)",
            "min_cost": round(p25, 2),
            "max_cost": round(p75, 2),
            "probability": 0.95,
            "inflation_type": "continuous",
        })

    return pd.DataFrame(recurring_items)


def load_configs(data_dir: str = "input") -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Carica i file di configurazione macro, ricorrenti e shock.
    Se i file non esistono, crea configurazioni predefinite coerenti
    consentendo al sistema di funzionare al 100% unicamente da estratti conto.
    """
    dp = Path(data_dir)
    if not dp.is_absolute():
        if not dp.exists():
            for candidate in [Path.cwd() / dp, Path(__file__).resolve().parent.parent / dp, Path("v4_speciale") / dp, Path("v3/previsione__spese") / dp]:
                if candidate.exists():
                    dp = candidate
                    break

    macro_path = dp / "macro_settings.csv"
    if not macro_path.exists() and (dp / "templates" / "macro_settings.csv").exists():
        macro_path = dp / "templates" / "macro_settings.csv"

    if macro_path.exists():
        df_macro = pd.read_csv(macro_path).dropna(how="all").set_index("parameter")
    else:
        defaults = {
            "parameter": [
                "starting_cash", "starting_investments", "monthly_investment",
                "salary_phase_1", "salary_phase_2", "salary_phase_2_extra",
                "annual_inflation_mean", "annual_inflation_std",
                "annual_market_return_mean", "annual_market_return_std",
                "cash_interest_gross", "overdraft_rate_annual",
                "expense_common_std", "expense_common_rho"
            ],
            "value": [
                3000.0, 655.0, 80.0, 2000.0, 2000.0, 0.0,
                0.035, 0.015, 0.05, 0.10, 0.02, 0.12, 0.62, 0.5
            ]
        }
        df_macro = pd.DataFrame(defaults).set_index("parameter")

    rec_path = dp / "recurring_expenses.csv"
    if not rec_path.exists() and (dp / "templates" / "recurring_expenses.csv").exists():
        rec_path = dp / "templates" / "recurring_expenses.csv"

    if rec_path.exists():
        df_recurring = pd.read_csv(rec_path).dropna(how="all")
    else:
        df_recurring = pd.DataFrame(columns=["name", "min_cost", "max_cost", "probability", "inflation_type"])

    shocks_path = dp / "scheduled_shocks.csv"
    if not shocks_path.exists() and (dp / "templates" / "scheduled_shocks.csv").exists():
        shocks_path = dp / "templates" / "scheduled_shocks.csv"

    if shocks_path.exists():
        df_shocks = pd.read_csv(shocks_path).dropna(how="all")
    else:
        df_shocks = pd.DataFrame(columns=["name", "date", "amount", "tag"])

    if "tag" not in df_shocks.columns:
        df_shocks["tag"] = "altro"

    return df_macro, df_recurring, df_shocks


# ============================================================
# GESTIONE MODIFICHE MANUALI (OVERRIDES), UNDO & PERSISTENZA
# ============================================================

def make_tx_key(date: Any, account_id: str, amount: float, description: str) -> str:
    """Genera una chiave univoca stabile per identificare una specifica transazione bancaria."""
    d_str = str(date)[:10] if date is not None else "nodate"
    amt_str = f"{float(amount):.2f}"
    desc_clean = re.sub(r"\s+", " ", str(description).strip())[:30]
    return f"{d_str}_{account_id}_{amt_str}_{desc_clean}"


def get_user_overrides_path() -> Path:
    """Restituisce il percorso assoluto del file delle modifiche utente JSON."""
    for base in [Path("input"), Path.cwd() / "input", Path(__file__).resolve().parent.parent / "input"]:
        if base.exists():
            return base / "user_overrides.json"
    return Path("input/user_overrides.json")


def load_user_overrides() -> Dict[str, Any]:
    """Carica le modifiche manuali dell'utente dal file JSON locale persistente."""
    path = get_user_overrides_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "balance_overrides": data.get("balance_overrides", {}),
                    "category_overrides": data.get("category_overrides", {}),
                    "transfer_flags": data.get("transfer_flags", {}),
                    "excluded_transactions": data.get("excluded_transactions", []),
                    "manual_transactions": data.get("manual_transactions", []),
                }
        except Exception as e:
            print(f"[WARN] Impossibile leggere {path}: {e}")
    return {
        "balance_overrides": {},
        "category_overrides": {},
        "transfer_flags": {},
        "excluded_transactions": [],
        "manual_transactions": [],
    }


def save_user_overrides(overrides: Dict[str, Any]) -> bool:
    """Salva le modifiche manuali dell'utente su file JSON locale persistente."""
    path = get_user_overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Impossibile salvare {path}: {e}")
        return False


def delete_statement_file(filename: Union[str, Path]) -> bool:
    """
    Elimina fisicamente un file estratto conto da disco (bank_statements, investments o wallet)
    e restituisce True se il file è stato rimosso con successo.
    """
    p = Path(filename)
    if p.is_file() and p.exists():
        try:
            p.unlink()
            return True
        except Exception as e:
            print(f"[ERROR] Errore cancellazione file {p}: {e}")
            return False

    clean_name = p.name
    deleted = False
    for folder_rel in [Path("input/bank_statements"), Path("input/investments"), Path("input/wallet")]:
        for base_p in [folder_rel, Path.cwd() / folder_rel, Path(__file__).resolve().parent.parent / folder_rel]:
            target = base_p / clean_name
            if target.exists() and target.is_file():
                try:
                    target.unlink()
                    deleted = True
                except Exception as e:
                    print(f"[ERROR] Errore cancellazione file {target}: {e}")
    return deleted


def apply_user_overrides(
    statements: List[BankStatement],
    summary: PortfolioSummary,
    overrides: Optional[Dict[str, Any]] = None
) -> Tuple[List[BankStatement], PortfolioSummary]:
    """
    Applica tutte le personalizzazioni e correzioni manuali (saldi, categorie modificate,
    giroconti forzati, transazioni escluse, movimenti manuali aggiuntivi) e ricalcola
    il riepilogo consolidato del portafoglio.
    """
    if overrides is None:
        overrides = load_user_overrides()

    bal_overrides = overrides.get("balance_overrides", {})
    cat_overrides = overrides.get("category_overrides", {})
    tr_flags = overrides.get("transfer_flags", {})
    excluded_keys = set(overrides.get("excluded_transactions", []))
    manual_txs = overrides.get("manual_transactions", [])

    # 1. Modifica manuale dei saldi finali dei singoli conti
    if bal_overrides:
        for stmt in statements:
            if stmt.account_id in bal_overrides:
                try:
                    stmt.ending_balance = float(bal_overrides[stmt.account_id])
                except (ValueError, TypeError):
                    pass

    # 2. Aggregazione transazioni con assegnazione chiavi univoche
    all_tx_list = []
    for stmt in statements:
        if stmt.transactions is not None and not stmt.transactions.empty:
            df_stmt = stmt.transactions.copy()
            if "account_id" not in df_stmt.columns:
                df_stmt["account_id"] = stmt.account_id
            if "institution" not in df_stmt.columns:
                df_stmt["institution"] = stmt.institution
            all_tx_list.append(df_stmt)

    if all_tx_list:
        df_all = pd.concat(all_tx_list, ignore_index=True)
    else:
        df_all = pd.DataFrame(columns=["date", "amount", "currency", "description", "category", "account_id", "institution"])

    # 3. Iniezione movimenti manuali creati dall'utente
    if manual_txs:
        df_man = pd.DataFrame(manual_txs)
        if "date" in df_man.columns:
            df_man["date"] = pd.to_datetime(df_man["date"]).dt.normalize()
        df_all = pd.concat([df_all, df_man], ignore_index=True)

    # 4. Applicazione chiavi, categorie modificate ed esclusioni
    if not df_all.empty:
        df_all["tx_key"] = df_all.apply(
            lambda r: make_tx_key(r.get("date"), r.get("account_id", ""), r.get("amount", 0.0), r.get("description", "")),
            axis=1
        )
        if excluded_keys:
            df_all = df_all[~df_all["tx_key"].isin(excluded_keys)].copy()

        for idx, r in df_all.iterrows():
            k = r["tx_key"]
            if k in cat_overrides:
                df_all.at[idx, "category"] = cat_overrides[k]
            if k in tr_flags:
                df_all.at[idx, "is_internal_transfer"] = bool(tr_flags[k])

    # 5. Ricalcolo PortfolioAggregator con i nuovi saldi e transazioni
    agg = PortfolioAggregator(statements)
    new_summary = agg.aggregate()
    new_summary.all_transactions = df_all

    return statements, new_summary

