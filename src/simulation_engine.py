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
DEFAULT_TAX_RATE = 0.26        # solo ripiego del motore; il servizio usa il regime del paese (banking/tax.py)
MIN_BOOTSTRAP_MONTHS = 12      # sotto questa soglia la storia è troppo corta per un bootstrap
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


def _rescale_history(hist: np.ndarray, target_mean: Optional[float], target_std: Optional[float]) -> np.ndarray:
    """Riporta la storia alla media/deviazione richieste (se date), mai sotto zero."""
    m, s = float(hist.mean()), float(hist.std(ddof=1)) if len(hist) > 1 else 0.0
    out = hist.copy()
    if target_std is not None and s > 0:
        tm = m if target_mean is None else float(target_mean)
        out = tm + (hist - m) * (float(target_std) / s)
    elif target_mean is not None and m > 0:
        out = hist * (float(target_mean) / m)
    return np.maximum(out, 0.0)


def _binomial_se_pct(p: float, n: int) -> float:
    """Errore standard (in punti percentuali) di una probabilità stimata con n scenari."""
    return float(np.sqrt(max(p * (1.0 - p), 0.0) / max(n, 1)) * 100.0)


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
    cash_tax_rate: Optional[float] = None,
    securities_stamp: float = 0.0,
    account_stamp_eur: float = 0.0,
    account_stamp_threshold: float = 0.0,
    market_shock_path: Optional[Union[np.ndarray, List[float]]] = None,
    inflation_shock_path: Optional[Union[np.ndarray, List[float]]] = None,
    income_gap: Optional[Tuple[int, int]] = None,
    expense_history: Optional[Union[np.ndarray, List[float]]] = None,
    bootstrap_block: int = 3,
) -> Dict[str, Any]:
    """
    Esegue la simulazione Monte Carlo su N scenari per l'orizzonte temporale specificato.
    Accetta parametri derivati empiricamente dagli estratti conto o configurazioni custom.

    wage_growth: crescita annua del reddito (aumento una volta l'anno); default = inflazione attesa,
        cioè potere d'acquisto del reddito costante. 0 = reddito nominale fisso.
    annual_fee: costi annui di prodotto (TER) sottratti al rendimento degli investimenti.
    tax_rate: aliquota sulle plusvalenze; cash_tax_rate: aliquota sugli interessi (default = tax_rate).
    securities_stamp: imposta di bollo annua sul valore dei titoli; account_stamp_eur: bollo fisso annuo
        sulla liquidità quando il saldo supera account_stamp_threshold (addebitato a rate mensili).
    market_tail_df: gradi di libertà della Student-t per i rendimenti (None = log-normale).
    phase2_start: dal quale mese vale `salary2` (None = non esiste una seconda fase).
    market_shock_path / inflation_shock_path: rendimenti / inflazione MENSILI deterministici che
        sostituiscono quelli casuali nei primi len(path) mesi (scenari di stress); poi si torna al modello.
        I numeri casuali vengono comunque estratti, così scenari diversi restano confrontabili.
    income_gap: (mese di inizio, numero di mesi) in cui il reddito (bonus compresi) è zero.
    expense_history: spese mensili storiche (mesi completi, in euro di oggi). Con almeno
        MIN_BOOTSTRAP_MONTHS valori le spese simulate sono un block bootstrap della storia
        (blocchi di `bootstrap_block` mesi): conserva asimmetria, mesi eccezionali e
        autocorrelazione, che una normale i.i.d. perde. Se monthly_expenses_mean/std sono dati,
        la storia viene riscalata per avere esattamente quella media e deviazione standard.
        Non conserva la posizione nel calendario dei mesi stagionali.
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
    cash_tax = eff_tax_rate if cash_tax_rate is None else float(cash_tax_rate)
    fee_factor_m = ((1.0 - annual_fee) * (1.0 - securities_stamp)) ** (1 / 12)
    stamp_m = float(account_stamp_eur) / 12.0
    phase2_dt = pd.to_datetime(phase2_start) if phase2_start is not None else None
    mu_log_m, sd_log_m = lognormal_monthly_params(mkt_mean, mkt_std)
    mkt_path = None if market_shock_path is None else np.asarray(market_shock_path, dtype=float)
    infl_path = None if inflation_shock_path is None else np.asarray(inflation_shock_path, dtype=float)

    # Con volatilità empirica (monthly_expenses_std dagli estratti) lo shock comune è già incluso nella std osservata:
    # applicarlo di nuovo gonfierebbe rischio e probabilità di esaurire la cassa.
    no_recurring = recurring_df is None or recurring_df.empty
    hist = None
    if expense_history is not None and no_recurring:
        h = np.asarray(expense_history, dtype=float)
        h = h[np.isfinite(h)]
        if len(h) >= MIN_BOOTSTRAP_MONTHS:
            hist = _rescale_history(h, monthly_expenses_mean, monthly_expenses_std)
    _empirical_vol = no_recurring and (monthly_expenses_std is not None or hist is not None)
    exp_common_std = float(P.get("expense_common_std", 0.0 if _empirical_vol else 0.40) if expense_common_std is None else expense_common_std)
    exp_common_rho = float(P.get("expense_common_rho", 0.45) if expense_common_rho is None else expense_common_rho)
    overdraft_rate = float(P.get("overdraft_rate_annual", 0.10) if overdraft_rate is None else overdraft_rate)

    innov_std = exp_common_std * np.sqrt(max(0.0, 1 - exp_common_rho ** 2))
    cash_rate_m = (1 + cash_rate * (1 - cash_tax)) ** (1 / 12) - 1
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
    hist_paths = None
    if hist is not None:
        block = int(min(max(bootstrap_block, 1), len(hist)))
        n_blocks = -(-months // block)
        starts = rng.integers(0, len(hist) - block + 1, size=(n_sims, n_blocks))
        idx = np.repeat(starts, block, axis=1)[:, :months] + np.tile(np.arange(block), n_blocks)[:months]
        hist_paths = hist[idx]
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
        if infl_path is not None and m < len(infl_path):
            minf = np.full(n_sims, infl_path[m])

        price_level = price_level * (1 + minf)
        if m > 0 and date.month == 1:
            year_level = price_level.copy()

        # 2. Rendimento di mercato stocastico
        if market_monthly is not None:
            mret = market_monthly[:, m]
        else:
            mret = np.expm1(mu_log_m + sd_log_m * standardized_shocks(rng, n_sims, market_tail_df))
        if mkt_path is not None and m < len(mkt_path):
            mret = np.full(n_sims, mkt_path[m])

        # 3. Interessi di cassa / scoperto
        interest = np.where(cash >= 0, cash * cash_rate_m, cash * overdraft_rate_m)
        cash = cash + interest
        if stamp_m:
            cash = cash - np.where(cash > account_stamp_threshold, stamp_m, 0.0)
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
        if income_gap is not None and income_gap[0] <= m < income_gap[0] + income_gap[1]:
            inc = 0.0
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
        elif hist_paths is not None:
            exp = hist_paths[:, m] * price_level
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
        "prob_ruin_se": _binomial_se_pct((cash_h.min(axis=1) < 0).mean(), n_sims),
        "prob_forced_sale_se": _binomial_se_pct((liq_h.sum(axis=1) > 0).mean(), n_sims),
        "n_sims": int(n_sims),
        "initial_nw": float(starting_cash + starting_inv),
    }
