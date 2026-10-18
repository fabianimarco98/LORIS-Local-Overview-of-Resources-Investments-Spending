# ============================================================
# BANKING MODULE — NET WORTH SNAPSHOTS (storico del patrimonio)
# ============================================================
"""
Storico del patrimonio inserito a mano (tipicamente ogni ~3 mesi).

Funziona anche senza estratti conto: l'utente definisce le proprie voci (conti, broker,
contanti, immobili...) e registra periodicamente un valore per ciascuna. Se una voce è
collegata a un conto degli estratti (`linked_account_id`), il valore può essere
precompilato dal saldo calcolato da PortfolioAggregator.

Persistenza: `input/net_worth.json` (gitignored), scritto in modo atomico.
Percorso modificabile con la variabile d'ambiente LORIS_NET_WORTH (test, profili multipli).
"""

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .portfolio import ASSET_CLASS_LABELS

SCHEMA_VERSION = 1
DEFAULT_STALE_DAYS = 90
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class Holding:
    id: str
    name: str
    asset_class: str = "OTHER"
    institution: str = ""
    currency: str = "EUR"          # informativo: i valori vanno inseriti già convertiti in EUR
    notes: str = ""
    linked_account_id: Optional[str] = None
    archived: bool = False         # archiviata = non compare nei nuovi aggiornamenti, lo storico resta


@dataclass
class Snapshot:
    date: str                      # ISO YYYY-MM-DD
    values: Dict[str, float] = field(default_factory=dict)   # holding_id -> valore in EUR
    note: str = ""


@dataclass
class NetWorthStore:
    holdings: List[Holding] = field(default_factory=list)
    snapshots: List[Snapshot] = field(default_factory=list)


def default_path() -> Path:
    env = os.environ.get("LORIS_NET_WORTH", "").strip()
    return Path(env) if env else _PROJECT_ROOT / "input" / "net_worth.json"


# ---------- validazione ----------

def _parse_iso_date(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Data non valida (atteso YYYY-MM-DD): {value!r}") from exc


def _clean_amount(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Importo non valido: {value!r}") from exc
    if not math.isfinite(amount):
        raise ValueError(f"Importo non valido: {value!r}")
    return round(amount, 2)


def _active_ids(store: NetWorthStore) -> set:
    return {h.id for h in store.holdings if not h.archived}


# ---------- persistenza ----------

def load(path: Optional[Any] = None) -> NetWorthStore:
    """Carica lo store. File assente = store vuoto; file corrotto = ValueError (mai perdita silenziosa)."""
    p = Path(path) if path is not None else default_path()
    if not p.exists():
        return NetWorthStore()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p.name} non è un JSON valido: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{p.name}: formato non riconosciuto")
    holdings = [Holding(**{k: v for k, v in h.items() if k in Holding.__dataclass_fields__})
                for h in raw.get("holdings", [])]
    snapshots = [Snapshot(date=_parse_iso_date(s["date"]),
                          values={str(k): _clean_amount(v) for k, v in s.get("values", {}).items()},
                          note=str(s.get("note", "")))
                 for s in raw.get("snapshots", [])]
    snapshots.sort(key=lambda s: s.date)
    return NetWorthStore(holdings, snapshots)


def save(store: NetWorthStore, path: Optional[Any] = None) -> Path:
    """Scrittura atomica: file temporaneo nella stessa cartella, poi os.replace."""
    p = Path(path) if path is not None else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "holdings": [asdict(h) for h in store.holdings],
        "snapshots": [asdict(s) for s in sorted(store.snapshots, key=lambda s: s.date)],
    }
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p


# ---------- modifica ----------

def add_holding(store: NetWorthStore, holding_id: str, name: str, asset_class: str = "OTHER",
                **kwargs: Any) -> Holding:
    holding_id = str(holding_id).strip()
    if not holding_id or not str(name).strip():
        raise ValueError("id e nome della voce sono obbligatori")
    if any(h.id == holding_id for h in store.holdings):
        raise ValueError(f"Voce già esistente: {holding_id}")
    if asset_class not in ASSET_CLASS_LABELS:
        raise ValueError(f"Classe di asset sconosciuta: {asset_class}")
    h = Holding(id=holding_id, name=str(name).strip(), asset_class=asset_class, **kwargs)
    store.holdings.append(h)
    return h


