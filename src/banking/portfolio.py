# ============================================================
# BANKING MODULE — PORTFOLIO AGGREGATOR & FINANCIAL ANALYTICS
# ============================================================
"""
Motore di aggregazione patrimoniale multi-banca e statistiche finanziarie:
- Calcolo del Patrimonio Netto Totale (Net Worth) e ripartizione per Asset Class
- Asset Allocation (Liquid Cash, High-Yield Cash, ETF/Investimenti, Altro)
- Rilevamento automatico di giroconti e trasferimenti interni tra conti propri
- Metriche di resilienza finanziaria: Buffer di liquidità (mesi di copertura),
  burn rate mensile, rendimento medio ponderato della cassa
- Riconciliazione incrociata con il tracciamento storico Monefy
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from .parsers import BankStatement
from .user_profile import owner_names


ASSET_CLASS_LABELS = {
    "LIQUID_CASH": "Liquidità Immediata (Conti Correnti)",
    "HIGH_YIELD_CASH": "Liquidità Remunerata (Trade Republic / Depositi)",
    "INVESTMENTS": "Investimenti (ETF / PAC / Azioni)",
    "BONDS": "Obbligazioni & Titoli di Stato",
    "CRYPTO": "Criptovalute & Asset Alternativi",
    "EXPENSE_TRACKER": "App Spese & Contanti (Wallet / Tracciamento)",
    "OTHER": "Altro Patrimonio",
}

ASSET_CLASS_LABELS_EN = {
    "LIQUID_CASH": "Liquid Cash (Checking)",
    "HIGH_YIELD_CASH": "High-Yield Cash / Savings (Trade Republic)",
    "INVESTMENTS": "Investments (ETF / Equities)",
    "BONDS": "Bonds & Government Securities",
    "CRYPTO": "Cryptocurrency & Alternative Assets",
    "EXPENSE_TRACKER": "Expense Tracker & Cash (Wallet)",
    "OTHER": "Other Assets",
}


def get_asset_class_label(asset_class: str, lang: str = "it") -> str:
    """Restituisce l'etichetta localizzata per la classe di asset."""
    if lang == "en":
        return ASSET_CLASS_LABELS_EN.get(asset_class, ASSET_CLASS_LABELS.get(asset_class, asset_class))
    return ASSET_CLASS_LABELS.get(asset_class, asset_class)

ASSET_CLASS_COLORS = {
    "LIQUID_CASH": "#38bdf8",      # Azzurro
    "HIGH_YIELD_CASH": "#10b981",  # Verde smeraldo
    "INVESTMENTS": "#f59e0b",      # Oro / Ambra
    "BONDS": "#8b5cf6",            # Viola
    "CRYPTO": "#ec4899",           # Rosa
    "EXPENSE_TRACKER": "#a855f7",  # Viola ametista
    "OTHER": "#94a3b8",            # Grigio
}


@dataclass
class PortfolioSummary:
    total_net_worth: float
    total_liquid_cash: float
    total_high_yield_cash: float
    total_investments: float
    asset_allocation: Dict[str, float]       # asset_class -> ammontare €
    asset_allocation_pct: Dict[str, float]   # asset_class -> %
    accounts_summary: pd.DataFrame
    internal_transfers: pd.DataFrame
    all_transactions: pd.DataFrame
    monthly_burn_rate: float
    liquidity_buffer_months: float
    recommended_starting_cash: float
    reconciliation_monefy: Dict[str, Any] = field(default_factory=dict)
    has_wallet_tracker: bool = False
    wallet_summary: Dict[str, Any] = field(default_factory=dict)


