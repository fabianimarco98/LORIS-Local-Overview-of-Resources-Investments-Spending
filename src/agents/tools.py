# ============================================================
# AGENT TOOLS — registro tool a sola lettura con validazione schema
# ============================================================
"""
Ogni tool è una funzione pura sul `PortfolioContext` (dati già in memoria). Nessun tool
scrive su disco, apre rete o modifica le impostazioni: l'agente può solo LEGGERE.
Gli argomenti proposti dal modello vengono validati (tipo, enum, pattern, range) e gli
errori tornano al modello come risultato strutturato, così può correggersi da solo.
Le descrizioni delle transazioni sono sempre passate dal PIIScrubber.
"""

from dataclasses import dataclass, field
import json
import math
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
DATE_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"
MAX_RESULT_CHARS = 6000
_EMPTY_STRINGS = {"", "null", "none", "nil", "undefined", "n/a", "na"}


# ------------------------------------------------------------
# Tool & registry
# ------------------------------------------------------------
@dataclass
class Tool:
    name: str
    description: str
    properties: Dict[str, Dict[str, Any]]
    fn: Callable[..., Any]
    required: List[str] = field(default_factory=list)

    def schema(self) -> Dict[str, Any]:
        """Formato `tools` di Ollama / OpenAI."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": self.required,
                },
            },
        }

    def signature(self) -> str:
        """Firma compatta per i messaggi d'errore, es. spending_by_category(month?: string, top_n?: integer)."""
        parts = [f"{k}{'' if k in self.required else '?'}: {v.get('type', 'string')}" for k, v in self.properties.items()]
        return f"{self.name}({', '.join(parts)}); ometti gli argomenti opzionali che non servono"

    def validate(self, args: Any) -> Tuple[Dict[str, Any], Optional[str]]:
        """Ritorna (argomenti puliti, messaggio d'errore o None)."""
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return {}, "gli argomenti devono essere un oggetto JSON"
        if not isinstance(args, dict):
            return {}, "gli argomenti devono essere un oggetto JSON"

        unknown = sorted(set(args) - set(self.properties))
        if unknown:
            return {}, f"argomenti sconosciuti: {unknown}; ammessi: {sorted(self.properties)}"
        missing = [r for r in self.required
                   if args.get(r) is None or str(args.get(r)).strip().lower() in _EMPTY_STRINGS]
        if missing:
            return {}, f"argomenti obbligatori mancanti: {missing}. Firma: {self.signature()}"

        clean: Dict[str, Any] = {}
        for key, raw in args.items():
            # i modelli locali passano spesso "null"/"none" come stringa per "nessun valore"
            if raw is None or (isinstance(raw, str) and raw.strip().lower() in _EMPTY_STRINGS):
                continue
            spec = self.properties[key]
            try:
                value = _coerce(raw, spec)
            except (TypeError, ValueError) as e:
                return {}, f"argomento '{key}' non valido: {e}. Firma: {self.signature()}"
            clean[key] = value
        return clean, None


def _coerce(raw: Any, spec: Dict[str, Any]) -> Any:
    typ = spec.get("type", "string")
    if typ == "integer":
        if isinstance(raw, bool):
            raise ValueError("atteso un intero")
        value: Any = int(float(raw))
    elif typ == "number":
        if isinstance(raw, bool):
            raise ValueError("atteso un numero")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("numero non finito")
    elif typ == "string":
        value = str(raw).strip()
        if "pattern" in spec and not re.match(spec["pattern"], value):
            raise ValueError(f"'{value}' non rispetta il formato richiesto ({spec.get('format_hint', spec['pattern'])})")
    else:
        raise ValueError(f"tipo non supportato: {typ}")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"valore ammesso solo tra {spec['enum']}")
    if "minimum" in spec and value < spec["minimum"]:
        raise ValueError(f"minimo {spec['minimum']}")
    if "maximum" in spec and value > spec["maximum"]:
        raise ValueError(f"massimo {spec['maximum']}")
    return value


@dataclass
class ToolResult:
    name: str
    args: Dict[str, Any]
    ok: bool
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_message(self, max_chars: int = MAX_RESULT_CHARS) -> str:
        payload = {"ok": True, "result": self.data} if self.ok else {"ok": False, "error": self.error}
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > max_chars:
            text = text[:max_chars] + '… [risultato troncato: restringi i filtri o riduci "limit"]'
        return text


