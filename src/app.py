# ============================================================
# EXPENSES PREDICTION & BANKING API — v4_speciale
# FastAPI REST backend indipendente da Monefy
# ============================================================
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import banking
from banking.anonymizer import PIIScrubber
from banking.local_llm import LocalLLMClient, RECOMMENDED_MODELS
from banking.parsers import parse_bank_statement
import bank_data_manager as bdm
import loris_service as svc
import simulation_engine as se

app = FastAPI(
    title="LORIS — Local Overview of Resources, Investments & Spending",
    version="4.0-LORIS",
    description="API REST headless per l'ingestion multi-banca, simulazione Monte Carlo e AI locale LORIS.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if (BASE_DIR.parent / "input").exists() else BASE_DIR
DATA_DIR = PROJECT_ROOT / "input"
STATEMENTS_DIR = DATA_DIR / "bank_statements"


class SimulationRequest(BaseModel):
    n_sims: int = Field(5000, ge=1, le=20000)
    start_date: Optional[str] = None
    pac: Optional[float] = None
    strategy: str = "dynamic"
    starting_cash: Optional[float] = None
    starting_inv: Optional[float] = None
    shock_scale: float = 1.0
    annual_return_pct: Optional[float] = Field(None, ge=-20, le=30)
    annual_volatility_pct: Optional[float] = Field(None, ge=0, le=60)
    annual_inflation_pct: Optional[float] = Field(None, ge=0, le=20)
    annual_fee_pct: Optional[float] = Field(None, ge=0, le=5)
    wage_growth_pct: Optional[float] = Field(None, ge=-10, le=20)


class LLMQueryRequest(BaseModel):
    question: str
    model: Optional[str] = None
    top_n_tx: int = 30


class PullModelRequest(BaseModel):
    model_tag: str


class AnonymizeRequest(BaseModel):
    text: str


@app.get("/api/health")
def health():
    llm = LocalLLMClient()
    st = llm.check_health()
    return {
        "status": "ok",
        "version": "v4_speciale",
        "local_llm_connected": st.is_available,
        "llm_provider": st.provider,
        "llm_model": st.model_name,
    }


@app.get("/api/portfolio")
def get_portfolio(as_of: Optional[str] = None):
    _data = svc.load_portfolio(as_of_date=as_of)
    summary = _data.summary
    return {
        "total_net_worth": summary.total_net_worth,
        "total_liquid_cash": summary.total_liquid_cash,
        "total_high_yield_cash": summary.total_high_yield_cash,
        "total_investments": summary.total_investments,
        "asset_allocation": summary.asset_allocation,
        "asset_allocation_pct": summary.asset_allocation_pct,
        "monthly_burn_rate": summary.monthly_burn_rate,
        "liquidity_buffer_months": summary.liquidity_buffer_months,
        "recommended_starting_cash": summary.recommended_starting_cash,
        "warnings": list(summary.load_warnings),
        "accounts_count": len(summary.accounts_summary),
        "accounts": summary.accounts_summary.to_dict(orient="records"),
        "internal_transfers_count": len(summary.internal_transfers),
    }


class SnapshotRequest(BaseModel):
    date: str
    values: Dict[str, float]
    note: str = ""


@app.get("/api/net-worth/history")
def get_net_worth_history(stale_days: int = Query(90, ge=1, le=3650)):
    try:
        return svc.get_net_worth_history(stale_days=stale_days)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/net-worth/snapshot")
def post_net_worth_snapshot(req: SnapshotRequest):
    try:
        return svc.record_snapshot(req.date, req.values, req.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/transactions")
def get_transactions(
    limit: int = Query(100, ge=1, le=1000),
    institution: Optional[str] = None,
    category: Optional[str] = None,
    anonymize: bool = False,
):
    _data = svc.load_portfolio()
    summary = _data.summary
    df = _data.df_tx

    if df.empty:
        return {"total": 0, "transactions": []}

    if institution:
        df = df[df["institution"] == institution]
    if category:
        df = df[df["category"] == category]

    df_sample = df.head(limit).copy()
    if anonymize:
        scrubber = PIIScrubber()
        df_sample = scrubber.anonymize_dataframe(df_sample, ["description"])

    if "date" in df_sample.columns:
        df_sample["date"] = pd.to_datetime(df_sample["date"]).dt.strftime("%Y-%m-%d")

    return {
        "total": len(df),
        "returned": len(df_sample),
        "transactions": df_sample.to_dict(orient="records"),
    }


@app.post("/api/simulate")
def run_simulation(req: SimulationRequest):
    _data = svc.load_portfolio()
    summary = _data.summary
    df_cat = _data.df_tx
    stats = _data.stats

    res = svc.run_forecast(
        _data,
        start=req.start_date,
        n_sims=req.n_sims,
        monthly_investment=req.pac,
        strategy=req.strategy,
        starting_cash=req.starting_cash,
        starting_inv=req.starting_inv,
        shock_scale=req.shock_scale,
        annual_return_pct=req.annual_return_pct,
        annual_volatility_pct=req.annual_volatility_pct,
        annual_inflation_pct=req.annual_inflation_pct,
        annual_fee_pct=req.annual_fee_pct,
        wage_growth_pct=req.wage_growth_pct,
    )

    tot_wealth = res["cash_history"] + res["invest_history"]
    terminal_wealth = tot_wealth[:, -1]

    return {
        "n_sims": req.n_sims,
        "months": len(res["dates"]),
        "dates": [d.strftime("%Y-%m-%d") for d in res["dates"]],
        "terminal_net_worth": {
            "p05": float(round(pd.Series(terminal_wealth).quantile(0.05), 2)),
            "p25": float(round(pd.Series(terminal_wealth).quantile(0.25), 2)),
            "median": float(round(pd.Series(terminal_wealth).median(), 2)),
            "p75": float(round(pd.Series(terminal_wealth).quantile(0.75), 2)),
            "p95": float(round(pd.Series(terminal_wealth).quantile(0.95), 2)),
        },
        "insolvency_risk_pct": float(round((res["cash_history"] < 0).any(axis=1).mean() * 100, 2)),
    }


@app.post("/api/llm/query")
def query_llm(req: LLMQueryRequest):
    _data = svc.load_portfolio()
    summary = _data.summary
    df = _data.df_tx

    scrubber = PIIScrubber()
    anon_df = scrubber.anonymize_dataframe(df.head(req.top_n_tx), ["description"]) if not df.empty else pd.DataFrame()

    llm = LocalLLMClient(preferred_model=req.model)
    answer = llm.query_portfolio_insights(
        portfolio_summary=summary,
        anonymized_transactions=anon_df,
        user_question=req.question,
    )

    return {"question": req.question, "model": llm.preferred_model, "answer": answer}


@app.get("/api/llm/models")
def list_models():
    """Restituisce lo stato del demone Ollama, i modelli installati e il catalogo consigliato."""
    llm = LocalLLMClient()
    st = llm.check_health()
    installed = llm.get_detailed_models()
    return {
        "is_available": st.is_available,
        "provider": st.provider,
        "active_model": st.model_name,
        "installed_models": installed,
        "recommended_models": RECOMMENDED_MODELS,
        "is_cli_installed": st.is_cli_installed,
        "cli_path": st.cli_path,
        "install_command": llm.get_install_instructions(),
    }


@app.post("/api/llm/pull")
def pull_model_endpoint(req: PullModelRequest):
    """Scarica e installa un modello in locale via Ollama."""
    llm = LocalLLMClient()
    ok, msg = llm.pull_model_sync(req.model_tag)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"status": "ok", "message": msg, "model": req.model_tag}


@app.post("/api/llm/start")
def start_ollama_daemon():
    """Avvia il demone Ollama in background se non è attivo."""
    llm = LocalLLMClient()
    ok, msg = llm.start_ollama_daemon()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"status": "ok", "message": msg}


@app.post("/api/anonymize")
def anonymize_text(req: AnonymizeRequest):
    scrubber = PIIScrubber()
    clean_text = scrubber.anonymize_text(req.text)
    is_clean, leaks = scrubber.audit_cleanliness(clean_text)
    return {
        "original_length": len(req.text),
        "clean_text": clean_text,
        "is_clean": is_clean,
        "leaks_detected": leaks,
    }
