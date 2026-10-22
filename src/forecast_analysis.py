# ============================================================
# FORECAST ANALYSIS — rischio, fondo di emergenza, stress test, sensitività
# ============================================================
"""
Analisi costruite sopra `loris_service.run_forecast`, quindi con gli stessi dati, la stessa
calibrazione e le stesse imposte dell'app. Tutte le varianti (stress, tornado) usano lo stesso
seed: i numeri casuali sono comuni, quindi le differenze misurano l'effetto del parametro e non
il rumore Monte Carlo.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import bank_data_manager as bdm
import loris_service as svc

ES_LEVEL = 5.0   # Expected Shortfall: media degli scenari peggiori sotto il 5° percentile


def risk_metrics(res: Dict[str, Any], goal_amount: Optional[float] = None,
                 goal_month: Optional[int] = None) -> Dict[str, Any]:
    """
    Misure di rischio oltre ai percentili:
    - es5: Expected Shortfall (CVaR) 5%, patrimonio medio negli scenari sotto il 5° percentile
    - ruin_by_month: % cumulata di scenari con cassa negativa entro il mese m; median_months_to_ruin
    - max_drawdown_median_pct / _p95_pct: massima perdita dal picco del patrimonio (al netto imposte)
    - goal: probabilità di avere almeno `goal_amount` al mese `goal_month` (default: fine orizzonte)
      e di averlo raggiunto almeno una volta entro quel mese
    - errori standard Monte Carlo delle probabilità
    """
    nw_final = np.asarray(res["nw_final"], dtype=float)
    cutoff = np.percentile(nw_final, ES_LEVEL)
    out: Dict[str, Any] = {
        "var5": float(cutoff),
        "es5": float(nw_final[nw_final <= cutoff].mean()),
    }

    below = np.asarray(res["cash_history"]) < 0
    ever = np.maximum.accumulate(below, axis=1)
    out["ruin_by_month"] = (ever.mean(axis=0) * 100.0).tolist()
    first = np.where(below.any(axis=1), below.argmax(axis=1) + 1, 0)
    ruined = first[first > 0]
    out["median_months_to_ruin"] = float(np.median(ruined)) if len(ruined) else None
    out["prob_ruin"] = float(res["prob_ruin"])
    out["prob_ruin_se"] = float(res.get("prob_ruin_se", 0.0))

    wealth = np.asarray(res["nw_history"], dtype=float)
    wealth = np.concatenate([np.full((wealth.shape[0], 1), float(res["initial_nw"])), wealth], axis=1)
    peak = np.maximum.accumulate(wealth, axis=1)
    dd = np.where(peak > 0, (peak - wealth) / np.where(peak > 0, peak, 1.0), 0.0)
    max_dd = dd.max(axis=1) * 100.0
    out["max_drawdown_median_pct"] = float(np.median(max_dd))
    out["max_drawdown_p95_pct"] = float(np.percentile(max_dd, 95))

    if goal_amount is not None:
        months = wealth.shape[1] - 1
        idx = months if goal_month is None else int(min(max(goal_month, 1), months))
        window = wealth[:, 1:idx + 1]
        p_end = float((window[:, -1] >= goal_amount).mean())
        p_ever = float((window.max(axis=1) >= goal_amount).mean())
        out["goal"] = {
            "amount": float(goal_amount), "month": idx,
            "prob_at_month_pct": p_end * 100.0,
            "prob_ever_pct": p_ever * 100.0,
            "prob_at_month_se_pct": float(np.sqrt(p_end * (1 - p_end) / len(window)) * 100.0),
        }
    return out


def emergency_fund(data: svc.PortfolioData, res: Dict[str, Any], months: int = 6) -> Dict[str, Any]:
    """
    Autonomia sulle sole spese essenziali e cassa consigliata: 95° percentile della spesa
    cumulata dei primi `months` mesi simulati (copre anche i mesi eccezionali, non solo la media).
    """
    essential = bdm.essential_monthly_spend(data.df_tx)
    cash = float(data.cash)
    exp = np.asarray(res["expenses"])
    k = min(months, exp.shape[1])
    recommended = float(np.percentile(exp[:, :k].sum(axis=1), 95))
    return {
        "current_cash": cash,
        "essential_monthly": essential,
        "runway_months_essential": cash / essential if essential > 0 else None,
        "window_months": k,
        "recommended_cash_p95": recommended,
        "gap": max(recommended - cash, 0.0),
    }


# ------------------------------------------------------------ scenari di stress

def _spread(total_return: float, months: int) -> List[float]:
    """Rendimento totale ripartito in rate mensili uguali (geometriche)."""
    return [(1.0 + total_return) ** (1.0 / months) - 1.0] * months


def _annual_to_monthly(rate: float, months: int) -> List[float]:
    return [(1.0 + rate) ** (1.0 / 12.0) - 1.0] * months


# Percorsi stilizzati di eventi reali. Chi versa ogni mese compra durante il crollo: un calo seguito da un
# rimbalzo rapido può ESSERE favorevole a fine orizzonte, per questo la tabella riporta anche il minimo
# raggiunto dal patrimonio e il drawdown, che mostrano il danno durante la crisi.
_GFC_2008 = _spread(-0.52, 17) + _spread(0.50, 19)     # picco-minimo ~ -50% in 17 mesi, ritorno ai massimi dopo anni

STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "gfc_2008": {
        "label_it": "Crisi finanziaria 2008", "label_en": "2008 financial crisis",
        "params": {"market_shock_path": _GFC_2008},
    },
    "covid_2020": {
        "label_it": "Crollo Covid 2020 (a V)", "label_en": "2020 Covid crash (V-shaped)",
        "params": {"market_shock_path": [-0.12, -0.20] + _spread(0.40, 10)},
    },
    "inflation_2022": {
        "label_it": "Inflazione 2022 (8%, poi 4%)", "label_en": "2022 inflation (8% then 4%)",
        "params": {"inflation_shock_path": _annual_to_monthly(0.08, 12) + _annual_to_monthly(0.04, 12),
                   "market_shock_path": _spread(-0.18, 12)},
    },
    "job_loss": {
        "label_it": "Perdita del lavoro per 6 mesi", "label_en": "6 months without income",
        "params": {"income_gap": (0, 6)},
    },
    "crisis_and_job_loss": {
        "label_it": "Crisi 2008 + 6 mesi senza reddito", "label_en": "2008 crisis + 6 months without income",
        "params": {"market_shock_path": _GFC_2008, "income_gap": (0, 6)},
    },
}


def run_stress_tests(data: svc.PortfolioData, **params: Any) -> pd.DataFrame:
    """Base + scenari di stress applicati al modello calibrato sui dati reali (partono dal primo mese)."""
    rows = []
    base = svc.run_forecast(data, **params)
    entries = [("base", "Scenario base", "Base case", base)]
    for key, sc in STRESS_SCENARIOS.items():
        entries.append((key, sc["label_it"], sc["label_en"], svc.run_forecast(data, **{**params, **sc["params"]})))
    for key, label_it, label_en, r in entries:
        rm = risk_metrics(r)
        rows.append({
            "scenario": key, "label_it": label_it, "label_en": label_en,
            "p5": r["p5"], "p50": r["p50"], "p95": r["p95"],
            "delta_p50": r["p50"] - base["p50"],
            "trough_p50": float(np.median(np.asarray(r["nw_history"]).min(axis=1))),
            "max_drawdown_median_pct": rm["max_drawdown_median_pct"],
            "prob_ruin": r["prob_ruin"], "prob_ruin_se": r["prob_ruin_se"],
            "prob_forced_sale": r["prob_forced_sale"],
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------ sensitività (tornado)

def run_tornado(data: svc.PortfolioData, metric: str = "p50", n_sims: int = 1500,
                **params: Any) -> Tuple[pd.DataFrame, float]:
    """
    Sensitività del patrimonio finale (`metric`) a ±variazioni dei parametri chiave, ricavate dai
    valori effettivi (non da importi fissi). Ritorna (tabella ordinata per ampiezza, valore base).
    """
    p = {**svc.FORECAST_DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    stats = data.stats
    income = float(p.get("monthly_income", stats.get("detected_salary", 0.0)))
    spend = float(p.get("monthly_expenses_mean", stats.get("monthly_expenses_mean", 0.0)))

    def pct(label: str, key: str, base: float, rel: float) -> Optional[tuple]:
        if base <= 0:
            return None
        return (f"{label} (−{rel:.0%} ↔ +{rel:.0%})", key, base * (1 - rel), base * (1 + rel))

    def points(label: str, key: str, base: float, delta: float, unit: str = "pt") -> tuple:
        return (f"{label} ({max(base - delta, 0):g}% ↔ {base + delta:g}%)", key, max(base - delta, 0.0), base + delta)

    variations = [v for v in [
        pct("Reddito mensile", "monthly_income", income, 0.10),
        pct("Spesa mensile", "monthly_expenses_mean", spend, 0.10),
        points("Rendimento mercato", "annual_return_pct", float(p["annual_return_pct"]), 2.0),
        points("Volatilità mercato", "annual_volatility_pct", float(p["annual_volatility_pct"]), 5.0),
        points("Inflazione", "annual_inflation_pct", float(p["annual_inflation_pct"]), 1.0),
        points("Interesse liquidità", "cash_rate_pct", float(p["cash_rate_pct"]), 1.0),
        pct("Versamento mensile PAC", "monthly_investment", float(p["monthly_investment"]), 0.50),
    ] if v is not None]

    fixed = {**params, "n_sims": n_sims, "monthly_income": income, "monthly_expenses_mean": spend}
    base_val = svc.run_forecast(data, **fixed)[metric]
    rows = []
    for label, key, lo, hi in variations:
        r_lo = svc.run_forecast(data, **{**fixed, key: lo})[metric]
        r_hi = svc.run_forecast(data, **{**fixed, key: hi})[metric]
        rows.append({"parametro": label, "chiave": key, "valore_basso": lo, "valore_alto": hi,
                     "delta_low": float(r_lo - base_val), "delta_high": float(r_hi - base_val),
                     "range": float(abs(r_hi - r_lo)), "p50_low": float(r_lo), "p50_high": float(r_hi)})
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("range", ascending=False).reset_index(drop=True)
    return table, float(base_val)