class ToolRegistry:
    def __init__(self, tools: Optional[List[Tool]] = None):
        self._tools: Dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> List[str]:
        return list(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> List[Dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, args: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name, {}, False, error=f"tool '{name}' inesistente; disponibili: {self.names()}")
        clean, err = tool.validate(args)
        if err:
            return ToolResult(name, {}, False, error=err)
        started = time.perf_counter()
        try:
            data = _jsonable(tool.fn(**clean))
        except Exception as e:  # errore del tool: restituito al modello, mai propagato
            return ToolResult(name, clean, False, error=f"{type(e).__name__}: {e}",
                              elapsed_ms=(time.perf_counter() - started) * 1000)
        return ToolResult(name, clean, True, data=data, elapsed_ms=(time.perf_counter() - started) * 1000)


def _jsonable(obj: Any) -> Any:
    """Converte tipi numpy/pandas in tipi JSON (NaN/inf -> None)."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _jsonable(obj.reset_index().to_dict(orient="records"))
    if isinstance(obj, (pd.Timestamp, pd.Period)):
        return str(obj)[:10] if isinstance(obj, pd.Timestamp) else str(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return round(f, 2) if math.isfinite(f) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ------------------------------------------------------------
# Contesto portafoglio
# ------------------------------------------------------------
@dataclass
class PortfolioContext:
    summary: Any                      # PortfolioSummary
    df_tx: pd.DataFrame               # transazioni categorizzate (bdm.categorize_transactions)
    stats: Dict[str, Any]             # bdm.compute_bank_monthly_statistics
    cash_rate_pct: float = 2.5
    scrubber: Any = None

    def __post_init__(self):
        if self.scrubber is None:
            from banking.anonymizer import PIIScrubber
            self.scrubber = PIIScrubber()
        if not self.df_tx.empty:
            self.df_tx = self.df_tx.copy()
            self.df_tx["date"] = pd.to_datetime(self.df_tx["date"])

    @classmethod
    def from_summary(cls, summary: Any, cash_rate_pct: float = 2.5) -> "PortfolioContext":
        import bank_data_manager as bdm
        df = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
        return cls(summary, df, bdm.compute_bank_monthly_statistics(df), cash_rate_pct)

    def spending(self) -> pd.DataFrame:
        """Sole uscite, giroconti interni esclusi."""
        df = self.df_tx
        if df.empty:
            return df
        out = df[df["amount"] < 0]
        if "is_internal_transfer" in out.columns:
            out = out[~out["is_internal_transfer"].fillna(False).astype(bool)]
        return out


# ------------------------------------------------------------
# Tool finanziari
# ------------------------------------------------------------
def build_portfolio_registry(ctx: PortfolioContext) -> ToolRegistry:
    s = ctx.summary

    def get_portfolio_summary() -> Dict[str, Any]:
        return {
            "net_worth": s.total_net_worth,
            "liquid_cash": s.total_liquid_cash,
            "high_yield_cash": s.total_high_yield_cash,
            "investments": s.total_investments,
            "asset_allocation_pct": s.asset_allocation_pct,
            "monthly_burn_rate": s.monthly_burn_rate,
            "liquidity_buffer_months": s.liquidity_buffer_months,
            "internal_transfers_detected": int(len(s.internal_transfers)),
            # Dati poco affidabili (saldi che non quadrano, estratti mancanti o vecchi): l'assistente deve dirlo
            "data_quality_warnings": [ctx.scrubber.anonymize_text(str(w)) for w in list(getattr(s, "load_warnings", []) or [])[:8]],
        }

    def list_accounts() -> List[Dict[str, Any]]:
        acc = s.accounts_summary
        if acc is None or acc.empty:
            return []
        cols = [c for c in ("institution", "account_type", "asset_class_label", "balance", "currency", "tx_count") if c in acc.columns]
        return acc[cols].to_dict(orient="records")

    def monthly_cashflow(last_n_months: int = 12) -> Dict[str, Any]:
        flow = ctx.stats.get("monthly_cashflow")
        if flow is None or flow.empty:
            return {"months": [], "note": "nessun dato"}
        recent = flow.tail(last_n_months).round(2)
        return {
            "months": [{"month": str(idx), **row} for idx, row in recent.to_dict(orient="index").items()],
            "avg_monthly_expenses": ctx.stats.get("monthly_expenses_mean"),
            "detected_salary": ctx.stats.get("detected_salary"),
            "average_savings_rate_pct": ctx.stats.get("average_savings_rate"),
        }

    def spending_by_category(month: Optional[str] = None, top_n: int = 10) -> Dict[str, Any]:
        df = ctx.spending()
        if df.empty:
            return {"categories": [], "note": "nessuna spesa"}
        if month:
            df = df[df["date"].dt.strftime("%Y-%m") == month]
            if df.empty:
                return {"month": month, "categories": [], "note": "nessuna spesa in questo mese"}
        grp = df.groupby("category")["amount"].agg(total=lambda x: abs(x.sum()), operations="count")
        grp = grp.sort_values("total", ascending=False)
        total = float(grp["total"].sum())
        top = grp.head(top_n)
        return {
            "month": month or "tutto lo storico",
            "total_spent": total,
            "categories": [
                {"category": c, "total": r.total, "operations": int(r.operations),
                 "share_pct": (r.total / total * 100.0) if total else 0.0}
                for c, r in top.iterrows()
            ],
            "note": "giroconti interni esclusi",
        }

    def query_transactions(
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        category: Optional[str] = None, text: Optional[str] = None,
        direction: str = "any", min_amount: Optional[float] = None, max_amount: Optional[float] = None,
        sort: str = "date_desc", limit: int = 15,
    ) -> Dict[str, Any]:
        df = ctx.df_tx
        if df.empty:
            return {"count": 0, "transactions": []}
        mask = pd.Series(True, index=df.index)
        if start_date:
            mask &= df["date"] >= pd.Timestamp(start_date)
        if end_date:
            mask &= df["date"] <= pd.Timestamp(end_date)
        if category:
            mask &= df["category"].astype(str).str.lower() == category.lower()
        if text:
            mask &= df["description"].astype(str).str.contains(re.escape(text), case=False, na=False)
        if direction == "out":
            mask &= df["amount"] < 0
        elif direction == "in":
            mask &= df["amount"] > 0
        absamt = df["amount"].abs()
        if min_amount is not None:
            mask &= absamt >= min_amount
        if max_amount is not None:
            mask &= absamt <= max_amount
        sel = df[mask]
        key, asc = {"date_desc": ("date", False), "date_asc": ("date", True),
                    "amount_desc": ("amount_abs", False), "amount_asc": ("amount_abs", True)}[sort]
        sel = sel.assign(amount_abs=sel["amount"].abs()).sort_values(key, ascending=asc, kind="stable").head(limit)
        rows = [{
            "date": r["date"].strftime("%Y-%m-%d"),
            "amount": float(r["amount"]),
            "description": ctx.scrubber.anonymize_text(str(r.get("description", ""))),
            "category": r.get("category"),
            "internal_transfer": bool(r.get("is_internal_transfer", False)),
        } for _, r in sel.iterrows()]
        return {"count_matching": int(mask.sum()), "returned": len(rows), "transactions": rows}

    def find_recurring_expenses() -> Dict[str, Any]:
        import bank_data_manager as bdm
        rec = bdm.detect_recurring_from_statements(ctx.df_tx)
        return {"recurring": rec.head(20).to_dict(orient="records") if not rec.empty else []}

    def calculate_runway(extra_monthly_cost: float = 0.0) -> Dict[str, Any]:
        from banking.guardrails import FinancialToolRegistry
        cash = s.total_liquid_cash + s.total_high_yield_cash
        return FinancialToolRegistry.calculate_runway(cash, s.monthly_burn_rate + extra_monthly_cost)

    def simulate_pac(monthly_pac: float, years: int = 5, expected_annual_return_pct: float = 6.0) -> Dict[str, Any]:
        from banking.guardrails import FinancialToolRegistry
        return FinancialToolRegistry.simulate_pac_wealth(
            s.total_investments, monthly_pac, years, expected_annual_return_pct
        )

    def run_forecast(
        horizon_months: int = 24, n_sims: int = 1000, monthly_investment: float = 100.0,
        annual_return_pct: float = 5.0, annual_inflation_pct: float = 2.5,
        annual_volatility_pct: float = 15.0,
    ) -> Dict[str, Any]:
        import loris_service as svc
        data = svc.PortfolioData([], s, ctx.df_tx, ctx.stats)
        res = svc.run_forecast(
            data, horizon_months=horizon_months, n_sims=n_sims, monthly_investment=monthly_investment,
            annual_return_pct=annual_return_pct, annual_inflation_pct=annual_inflation_pct,
            annual_volatility_pct=annual_volatility_pct,
            cash_rate_pct=ctx.cash_rate_pct,
        )
        prm = res["params"]
        from forecast_analysis import risk_metrics
        risk = risk_metrics(res)
        return {
            "assumptions": {
                "start": str(res["start"])[:10], "horizon_months": res["months"], "n_sims": n_sims,
                "starting_cash": data.cash, "starting_investments": float(s.total_investments),
                "monthly_income": float(ctx.stats.get("detected_salary", 0.0)),
                "monthly_expenses_mean": float(ctx.stats.get("monthly_expenses_mean", 0.0)),
                "monthly_investment": prm["monthly_investment"], "annual_return_pct": prm["annual_return_pct"],
                "annual_volatility_pct": prm["annual_volatility_pct"], "annual_fee_pct": prm["annual_fee_pct"],
            },
            "net_worth_p5_pessimistic": res["p5"],
            "net_worth_p50_median": res["p50"],
            "net_worth_p95_optimistic": res["p95"],
            "net_worth_p50_in_today_euros": res["p50_real"],
            "probability_of_running_out_of_cash_pct": res["prob_ruin"],
            "probability_margin_of_error_pct_95": round(1.96 * res["prob_ruin_se"], 2),
            "expected_shortfall_5pct": risk["es5"],
            "max_drawdown_median_pct": risk["max_drawdown_median_pct"],
            "tax_country": prm["tax_country"],
        }

    def net_worth_history() -> Dict[str, Any]:
        import loris_service as svc
        hist = svc.get_net_worth_history()
        if not hist["snapshots"]:
            return {"snapshots": 0, "note": "nessun aggiornamento del patrimonio registrato"}
        names = {h["id"]: ctx.scrubber.anonymize_text(h["name"]) for h in hist["holdings"]}
        latest = hist["snapshots"][-1]
        return {
            "snapshots": len(hist["snapshots"]),
            "latest_date": latest["date"],
            "latest_values": [{"holding": names.get(k, k), "value": v} for k, v in latest["values"].items()],
            "totals_and_changes": hist["deltas"],
            "days_since_last_update": hist["days_since_last"],
            "update_due": hist["update_due"],
        }

    month_prop = {"type": "string", "pattern": MONTH_PATTERN, "format_hint": "YYYY-MM, es. 2026-09",
                  "description": "Mese nel formato YYYY-MM (es. 2026-09)"}
    date_prop = {"type": "string", "pattern": DATE_PATTERN, "format_hint": "YYYY-MM-DD, es. 2026-09-30"}

    return ToolRegistry([
        Tool("get_portfolio_summary",
             "Patrimonio netto, liquidità, investimenti, allocazione %, spesa media mensile (burn rate) e mesi di cuscinetto.",
             {}, get_portfolio_summary),
        Tool("list_accounts", "Elenco dei conti con istituto, tipo e saldo.", {}, list_accounts),
        Tool("monthly_cashflow",
             "Entrate, uscite, netto e tasso di risparmio per ciascun mese, più stipendio rilevato e spesa media.",
             {"last_n_months": {"type": "integer", "minimum": 1, "maximum": 60, "description": "Quanti mesi recenti (default 12)"}},
             monthly_cashflow),
        Tool("spending_by_category",
             "Spese per categoria (giroconti esclusi), per un mese o per tutto lo storico.",
             {"month": month_prop, "top_n": {"type": "integer", "minimum": 1, "maximum": 30}},
             spending_by_category),
        Tool("query_transactions",
             "Cerca transazioni con filtri. Descrizioni anonimizzate. Usa limit piccoli e filtri precisi.",
             {"start_date": date_prop, "end_date": date_prop,
              "category": {"type": "string"}, "text": {"type": "string", "description": "Testo contenuto nella descrizione"},
              "direction": {"type": "string", "enum": ["any", "in", "out"]},
              "min_amount": {"type": "number", "minimum": 0}, "max_amount": {"type": "number", "minimum": 0},
              "sort": {"type": "string", "enum": ["date_desc", "date_asc", "amount_desc", "amount_asc"]},
              "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
             query_transactions),
        Tool("find_recurring_expenses", "Spese fisse e ricorrenti rilevate (affitto, abbonamenti, bollette).",
             {}, find_recurring_expenses),
        Tool("calculate_runway",
             "Autonomia in mesi della liquidità alla spesa attuale, con riserva consigliata a 3 e 6 mesi.",
             {"extra_monthly_cost": {"type": "number", "minimum": 0, "description": "Costo mensile aggiuntivo da simulare"}},
             calculate_runway),
        Tool("simulate_pac",
             "Proiezione deterministica di un piano di accumulo (PAC) partendo dagli investimenti attuali.",
             {"monthly_pac": {"type": "number", "minimum": 0, "maximum": 100000},
              "years": {"type": "integer", "minimum": 1, "maximum": 40},
              "expected_annual_return_pct": {"type": "number", "minimum": -20, "maximum": 30}},
             simulate_pac, required=["monthly_pac"]),
        Tool("net_worth_history",
             "Storico del patrimonio registrato a mano (snapshot periodici): totali, variazioni e se serve un aggiornamento.",
             {}, net_worth_history),
        Tool("run_forecast",
             "Previsione Monte Carlo del patrimonio (P5/P50/P95 e probabilità di esaurire la cassa).",
             {"horizon_months": {"type": "integer", "minimum": 6, "maximum": 120},
              "n_sims": {"type": "integer", "minimum": 200, "maximum": 3000},
              "monthly_investment": {"type": "number", "minimum": 0, "maximum": 100000},
              "annual_return_pct": {"type": "number", "minimum": -20, "maximum": 30},
              "annual_volatility_pct": {"type": "number", "minimum": 0, "maximum": 60},
              "annual_inflation_pct": {"type": "number", "minimum": 0, "maximum": 20}},
             run_forecast),
    ])
