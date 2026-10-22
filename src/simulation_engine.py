# ============================================================
# SIMULATION ENGINE — Monte Carlo, Stochastic Wealth Forecasting
# ============================================================
"""
Motore di simulazione stocastica Monte Carlo universale per finanza personale:
- Proiezione patrimonio netto (Fan Chart percentili 5°, 25°, 50°, 75°, 95°)
- Traiettorie congiunte: Liquidità (Conto corrente) vs Investimenti (ETF / Titoli)
- Calibrazione empirica automatica dai dati reali degli estratti conto
- Rischio di scoperto di liquidità (Ruin Probability / Cash Depletion)
- Orizzonte temporale flessibile (12, 24, 36, 60 mesi o orizzonte personalizzato)
- Rendimenti azionari log-normali (o Student-t) e inflazione stocastica per scenario
- Crescita salariale e costi di prodotto (TER) esplicitati
- Gestione shock finanziari programmati e liquidazione forzata con fiscalità
"""

import hashlib
from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np
import pandas as pd
from pathlib import Path

# Orizzonte di default quando non specificato
DEFAULT_HORIZON_MONTHS = 36
DEFAULT_TAX_RATE = 0.26
EXTRA_MONTHS = (3, 6, 9, 12)   # solo per macro_df con salary_phase_*_extra (compatibilità)


def lognormal_monthly_params(annual_mean: float, annual_std: float) -> Tuple[float, float]:
    """
    Parametri (mu, sigma) del log-rendimento MENSILE tali che il rendimento annuo semplice
    abbia media `annual_mean` e deviazione standard `annual_std` (E[1+R] = 1+mean, esatto).
    Un rendimento normale con media geometrica fissata renderebbe in media circa mean - std²/2.
    """
    gross = max(1.0 + annual_mean, 1e-6)
    s2 = np.log1p((max(annual_std, 0.0) / gross) ** 2)
    return (np.log(gross) - s2 / 2.0) / 12.0, float(np.sqrt(s2 / 12.0))


def standardized_shocks(rng: np.random.Generator, size: int, tail_df: Optional[float]) -> np.ndarray:
    """Shock a media 0 e varianza 1: normali, oppure Student-t (code grasse) riscalate."""
    if tail_df is None:
        return rng.standard_normal(size)
    if tail_df <= 2:
        raise ValueError("market_tail_df deve essere > 2 (varianza finita)")
    return rng.standard_t(tail_df, size) / np.sqrt(tail_df / (tail_df - 2.0))


def sim_months(start: Union[str, pd.Timestamp], end: Optional[Union[str, pd.Timestamp]] = None) -> int:
    """Calcola il numero di mesi tra la data di inizio e la data di destinazione."""
    s = pd.to_datetime(start)
    if end is not None:
        e = pd.to_datetime(end)
    else:
        return DEFAULT_HORIZON_MONTHS
    m = (e.year - s.year) * 12 + (e.month - s.month) + 1
    return max(1, m)