def unique_holding_id(store: NetWorthStore, name: str) -> str:
    """Id stabile derivato dal nome ("Conto Principale" -> "conto_principale"), con suffisso se già usato."""
    base = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "voce"
    taken = {h.id for h in store.holdings}
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def archive_holding(store: NetWorthStore, holding_id: str, archived: bool = True) -> None:
    for h in store.holdings:
        if h.id == holding_id:
            h.archived = archived
            return
    raise ValueError(f"Voce sconosciuta: {holding_id}")


def add_snapshot(store: NetWorthStore, snap_date: Any, values: Dict[str, Any], note: str = "") -> Snapshot:
    """Aggiunge (o sostituisce, a parità di data) uno snapshot. Solo voci attive e valori finiti."""
    iso = _parse_iso_date(snap_date)
    active = _active_ids(store)
    cleaned: Dict[str, float] = {}
    for hid, val in values.items():
        if hid not in active:
            raise ValueError(f"Voce sconosciuta o archiviata: {hid}")
        cleaned[hid] = _clean_amount(val)
    if not cleaned:
        raise ValueError("Uno snapshot richiede almeno un valore")
    snap = Snapshot(date=iso, values=cleaned, note=str(note))
    store.snapshots = [s for s in store.snapshots if s.date != iso] + [snap]
    store.snapshots.sort(key=lambda s: s.date)
    return snap


# ---------- precompilazione dagli estratti ----------

def prefill_from_portfolio(store: NetWorthStore, summary: Any) -> Dict[str, float]:
    """Valori suggeriti per le voci attive collegate a un conto degli estratti (saldo di `summary`)."""
    acc = getattr(summary, "accounts_summary", None)
    if acc is None or acc.empty:
        return {}
    if "is_tracker" in acc.columns:
        acc = acc[~acc["is_tracker"]]
    balances = acc.set_index("account_id")["balance"].to_dict()
    return {h.id: round(float(balances[h.linked_account_id]), 2)
            for h in store.holdings
            if not h.archived and h.linked_account_id in balances}


# ---------- analisi ----------

def history_df(store: NetWorthStore) -> pd.DataFrame:
    """Una riga per (data, voce): date, holding_id, name, asset_class, value."""
    by_id = {h.id: h for h in store.holdings}
    rows = [{"date": s.date, "holding_id": hid, "name": by_id[hid].name if hid in by_id else hid,
             "asset_class": by_id[hid].asset_class if hid in by_id else "OTHER", "value": val}
            for s in store.snapshots for hid, val in s.values.items()]
    return pd.DataFrame(rows, columns=["date", "holding_id", "name", "asset_class", "value"])


def totals_by_class(store: NetWorthStore) -> pd.DataFrame:
    """Pivot data x asset_class con colonna `total`."""
    df = history_df(store)
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot_table(index="date", columns="asset_class", values="value", aggfunc="sum", fill_value=0.0)
    pivot["total"] = pivot.sum(axis=1)
    return pivot.sort_index()


def deltas(store: NetWorthStore) -> pd.DataFrame:
    """Per ogni snapshot: totale, variazione assoluta e % rispetto al precedente (NaN sul primo)."""
    pivot = totals_by_class(store)
    if pivot.empty:
        return pd.DataFrame(columns=["date", "total", "delta", "delta_pct"])
    out = pd.DataFrame({"date": pivot.index, "total": pivot["total"].values})
    out["delta"] = out["total"].diff()
    prev = out["total"].shift(1)
    out["delta_pct"] = (out["delta"] / prev.where(prev != 0)) * 100.0
    return out


def days_since_last(store: NetWorthStore, today: Optional[Any] = None) -> Optional[int]:
    """Giorni dall'ultimo snapshot (None se non ce ne sono)."""
    if not store.snapshots:
        return None
    ref = datetime.strptime(_parse_iso_date(today), "%Y-%m-%d").date() if today else date.today()
    return (ref - datetime.strptime(store.snapshots[-1].date, "%Y-%m-%d").date()).days


def is_update_due(store: NetWorthStore, stale_days: int = DEFAULT_STALE_DAYS, today: Optional[Any] = None) -> bool:
    """True se non ci sono snapshot o l'ultimo è più vecchio di `stale_days`."""
    days = days_since_last(store, today)
    return days is None or days > stale_days
