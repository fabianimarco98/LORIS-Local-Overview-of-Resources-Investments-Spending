# ============================================================
# LORIS SERVICE — pipeline condivisa da Streamlit, CLI, API e agente
# ============================================================
"""
Un solo punto per: caricare estratti conto -> applicare le modifiche dell'utente ->
categorizzare -> statistiche -> previsione Monte Carlo. Evita che le tre interfacce
calcolino numeri diversi dagli stessi dati (soglie, PAC, tassi, override).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import bank_data_manager as bdm
import simulation_engine as se

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATEMENTS_DIR = PROJECT_ROOT / "input" / "bank_statements"

# Parametri di previsione di default (unici per tutte le interfacce)
FORECAST_DEFAULTS: Dict[str, Any] = {
    "horizon_months": 36,
    "n_sims": 3000,
    "seed": 42,
    "monthly_investment": 100.0,
    "annual_return_pct": 5.0,
    "annual_inflation_pct": 2.5,
    "cash_rate_pct": 2.5,
    "strategy": "dynamic",
    "cash_threshold": 5000.0,
    "tax_rate": 0.26,
}


@dataclass
class PortfolioData:
    statements: List[Any]
    summary: Any
    df_tx: pd.DataFrame            # transazioni categorizzate (giroconti e scelte utente applicati)
    stats: Dict[str, Any]          # statistiche mensili retrospettive
    load_warnings: List[str] = field(default_factory=list)

    @property
    def cash(self) -> float:
        return float(self.summary.total_liquid_cash + self.summary.total_high_yield_cash)

    @property
    def is_empty(self) -> bool:
        return self.summary.all_transactions.empty


def build_portfolio_data(statements: List[Any], summary: Any) -> PortfolioData:
    """Dati derivati (categorie, statistiche) a partire da statements + summary già caricati."""
    df_tx = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
    return PortfolioData(statements, summary, df_tx, bdm.compute_bank_monthly_statistics(df_tx),
                         list(getattr(summary, "load_warnings", [])))


def load_portfolio(
    statements_dir: Optional[Any] = None,
    as_of_date: Optional[str] = None,
    apply_overrides: bool = True,
    overrides: Optional[Dict[str, Any]] = None,
) -> PortfolioData:
    """Carica da disco, applica le modifiche utente salvate (input/user_overrides.json) e deriva le statistiche."""
    folder = str(statements_dir if statements_dir is not None else DEFAULT_STATEMENTS_DIR)
    statements, summary = bdm.load_all_bank_statements(folder, as_of_date=as_of_date)
    if apply_overrides:
        statements, summary = bdm.apply_user_overrides(statements, summary, overrides)
    return build_portfolio_data(statements, summary)


def run_forecast(data: PortfolioData, **params: Any) -> Dict[str, Any]:
    """
    Monte Carlo calibrato sui dati reali (reddito, spesa media e volatilità dagli estratti).
    Qualsiasi parametro di FORECAST_DEFAULTS o di calibrazione (starting_cash, starting_inv,
    monthly_income, monthly_expenses_mean, monthly_expenses_std, start, shock_scale) può essere sovrascritto.
    """
    p = {**FORECAST_DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    stats, summary = data.stats, data.summary
    res = se.run_simulation(
        start=p.get("start") or se.default_start(),
        horizon_months=int(p["horizon_months"]),
        n_sims=int(p["n_sims"]),
        seed=int(p["seed"]),
        pac=float(p["monthly_investment"]),
        strategy=p["strategy"],
        cash_threshold=float(p["cash_threshold"]),
        monthly_income=float(p.get("monthly_income", stats.get("detected_salary", 0.0))),
        starting_cash=float(p.get("starting_cash", data.cash)),
        starting_inv=float(p.get("starting_inv", summary.total_investments)),
        cash_rate=float(p["cash_rate_pct"]) / 100.0,
        mkt_mean=float(p["annual_return_pct"]) / 100.0,
        infl_mean=float(p["annual_inflation_pct"]) / 100.0,
        monthly_expenses_mean=float(p.get("monthly_expenses_mean", stats.get("monthly_expenses_mean", 0.0))),
        monthly_expenses_std=float(p.get("monthly_expenses_std", stats.get("monthly_expenses_std", 0.0))),
        tax_rate=float(p["tax_rate"]),
        shock_scale=float(p.get("shock_scale", 1.0)),
        recurring_df=None,
        shocks_df=None,
    )
    res["params"] = p
    return res