def default_start() -> str:
    """Primo giorno del mese successivo a oggi (data di partenza di default delle proiezioni)."""
    return (pd.Timestamp.today().normalize() + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d")


def run_simulation(
    start: Optional[Union[str, pd.Timestamp]] = None,
    horizon_months: Optional[int] = None,
    end_date: Optional[Union[str, pd.Timestamp]] = None,
    n_sims: int = 5000,
    seed: int = 42,
    pac: Optional[float] = None,
    strategy: str = "fixed",
    cash_threshold: float = 6000.0,
    min_chunk: float = 300.0,
    monthly_income: Optional[float] = None,
    salary1: Optional[float] = None,
    salary2: Optional[float] = None,
    extra_phase1: Optional[float] = None,
    extra_phase2: Optional[float] = None,
    bonus_months: Optional[Tuple[int, ...]] = None,
    bonus_amount: Optional[float] = None,
    infl_mean: Optional[float] = None,
    infl_std: Optional[float] = None,
    mkt_mean: Optional[float] = None,
    mkt_std: Optional[float] = None,
    starting_cash: Optional[float] = None,
    starting_inv: Optional[float] = None,
    cash_rate: Optional[float] = None,
    tax_rate: Optional[float] = None,
    recurring_df: Optional[pd.DataFrame] = None,
    shocks_df: Optional[pd.DataFrame] = None,
    shock_scale: float = 1.0,
    market_monthly: Optional[np.ndarray] = None,
    inflation_monthly: Optional[np.ndarray] = None,
    expense_common_std: Optional[float] = None,
    expense_common_rho: Optional[float] = None,
    overdraft_rate: Optional[float] = None,
    macro_df: Optional[pd.DataFrame] = None,
    monthly_expenses_mean: Optional[float] = None,
    monthly_expenses_std: Optional[float] = None,
    wage_growth: Optional[float] = None,
    annual_fee: Optional[float] = None,
    market_tail_df: Optional[float] = None,
    phase2_start: Optional[Union[str, pd.Timestamp]] = None,
) -> Dict[str, Any]:
    """
    Esegue la simulazione Monte Carlo su N scenari per l'orizzonte temporale specificato.
    Accetta parametri derivati empiricamente dagli estratti conto o configurazioni custom.

    wage_growth: crescita annua del reddito (aumento una volta l'anno); default = inflazione attesa,
        cioè potere d'acquisto del reddito costante. 0 = reddito nominale fisso.
    annual_fee: costi annui di prodotto (TER) sottratti al rendimento degli investimenti.
    market_tail_df: gradi di libertà della Student-t per i rendimenti (None = log-normale).
    phase2_start: dal quale mese vale `salary2` (None = non esiste una seconda fase).
    """
    start_dt = pd.to_datetime(start if start is not None else default_start())

    # 1. Determinazione orizzonte temporale in mesi
    if horizon_months is not None and horizon_months > 0:
        months = int(horizon_months)
    elif end_date is not None:
        months = sim_months(start_dt, end_date)
    else:
        months = DEFAULT_HORIZON_MONTHS
    months = max(1, months)

    dates = pd.date_range(start=start_dt, periods=months, freq="MS")

    # 2. Defaults e parametri macroeconomici
    P = macro_df["value"].astype(float) if macro_df is not None else {}
    pac = float(P.get("monthly_investment", 0.0) if pac is None else pac)

    # Entrate mensili
    if monthly_income is not None:
        inc_base = float(monthly_income)
        # Se l'utente specifica il suo reddito mensile atteso,
        # usa un reddito costante senza iniettare scatti o bonus a meno che richiesti
        sal2 = float(salary2) if salary2 is not None else inc_base
        extra1 = float(extra_phase1) if extra_phase1 is not None else 0.0
        extra2 = float(extra_phase2) if extra_phase2 is not None else 0.0
    elif salary1 is not None:
        inc_base = float(salary1)
        sal2 = float(salary2) if salary2 is not None else inc_base
        extra1 = float(extra_phase1) if extra_phase1 is not None else 0.0
        extra2 = float(extra_phase2) if extra_phase2 is not None else 0.0
    else:
        inc_base = float(P.get("salary_phase_1", 0.0))
        sal2 = float(P.get("salary_phase_2", inc_base) if salary2 is None else salary2)
        extra1 = float(P.get("salary_phase_1_extra", 0.0) if extra_phase1 is None else extra_phase1)
        extra2 = float(P.get("salary_phase_2_extra", 0.0 if macro_df is None else 0.0) if extra_phase2 is None else extra_phase2)

    infl_mean = float(P.get("annual_inflation_mean", 0.025) if infl_mean is None else infl_mean)
    infl_std = float(P.get("annual_inflation_std", 0.015) if infl_std is None else infl_std)
    mkt_mean = float(P.get("annual_market_return_mean", 0.06) if mkt_mean is None else mkt_mean)
    mkt_std = float(P.get("annual_market_return_std", 0.12) if mkt_std is None else mkt_std)

    starting_cash = float(P.get("starting_cash", 0.0) if starting_cash is None else starting_cash)
    starting_inv = float(P.get("starting_investments", 0.0) if starting_inv is None else starting_inv)
    cash_rate = float(P.get("cash_interest_gross", 0.015) if cash_rate is None else cash_rate)
    eff_tax_rate = float(P.get("capital_gains_tax", DEFAULT_TAX_RATE) if tax_rate is None else tax_rate)
    wage_growth = infl_mean if wage_growth is None else float(wage_growth)
    annual_fee = float(P.get("annual_fee", 0.0) if annual_fee is None else annual_fee)
    fee_factor_m = (1.0 - annual_fee) ** (1 / 12)
    phase2_dt = pd.to_datetime(phase2_start) if phase2_start is not None else None
    mu_log_m, sd_log_m = lognormal_monthly_params(mkt_mean, mkt_std)

    # Con volatilità empirica (monthly_expenses_std dagli estratti) lo shock comune è già incluso nella std osservata:
    # applicarlo di nuovo gonfierebbe rischio e probabilità di esaurire la cassa.
    _empirical_vol = (recurring_df is None or recurring_df.empty) and monthly_expenses_std is not None
    exp_common_std = float(P.get("expense_common_std", 0.0 if _empirical_vol else 0.40) if expense_common_std is None else expense_common_std)
    exp_common_rho = float(P.get("expense_common_rho", 0.45) if expense_common_rho is None else expense_common_rho)
    overdraft_rate = float(P.get("overdraft_rate_annual", 0.10) if overdraft_rate is None else overdraft_rate)

    innov_std = exp_common_std * np.sqrt(max(0.0, 1 - exp_common_rho ** 2))
    cash_rate_m = (1 + cash_rate * (1 - eff_tax_rate)) ** (1 / 12) - 1
    overdraft_rate_m = (1 + overdraft_rate) ** (1 / 12) - 1

    # Preparazione spese ricorrenti
    rec = recurring_df.to_dict("records") if recurring_df is not None and not recurring_df.empty else []

    # Preparazione shock
    shock_by_month = {}
    if shocks_df is not None and not shocks_df.empty:
        _sh = shocks_df.copy()
        _sh["dt"] = pd.to_datetime(_sh["date"])
        for _, r in _sh.iterrows():
            m_idx = (r["dt"].year - start_dt.year) * 12 + (r["dt"].month - start_dt.month)
            if 0 <= m_idx < months:
                shock_by_month[m_idx] = shock_by_month.get(m_idx, 0.0) + float(r["amount"]) * shock_scale

    rng = np.random.default_rng(seed)
    cash = np.full(n_sims, starting_cash, dtype=float)
    invest = np.full(n_sims, starting_inv, dtype=float)
    cost_basis = np.full(n_sims, starting_inv, dtype=float)

    cash_h = np.zeros((n_sims, months))
    inv_h = np.zeros((n_sims, months))
    exp_h = np.zeros((n_sims, months))
    int_h = np.zeros((n_sims, months))
    liq_h = np.zeros((n_sims, months))
    cb_h = np.zeros((n_sims, months))
    income_sched = np.zeros(months)

    price_level = np.ones(n_sims)       # livello dei prezzi PER SCENARIO (l'inflazione è incerta)
    year_level = np.ones(n_sims)
    log_common = np.zeros(n_sims)

    for m in range(months):
        date = dates[m]

        # 1. Inflazione stocastica
        if inflation_monthly is not None:
            minf = inflation_monthly[:, m]
        else:
            _mu_inf = (1 + infl_mean) ** (1 / 12) - 1
            _sd_inf = infl_std / np.sqrt(12)
            minf = rng.normal(_mu_inf, _sd_inf, n_sims)

        price_level = price_level * (1 + minf)
        if m > 0 and date.month == 1:
            year_level = price_level.copy()

        # 2. Rendimento di mercato stocastico
        if market_monthly is not None:
            mret = market_monthly[:, m]
        else:
            mret = np.expm1(mu_log_m + sd_log_m * standardized_shocks(rng, n_sims, market_tail_df))

        # 3. Interessi di cassa / scoperto
        interest = np.where(cash >= 0, cash * cash_rate_m, cash * overdraft_rate_m)
        cash = cash + interest
        int_h[:, m] = interest

        # 4. Entrate del mese
        is_p2 = phase2_dt is not None and date >= phase2_dt
        inc = sal2 if is_p2 else inc_base
        if bonus_months is not None:
            if date.month in bonus_months:
                inc += (bonus_amount if bonus_amount is not None else 0.0)
        else:
            # Compatibilità: se macro_df presente o extra definiti
            if date.month in EXTRA_MONTHS and (extra1 > 0 or extra2 > 0):
                inc += extra2 if is_p2 else extra1

        inc *= (1 + wage_growth) ** (m // 12)
        income_sched[m] = inc
        cash = cash + inc

        # 5. PAC (Piano di Accumulo Capitale)
        pac_m = np.where(cash >= pac, pac, 0.0)   # non si investe denaro che non c'è
        cash = cash - pac_m
        invest = invest * (1 + mret) * fee_factor_m + pac_m
        cost_basis = cost_basis + pac_m

        # 6. Spese del mese
        eps = rng.normal(0, innov_std, n_sims)
        log_common = exp_common_rho * log_common + eps
        common_factor = np.exp(log_common - exp_common_std ** 2 / 2)

        exp = np.zeros(n_sims)
        if rec:
            for r in rec:
                occurs = rng.random(n_sims) < r.get("probability", 1.0)
                raw = rng.uniform(r.get("min_cost", 0.0), r.get("max_cost", 0.0), n_sims)
                mult = price_level if r.get("inflation_type") == "continuous" else year_level
                exp += raw * mult * occurs
        else:
            # Calibrazione empirica diretta al 100% da estratti conto
            _mean = monthly_expenses_mean if monthly_expenses_mean is not None else 1300.0
            _std = monthly_expenses_std if monthly_expenses_std is not None else 200.0
            exp = rng.normal(_mean, _std, n_sims)
            exp = np.maximum(exp, 0.0) * price_level

        exp = exp * common_factor

        # 7. Shock programmati
        if m in shock_by_month:
            exp = exp + shock_by_month[m] * price_level

        cash = cash - exp

        # 8. Strategia dinamica di investimento dell'eccesso di cassa
        if strategy == "dynamic":
            excess = cash - cash_threshold
            extra_inv = np.where(excess >= min_chunk, excess, 0.0)
            cash = cash - extra_inv
            invest = invest + extra_inv
            cost_basis = cost_basis + extra_inv

        # 9. Liquidazione forzata se cash < 0: si vende abbastanza da coprire il fabbisogno AL NETTO delle imposte
        need = np.clip(-cash, 0, None)
        gain_frac = np.divide(invest - cost_basis, invest, out=np.zeros_like(invest), where=invest > 0)
        gain_frac = np.clip(gain_frac, 0.0, 1.0)
        net_per_unit = 1.0 - gain_frac * eff_tax_rate          # incasso netto per ogni € venduto
        sell = np.minimum(need / np.maximum(net_per_unit, 1e-6), invest)
        do_sell = sell > 0
        if do_sell.any():
            tax = sell * gain_frac * eff_tax_rate
            proceeds = sell - tax
            frac_sold = np.divide(sell, invest, out=np.zeros_like(invest), where=invest > 0)
            cash = cash + proceeds
            cost_basis = cost_basis - cost_basis * frac_sold
            invest = invest - sell

        liq_h[:, m] = sell
        cash_h[:, m] = cash
        inv_h[:, m] = invest
        cb_h[:, m] = cost_basis
        exp_h[:, m] = exp

    gains = np.maximum(0, invest - cost_basis)
    nw_final = cash + invest - gains * eff_tax_rate
    nw_final_real = nw_final / price_level      # deflazionato con il livello prezzi di ciascuno scenario

    p5, p10, p25, p50, p75, p90, p95 = np.percentile(nw_final, [5, 10, 25, 50, 75, 90, 95])
    p10r, p50r, p90r = np.percentile(nw_final_real, [10, 50, 90])

    return {
        "dates": dates,
        "months": months,
        "start": start_dt,
        "cash": cash_h,
        "invest": inv_h,
        "expenses": exp_h,
        "interest": int_h,
        "cash_history": cash_h,
        "invest_history": inv_h,
        "total_wealth_history": cash_h + inv_h,
        "nw_history": cash_h + inv_h - np.maximum(0.0, inv_h - cb_h) * eff_tax_rate,   # al netto delle imposte latenti
        "liquidated": liq_h,
        "income": income_sched,
        "nw": cash_h + inv_h,
        "nw_final": nw_final,
        "nw_final_real": nw_final_real,
        "price_level_final": float(price_level.mean()),
        "price_level_paths": price_level,
        "p5": float(p5),
        "p10": float(p10),
        "p25": float(p25),
        "p50": float(p50),
        "p75": float(p75),
        "p90": float(p90),
        "p95": float(p95),
        "p10_real": float(p10r),
        "p50_real": float(p50r),
        "p90_real": float(p90r),
        "prob_ruin": float((cash_h.min(axis=1) < 0).mean() * 100),
        "prob_forced_sale": float((liq_h.sum(axis=1) > 0).mean() * 100),
        "initial_nw": float(starting_cash + starting_inv),
    }


def run_historical_backtest(recurring_df, shocks_df, macro_df, start="2026-10-01", horizon_months=None):
    """Backtest storico usando serie reali S&P 500 e CPI dal 1970."""
    ANNI = np.arange(1970, 2025)
    SP500 = np.array([
        4.0, 14.3, 19.0, -14.7, -26.5, 37.2, 23.8, -7.2, 6.6, 18.4,
        32.4, -4.9, 21.5, 22.6, 6.3, 31.7, 18.7, 5.3, 16.6, 31.7,
        -3.1, 30.5, 7.6, 10.1, 1.3, 37.6, 23.0, 33.4, 28.6, 21.0,
        -9.1, -11.9, -22.1, 28.7, 10.9, 4.9, 15.8, 5.5, -37.0, 26.5,
        15.1, 2.1, 16.0, 32.4, 13.7, 1.4, 12.0, 21.8, -4.4, 31.5,
        18.4, 28.7, -18.1, 26.3, 25.0,
    ]) / 100
    CPI = np.array([
        5.8, 4.3, 3.3, 6.2, 11.1, 9.1, 5.7, 6.5, 7.6, 11.3,
        13.5, 10.3, 6.1, 3.2, 4.3, 3.5, 1.9, 3.7, 4.1, 4.8,
        5.4, 4.2, 3.0, 3.0, 2.6, 2.8, 2.9, 2.3, 1.6, 2.2,
        3.4, 2.8, 1.6, 2.3, 2.7, 3.4, 3.2, 2.8, 3.8, -0.4,
        1.6, 3.2, 2.1, 1.5, 1.6, 0.1, 1.3, 2.1, 2.4, 1.8,
        1.2, 4.7, 8.0, 4.1, 3.0,
    ]) / 100

    sp500_m = (1 + np.repeat(SP500, 12)) ** (1 / 12) - 1
    cpi_m = (1 + np.repeat(CPI, 12)) ** (1 / 12) - 1
    n_months_hist = len(sp500_m)
    months = horizon_months if horizon_months else sim_months(start)

    # Finestre sovrapposte
    n_windows = max(1, n_months_hist - months + 1)
    mkt_mat = np.array([sp500_m[i:i + months] for i in range(n_windows)])
    inf_mat = np.array([cpi_m[i:i + months] for i in range(n_windows)])

    res_backtest = run_simulation(start=start, horizon_months=months, n_sims=n_windows, seed=42,
                                  recurring_df=recurring_df, shocks_df=shocks_df,
                                  macro_df=macro_df,
                                  market_monthly=mkt_mat, inflation_monthly=inf_mat)

    # Finestre disgiunte
    step = months
    disjoint_starts = list(range(0, n_months_hist - months + 1, step))
    mkt_dis = np.array([sp500_m[i:i + months] for i in disjoint_starts])
    inf_dis = np.array([cpi_m[i:i + months] for i in disjoint_starts])
    res_disjoint = run_simulation(start=start, horizon_months=months, n_sims=len(disjoint_starts), seed=42,
                                  recurring_df=recurring_df, shocks_df=shocks_df,
                                  macro_df=macro_df,
                                  market_monthly=mkt_dis, inflation_monthly=inf_dis)

    return res_backtest, res_disjoint


def run_tornado_analysis(recurring_df, shocks_df, macro_df, start="2026-10-01", horizon_months=None, n_sims=3000):
    """Analisi tornado di sensibilità sui parametri chiave."""
    base_res = run_simulation(start=start, horizon_months=horizon_months, n_sims=n_sims, seed=11,
                              recurring_df=recurring_df, shocks_df=shocks_df, macro_df=macro_df)
    base_p50 = base_res["p50"]

    def _rec_scaled(factor):
        if recurring_df is None or recurring_df.empty:
            return recurring_df
        r = recurring_df.copy()
        r["min_cost"] *= factor
        r["max_cost"] *= factor
        return r

    variations = [
        ("Spese ricorrenti (−10% ↔ +10%)", dict(recurring_df=_rec_scaled(0.9)), dict(recurring_df=_rec_scaled(1.1))),
        ("Shock programmati (−20% ↔ +20%)", dict(shock_scale=0.8), dict(shock_scale=1.2)),
        ("Entrate mensili (1.800€ ↔ 2.500€)", dict(monthly_income=1800), dict(monthly_income=2500)),
        ("Inflazione media (1,5% ↔ 4,5%)", dict(infl_mean=0.015), dict(infl_mean=0.045)),
        ("Rendimento mercato (2% ↔ 10%)", dict(mkt_mean=0.02), dict(mkt_mean=0.10)),
        ("Interesse liquidità (0% ↔ 3%)", dict(cash_rate=0.0), dict(cash_rate=0.03)),
        ("Volatilità mercato (8% ↔ 20%)", dict(mkt_std=0.08), dict(mkt_std=0.20)),
        ("Tasso di scoperto (5% ↔ 15%)", dict(overdraft_rate=0.05), dict(overdraft_rate=0.15)),
        ("PAC (0€ ↔ 250€)", dict(pac=0), dict(pac=250)),
    ]

    base_kwargs = dict(start=start, horizon_months=horizon_months, n_sims=n_sims, seed=11,
                       recurring_df=recurring_df, shocks_df=shocks_df, macro_df=macro_df)
    rows = []
    for label, low_kwargs, high_kwargs in variations:
        res_lo = run_simulation(**{**base_kwargs, **low_kwargs})
        res_hi = run_simulation(**{**base_kwargs, **high_kwargs})
        delta_lo = res_lo["p50"] - base_p50
        delta_hi = res_hi["p50"] - base_p50
        rows.append({
            "parametro": label,
            "delta_low": float(delta_lo),
            "delta_high": float(delta_hi),
            "range": float(abs(delta_hi - delta_lo)),
            "p50_low": float(res_lo["p50"]),
            "p50_high": float(res_hi["p50"]),
        })

    df_tornado = pd.DataFrame(rows).sort_values("range", ascending=False)
    return df_tornado, base_p50