class PortfolioAggregator:
    """Aggrega molteplici estratti conto ed esegue analisi patrimoniali."""

    def __init__(self, statements: Optional[List[BankStatement]] = None):
        self.statements: List[BankStatement] = statements or []

    def add_statement(self, statement: BankStatement):
        self.statements.append(statement)

    def clear(self):
        self.statements.clear()

    def aggregate(
        self,
        manual_account_balances: Optional[Dict[str, float]] = None,
        monefy_df: Optional[pd.DataFrame] = None,
        as_of_date: Optional[pd.Timestamp] = None
    ) -> PortfolioSummary:
        """
        Elabora tutti gli estratti conto caricati e calcola la panoramica patrimoniale completa.
        manual_account_balances: consente all'utente di sovrascrivere o integrare saldi puntuali.
        monefy_df: DataFrame di Monefy per la riconciliazione automatica.
        """
        manual_balances = manual_account_balances or {}

        # Consolidamento automatico di estratti conto multipli o a periodi consecutivi per lo stesso conto
        grouped_statements: Dict[str, List[BankStatement]] = {}
        for s in self.statements:
            grouped_statements.setdefault(s.account_id, []).append(s)

        effective_statements: List[BankStatement] = []
        for acc_id, group in grouped_statements.items():
            if len(group) == 1:
                effective_statements.append(group[0])
            else:
                # Ordina cronologicamente in base a data finale del documento o transazione massima
                group.sort(key=lambda x: (
                    x.end_date if x.end_date is not None else pd.Timestamp.min,
                    x.transactions["date"].max() if (not x.transactions.empty and "date" in x.transactions.columns) else pd.Timestamp.min
                ))
                latest_stmt = group[-1]
                all_txs_list = [x.transactions for x in group if not x.transactions.empty]
                if all_txs_list:
                    merged_tx = pd.concat(all_txs_list, ignore_index=True)
                    if "date" in merged_tx.columns and "amount" in merged_tx.columns and "description" in merged_tx.columns:
                        merged_tx = merged_tx.drop_duplicates(subset=["date", "amount", "description"]).sort_values("date").reset_index(drop=True)
                else:
                    merged_tx = pd.DataFrame()

                earliest_start = min((x.start_date for x in group if x.start_date is not None), default=None)
                all_sources = ", ".join(dict.fromkeys(x.source_file for x in group if x.source_file))
                combined_meta = latest_stmt.metadata.copy() if latest_stmt.metadata else {}
                combined_meta["multi_statement_count"] = len(group)

                cons_stmt = BankStatement(
                    account_id=acc_id,
                    institution=latest_stmt.institution,
                    account_type=latest_stmt.account_type,
                    asset_class=latest_stmt.asset_class,
                    currency=latest_stmt.currency,
                    start_date=earliest_start or latest_stmt.start_date,
                    end_date=latest_stmt.end_date,
                    starting_balance=group[0].starting_balance,
                    ending_balance=latest_stmt.ending_balance,
                    transactions=merged_tx,
                    source_file=all_sources,
                    metadata=combined_meta,
                )
                effective_statements.append(cons_stmt)

        # 1. Tabella di sintesi dei conti
        acc_rows = []
        all_tx_list = []
        wallet_meta_list = []

        for stmt in effective_statements:
            is_tracker = (stmt.asset_class == "EXPENSE_TRACKER" or stmt.account_type == "ExpenseTracker")

            tx = stmt.transactions.copy()
            if as_of_date is not None and not tx.empty and "date" in tx.columns:
                tx = tx[tx["date"] <= as_of_date].copy()

            # Saldo finale dal file o sovrascritto:
            # Per i tracker spese è SEMPRE 0.0 per non alterare il patrimonio bancario
            if is_tracker:
                bal = 0.0
            else:
                bal = manual_balances.get(stmt.account_id, stmt.ending_balance or 0.0)
                if as_of_date is not None and not tx.empty:
                    if "balance_after" in tx.columns and tx["balance_after"].notna().any():
                        bal = float(tx["balance_after"].dropna().iloc[-1])
                    elif stmt.ending_balance is None:
                        bal = float(tx["amount"].sum())

            # Calcolo spesa tracciata
            tracked_exp = 0.0
            if not tx.empty and "amount" in tx.columns:
                tracked_exp = float(abs(tx[tx["amount"] < 0]["amount"].sum()))

            acc_rows.append({
                "account_id": stmt.account_id,
                "institution": stmt.institution,
                "account_type": stmt.account_type,
                "asset_class": stmt.asset_class,
                "asset_class_label": ASSET_CLASS_LABELS.get(stmt.asset_class, stmt.asset_class),
                "balance": bal,
                "tracked_expenses": tracked_exp,
                "currency": stmt.currency,
                "tx_count": len(tx),
                "source_file": stmt.source_file,
                "is_tracker": is_tracker,
            })

            if not tx.empty:
                tx_copy = tx.copy()
                tx_copy["account_id"] = stmt.account_id
                tx_copy["institution"] = stmt.institution
                tx_copy["asset_class"] = stmt.asset_class
                tx_copy["is_tracker"] = is_tracker
                all_tx_list.append(tx_copy)

            if is_tracker and stmt.metadata:
                wallet_meta_list.append(stmt.metadata)

        df_accounts = pd.DataFrame(acc_rows)
        df_all_tx = pd.concat(all_tx_list, ignore_index=True) if all_tx_list else pd.DataFrame()

        if not df_all_tx.empty and "date" in df_all_tx.columns:
            df_all_tx = df_all_tx.sort_values("date").reset_index(drop=True)

        # 2. Rilevamento automatico trasferimenti interni (Giroconti)
        df_transfers = self._detect_internal_transfers(df_all_tx)

        # 3. Ripartizione per Asset Class escludendo i tracker di spesa dal Net Worth bancario reale
        real_accs = df_accounts[~df_accounts["is_tracker"]] if not df_accounts.empty and "is_tracker" in df_accounts.columns else df_accounts
        if not real_accs.empty:
            alloc = real_accs.groupby("asset_class")["balance"].sum().to_dict()
            total_nw = float(real_accs["balance"].sum())
        else:
            alloc = {}
            total_nw = 0.0

        # Garantisci chiavi base
        for ac in ["LIQUID_CASH", "HIGH_YIELD_CASH", "INVESTMENTS"]:
            alloc.setdefault(ac, 0.0)

        alloc_pct = {}
        for ac, val in alloc.items():
            alloc_pct[ac] = (val / total_nw * 100) if total_nw > 0 else 0.0

        liquid_cash = float(alloc.get("LIQUID_CASH", 0.0))
        high_yield = float(alloc.get("HIGH_YIELD_CASH", 0.0))
        investments = float(alloc.get("INVESTMENTS", 0.0))

        # 4. Burn rate e buffer di liquidità
        monthly_burn = self._compute_burn_rate(df_all_tx)
        total_cash_buffer = liquid_cash + high_yield
        buffer_months = max(0.0, (total_cash_buffer / monthly_burn)) if monthly_burn > 0 else 0.0

        # 5. Sintesi aggregata per Wallet / App Spese se presente
        has_wallet = len(wallet_meta_list) > 0 or (not df_all_tx.empty and "is_tracker" in df_all_tx.columns and df_all_tx["is_tracker"].any())
        w_summary = {}
        if has_wallet and not df_all_tx.empty and "is_tracker" in df_all_tx.columns:
            w_tx = df_all_tx[df_all_tx["is_tracker"]].copy()
            w_debits = w_tx[w_tx["amount"] < 0] if "amount" in w_tx.columns else pd.DataFrame()
            if not w_debits.empty and "is_cash" in w_debits.columns:
                is_cash_mask = w_debits["is_cash"].fillna(False).astype(bool)
                w_cash = w_debits[is_cash_mask]
                w_elec = w_debits[~is_cash_mask]
            else:
                w_cash = pd.DataFrame()
                w_elec = w_debits

            tot_w_exp = float(abs(w_debits["amount"].sum())) if not w_debits.empty else 0.0
            tot_w_cash = float(abs(w_cash["amount"].sum())) if not w_cash.empty else 0.0
            tot_w_elec = float(abs(w_elec["amount"].sum())) if not w_elec.empty else 0.0

            cat_group = {}
            if not w_debits.empty and "wallet_category" in w_debits.columns:
                cat_group = w_debits.groupby("wallet_category")["amount"].agg(lambda s: round(abs(float(s.sum())), 2)).to_dict()
            elif not w_debits.empty:
                cat_group = w_debits.groupby("category")["amount"].agg(lambda s: round(abs(float(s.sum())), 2)).to_dict()

            min_d = w_tx["date"].min().strftime("%Y-%m-%d") if not w_tx.empty and "date" in w_tx.columns and pd.notna(w_tx["date"].min()) else ""
            max_d = w_tx["date"].max().strftime("%Y-%m-%d") if not w_tx.empty and "date" in w_tx.columns and pd.notna(w_tx["date"].max()) else ""

            w_summary = {
                "total_expenses": round(tot_w_exp, 2),
                "cash_expenses": round(tot_w_cash, 2),
                "electronic_expenses": round(tot_w_elec, 2),
                "cash_ratio_pct": round((tot_w_cash / tot_w_exp * 100.0), 1) if tot_w_exp > 0 else 0.0,
                "tx_count": len(w_tx),
                "cash_tx_count": len(w_cash),
                "top_categories": dict(sorted(cat_group.items(), key=lambda x: x[1], reverse=True)),
                "date_range": (min_d, max_d),
            }

        # 6. Riconciliazione con Monefy se fornito
        reconcil_info = {}
        if monefy_df is not None and not monefy_df.empty:
            reconcil_info = self._reconcile_with_monefy(df_accounts, df_all_tx, monefy_df, as_of_date)

        # Cassa di partenza consigliata per macro_settings.csv (somma cassa liquida + remunerata)
        rec_starting_cash = total_cash_buffer

        return PortfolioSummary(
            total_net_worth=round(total_nw, 2),
            total_liquid_cash=round(liquid_cash, 2),
            total_high_yield_cash=round(high_yield, 2),
            total_investments=round(investments, 2),
            asset_allocation=alloc,
            asset_allocation_pct=alloc_pct,
            accounts_summary=df_accounts,
            internal_transfers=df_transfers,
            all_transactions=df_all_tx,
            monthly_burn_rate=round(monthly_burn, 2),
            liquidity_buffer_months=round(buffer_months, 1),
            recommended_starting_cash=round(rec_starting_cash, 2),
            reconciliation_monefy=reconcil_info,
            has_wallet_tracker=has_wallet,
            wallet_summary=w_summary,
        )

    def _detect_internal_transfers(self, df_tx: pd.DataFrame, days_tolerance: int = 4) -> pd.DataFrame:
        """
        Trova coppie di transazioni (un'uscita su Conto A e un'entrata su Conto B)
        che rappresentano lo stesso trasferimento interno (es. Girokonto -> Trade Republic).
        Esclude rigorosamente le spese personali (Wallet, contanti, pagamenti con carta o esercenti)
        e gli investimenti (PAC/ETF) per evitare falsi positivi.
        """
        if df_tx.empty or "amount" not in df_tx.columns or "account_id" not in df_tx.columns:
            return pd.DataFrame()

        TRANSFER_HINTS = {
            "transfer", "giroconto", "top up", "top-up", "ricarica", "bonifico", "deposit",
            "einzahlung", "auszahlung", "internal", "own account",
            "revolut", "trade republic", "erste", "sparkasse", "unicredit", "intesa",
            *owner_names(),
        }

        MERCHANT_HINTS = {
            "kartentransaktiontgtg", "burger king", "mcdonald", "deliveroo", "uber eats",
            "billa", "spar", "hofer", "lidl", "penny", "coop", "alilauro", "betfair"
        }

        def _has_transfer_hint(desc: Any, cat: Any, is_int: Any) -> bool:
            if bool(is_int):
                return True
            d_l = str(desc or "").lower()
            c_l = str(cat or "").lower()
            if any(h in c_l for h in ["giroconto", "transfer"]):
                return True
            return any(h in d_l for h in TRANSFER_HINTS)

        def _is_merchant(desc: Any) -> bool:
            d_l = str(desc or "").lower()
            return any(m in d_l for m in MERCHANT_HINTS)

        debits = df_tx[df_tx["amount"] < 0].copy()
        credits = df_tx[df_tx["amount"] > 0].copy()

        # Escludi app tracker spese e contanti (le spese su Wallet non sono bonifici bancari)
        if "is_tracker" in debits.columns:
            debits = debits[~debits["is_tracker"].fillna(False).astype(bool)]
        if "is_cash" in debits.columns:
            debits = debits[~debits["is_cash"].fillna(False).astype(bool)]
        if "is_tracker" in credits.columns:
            credits = credits[~credits["is_tracker"].fillna(False).astype(bool)]
        if "is_cash" in credits.columns:
            credits = credits[~credits["is_cash"].fillna(False).astype(bool)]

        # Escludi acquisti di investimenti (PAC, ETF)
        inv_cats = {"Investimento ETF / Azioni", "Investimenti & PAC"}
        if "category" in debits.columns:
            debits = debits[~debits["category"].isin(inv_cats)]
        if "description" in debits.columns:
            debits = debits[~debits["description"].str.lower().str.contains(r"savings plan|sparplan|handel|buy trade", regex=True, na=False)]

        matched = []
        used_credit_idx = set()

        for d_idx, d_row in debits.iterrows():
            target_amount = abs(d_row["amount"])
            d_date = d_row["date"]
            d_acc = d_row["account_id"]
            d_desc = d_row.get("description", "")
            d_cat = d_row.get("category", "")
            d_int = d_row.get("is_internal_transfer", False)

            if _is_merchant(d_desc):
                continue

            candidates = credits[
                (~credits.index.isin(used_credit_idx)) &
                (credits["account_id"] != d_acc) &
                (np.isclose(credits["amount"], target_amount, atol=0.01)) &
                (credits["date"] >= d_date - pd.Timedelta(days=days_tolerance)) &
                (credits["date"] <= d_date + pd.Timedelta(days=days_tolerance))
            ]

            for c_idx, c_row in candidates.iterrows():
                c_desc = c_row.get("description", "")
                c_cat = c_row.get("category", "")
                c_int = c_row.get("is_internal_transfer", False)

                if _is_merchant(c_desc):
                    continue

                # Per piccoli importi (< €100), esigi almeno un indizio testuale di giroconto
                if target_amount < 100.0:
                    if not (_has_transfer_hint(d_desc, d_cat, d_int) or _has_transfer_hint(c_desc, c_cat, c_int)):
                        continue

                used_credit_idx.add(c_idx)
                matched.append({
                    "date": d_date,
                    "from_date": d_date,
                    "to_date": c_row["date"],
                    "from_account": d_acc,
                    "to_account": c_row["account_id"],
                    "amount": target_amount,
                    "from_desc": d_desc,
                    "to_desc": c_desc,
                })
                break

        return pd.DataFrame(matched)

    def _compute_burn_rate(self, df_tx: pd.DataFrame) -> float:
        """Calcola la spesa media mensile reale (escludendo i giroconti interni)."""
        if df_tx.empty or "amount" not in df_tx.columns or "date" not in df_tx.columns:
            return 0.0

        # Esclude transazioni segnate come giroconto con gestione robusta dei nulli
        is_internal = df_tx["is_internal_transfer"].fillna(False).astype(bool) if "is_internal_transfer" in df_tx.columns else pd.Series(False, index=df_tx.index)
        spese = df_tx[(df_tx["amount"] < 0) & (~is_internal)].copy()
        if spese.empty:
            return 0.0

        # Se abbiamo sia estratti bancari che tracker spese, privilegia i conti bancari per il buffer di cassa liquida
        is_tr = spese["is_tracker"].fillna(False).astype(bool) if "is_tracker" in spese.columns else pd.Series(False, index=spese.index)
        bank_spese = spese[~is_tr]
        target_spese = bank_spese if not bank_spese.empty else spese

        target_spese = target_spese.copy()
        target_spese["month"] = pd.to_datetime(target_spese["date"]).dt.to_period("M")
        spese_m = target_spese.groupby("month")["amount"].sum().abs()
        if len(spese_m) > 0:
            return float(spese_m.mean())
        return 0.0

    def _reconcile_with_monefy(
        self,
        df_accounts: pd.DataFrame,
        df_tx: pd.DataFrame,
        monefy_df: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp]
    ) -> Dict[str, Any]:
        """
        Confronta il totale effettivo degli estratti conto bancari
        con il saldo Monefy per identificare scostamenti.
        """
        total_bank_cash = float(
            df_accounts[df_accounts["asset_class"].isin(["LIQUID_CASH", "HIGH_YIELD_CASH"])]["balance"].sum()
        ) if not df_accounts.empty else 0.0

        # Saldo teorico cumulato Monefy
        m_df = monefy_df.copy()
        if as_of_date is not None:
            m_df = m_df[m_df["date"] <= as_of_date]

        monefy_cash_implied = float(m_df["amount"].sum()) if not m_df.empty else 0.0
        discrepancy = total_bank_cash - monefy_cash_implied

        return {
            "total_bank_cash": round(total_bank_cash, 2),
            "monefy_cumulative_balance": round(monefy_cash_implied, 2),
            "discrepancy": round(discrepancy, 2),
            "is_aligned": abs(discrepancy) < 50.0,
            "message": (
                f"I conti bancari totalizzano €{total_bank_cash:,.2f} di liquidità disponibile. "
                f"Scostamento dal tracciamento cumulativo Monefy: €{discrepancy:+,.2f}."
            )
        }
