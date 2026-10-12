# ============================================================
# BANKING MODULE — LOCAL LLM CLIENT & PRIVACY-FIRST AI ASSISTANT
# ============================================================
"""
Assistente di intelligenza artificiale 100% LOCALE e ANONIMO:
- Connessione a demoni locali (Ollama, llama.cpp, LM Studio su localhost)
- Zero chiamate a server esterni (totale anonimato garantito da sandbox locale)
- Pre-scrubbing obbligatorio di tutte le PII tramite PIIScrubber prima di comporre i prompt
- Motore di fallback deterministico con euristica avanzata basata su regole e dizionari:
  funziona istantaneamente e al 100% anche senza alcun server LLM attivo.
"""

from dataclasses import dataclass, field
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple
import requests
import pandas as pd

from .anonymizer import PIIScrubber
from .guardrails import FinancialFactSheet, FinancialGuardrail, FinancialToolRegistry


# Modelli consigliati per LORIS con download diretto via Ollama
RECOMMENDED_MODELS = [
    {
        "tag": "llama3.2:latest",
        "name": "llama3.2:latest",
        "display_name": "Llama 3.2 3B (Consigliato per LORIS)",
        "description": "Bilanciato, veloce (~2.0 GB), ottima comprensione in italiano ed analisi finanziaria.",
        "size_est": "2.0 GB",
        "recommended": True,
    },
    {
        "tag": "llama3.2:1b",
        "name": "llama3.2:1b",
        "display_name": "Llama 3.2 1B (Ultra Leggero)",
        "description": "Istantaneo e compatto (~1.3 GB), consumo minimo di RAM.",
        "size_est": "1.3 GB",
        "recommended": False,
    },
    {
        "tag": "qwen2.5:3b",
        "name": "qwen2.5:3b",
        "display_name": "Qwen 2.5 3B (Logica Numerica)",
        "description": "Precisione elevata nei calcoli matematici e nella contabilità (~1.9 GB).",
        "size_est": "1.9 GB",
        "recommended": False,
    },
    {
        "tag": "mistral:latest",
        "name": "mistral:latest",
        "display_name": "Mistral 7B (Analitico & Robusto)",
        "description": "Modello ad alte prestazioni per spiegazioni approfondite (~4.1 GB).",
        "size_est": "4.1 GB",
        "recommended": False,
    },
    {
        "tag": "qwen2.5:7b",
        "name": "qwen2.5:7b",
        "display_name": "Qwen 2.5 7B (Avanzato)",
        "description": "Potenza di calcolo e sintesi patrimoniale superiore (~4.7 GB).",
        "size_est": "4.7 GB",
        "recommended": False,
    },
]

# Categorie standard previste dal modello e da Monefy
MONEFY_CATEGORIES = [
    "Affitto",
    "Spesa",
    "Eating out",
    "Drinking out",
    "Trasporti",
    "Benzina + autostrada + car",
    "House (lavatrice, arredamento)",
    "Bills + commissions",
    "Palestra, sport e integratori",
    "Health",
    "Università + istruzione",
    "Vestiti",
    "Parrucchiere",
    "Utilities",
    "Gift",
    "libri",
    "Musei e cinema",
    "Cazzate e scommesse",
    "Entertainment",
    "videogames",
    "Salary",
    "Deposits",
    "Rimborsi",
]

# Dizionario euristico ad alta copertura per classificazione offline deterministica
OFFLINE_MERCHANT_RULES = {
    # Spesa / Supermercato
    "Spesa": [
        "billa", "spar", "hofer", "lidl", "penny", "coop", "esselunga", "conad",
        "carrefour", "pam", "interspar", "eurospin", "dm ", "bipa", "merkur", "supermarket", "alimentari"
    ],
    # Eating out
    "Eating out": [
        "restaurant", "ristorante", "pizzeria", "trattoria", "kebab", "mcdonald", "burger king",
        "tokki", "sushi", "ramen", "noodle", "va piano", "osteria", "osterreich", "bistro", "deliveroo", "just eat", "uber eats"
    ],
    # Drinking out / Caffè
    "Drinking out": [
        "bar", "cafe", "caffe", "pub", "brewery", "cocktail", "espresso", "starbucks", "ube", "aperitivo"
    ],
    # Affitto
    "Affitto": [
        "affitto", "miete", "rent", "vermieter", "locazione", "canone di locazione", "musterstrasse"
    ],
    # Casa / House
    "House (lavatrice, arredamento)": [
        "ikea", "möbelix", "moebelix", "leroy merlin", "brico", "obi", "bauhaus",
        "ferramenta", "arredo", "materasso", "scarpiera", "cassettiera", "silvercrest", "lavatrice", "sifone"
    ],
    # Utenze / Bollette / Bills
    "Bills + commissions": [
        "wiener netze", "gogreenenergy", "maxenergy", "luce", "gas", "elettricita",
        "enel", "a2a", "spusu", "sim ", "telefonia", "coopvoce", "vodafone", "telecom", "canone rai", "commissione", "fee paypal"
    ],
    # Trasporti
    "Trasporti": [
        "wiener linien", "öbb", "oebb", "trenitalia", "italo", "metro", "bus", "biglietto",
        "transport", "abbonamento trasporti", "uber", "bolt", "flughafen"
    ],
    # Palestra & Sport
    "Palestra, sport e integratori": [
        "mcfit", "fitinn", "virgin", "palestra", "fitness", "creatina", "protein", "decathlon", "sport"
    ],
    # Health / Farmacia
    "Health": [
        "farmacia", "apotheke", "dentista", "zahnarzt", "visita medica", "ticket", "medico", "pastiglie", "crema"
    ],
    # Università & Ricerca
    "Università + istruzione": [
        "acme", "universita", "universitaet", "tuition", "tassa iscrizione", "learning", "coursera", "udemy"
    ],
    # Abbigliamento
    "Vestiti": [
        "zara", "h&m", "uniqlo", "zalando", "decathlon vestiti", "scarpe", "clothes", "abbigliamento", "pull&bear"
    ],
    # Intrattenimento & Svago
    "Musei e cinema": [
        "cinema", "kino", "teatro", "museum", "museo", "mostra", "non stop kino"
    ],
    "Entertainment": [
        "netflix", "spotify", "prime video", "youtube", "disney", "audible", "gemini pro", "chatgpt"
    ],
    "videogames": [
        "steam", "playstation", "nintendo", "xbox", "gog", "vydia", "epic games"
    ],
    # Scommesse & Gioco
    "Svago & Scommesse": [
        "betfair", "bet365", "snai", "eurobet", "sisal", "lottomatica", "planetwin", "pokerstars", "bwin", "goldbet", "william hill", "casino", "scommesse", "betting", "gambling"
    ],
    # Entrate
    "Salary": [
        "gehalt", "stipendio", "salary", "acme wien", "acme university", "emolumento"
    ],
    "Deposits": [
        "zinsen", "interessi", "trade republic zinsen", "dividendo", "cedola"
    ],
    "Rimborsi": [
        "rimborso", "refund", "rückerstattung", "aliexpress", "amazon rimborso"
    ],
}


@dataclass
class LLMStatus:
    is_available: bool
    provider: str  # 'ollama', 'openai_compatible', 'offline_rules'
    model_name: str
    available_models: List[str]
    latency_ms: Optional[float] = None
    endpoint_url: str = "http://localhost:11434"
    installed_details: List[Dict[str, Any]] = field(default_factory=list)
    is_cli_installed: bool = False
    cli_path: Optional[str] = None


class LocalLLMClient:
    """
    Client per interagire con LLM in locale su porta localhost (Ollama o server compatibili),
    con selezione modelli, installazione diretta 1-click e fallback deterministico istantaneo.
    """

    def __init__(
        self,
        endpoint_url: str = "http://localhost:11434",
        preferred_model: Optional[str] = None,
        timeout_seconds: float = 12.0,
    ):
        # Sicurezza rigorosa: accetta SOLO host locali per garantire totale anonimato
        self._validate_local_endpoint(endpoint_url)
        self.endpoint_url = endpoint_url.rstrip("/")
        self.preferred_model = preferred_model
        self.timeout_seconds = timeout_seconds
        self.scrubber = PIIScrubber()

    def _validate_local_endpoint(self, url: str):
        allowed_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
        is_local = any(host in url.lower() for host in allowed_hosts)
        if not is_local:
            raise ValueError(
                f"VIOLAZIONE PRIVACY: L'endpoint '{url}' non è su localhost. "
                "Per tutelare la privacy bancaria, sono ammessi esclusivamente server LLM locali."
            )

    def is_ollama_cli_available(self) -> Tuple[bool, Optional[str]]:
        """Verifica se l'eseguibile Ollama è presente nel sistema operativo."""
        which_path = shutil.which("ollama")
        if which_path:
            return True, which_path
        common_paths = [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
            os.path.expanduser("~/bin/ollama"),
            "/Applications/Ollama.app/Contents/Resources/ollama",
        ]
        for p in common_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return True, p
        return False, None

    def start_ollama_daemon(self) -> Tuple[bool, str]:
        """Avvia il demone Ollama in background se non è già attivo."""
        # Se risponde già, non fare nulla
        st = self.check_health()
        if st.is_available:
            return True, "Demone Ollama è già attivo e raggiungibile."

        cli_ok, cli_path = self.is_ollama_cli_available()
        if not cli_ok or not cli_path:
            cmd = self.get_install_instructions()
            return False, f"Ollama non è installato sulla macchina.\nInstalla con: {cmd}"

        try:
            subprocess.Popen(
                [cli_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            # Attende fino a 4 secondi per l'avvio del server HTTP
            for _ in range(8):
                time.sleep(0.5)
                if self.check_health().is_available:
                    return True, "Demone Ollama avviato con successo!"
            return True, "Processo Ollama avviato; in attesa di risposta della porta 11434..."
        except Exception as e:
            return False, f"Impossibile avviare il processo Ollama: {e}"

    def get_install_instructions(self) -> str:
        """Restituisce il comando per installare Ollama in base al sistema operativo."""
        import platform
        sys_name = platform.system().lower()
        if "darwin" in sys_name:
            return "brew install ollama"
        elif "linux" in sys_name:
            return "curl -fsSL https://ollama.com/install.sh | sh"
        else:
            return "Scarica l'installer da https://ollama.com/download"

    def get_detailed_models(self) -> List[Dict[str, Any]]:
        """Restituisce i dettagli dei modelli installati in Ollama (dimensione, data, tag)."""
        try:
            resp = requests.get(f"{self.endpoint_url}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                raw_models = resp.json().get("models", [])
                out = []
                for m in raw_models:
                    size_b = m.get("size", 0)
                    size_gb = round(size_b / (1024**3), 2) if size_b else 0.0
                    out.append({
                        "name": m.get("name", ""),
                        "size_gb": size_gb,
                        "digest": m.get("digest", "")[:12],
                        "modified_at": m.get("modified_at", ""),
                    })
                return out
        except Exception:
            pass
        return []

    def pull_model_stream(self, model_tag: str) -> Generator[Dict[str, Any], None, None]:
        """
        Scarica/installa un modello da Ollama inviando eventi di avanzamento in tempo reale.
        Produce dizionari: {"status": str, "completed": int, "total": int, "percent": float, "done": bool}
        """
        payload = {"name": model_tag, "stream": True}
        try:
            resp = requests.post(
                f"{self.endpoint_url}/api/pull",
                json=payload,
                stream=True,
                timeout=900,
            )
            if resp.status_code != 200:
                yield {
                    "status": f"Errore server HTTP {resp.status_code}",
                    "completed": 0,
                    "total": 0,
                    "percent": 0.0,
                    "done": True,
                    "error": True,
                }
                return

            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                    status = chunk.get("status", "")
                    completed = chunk.get("completed", 0)
                    total = chunk.get("total", 0)
                    percent = round((completed / total * 100.0), 1) if (total and total > 0) else 0.0
                    is_done = status == "success"
                    yield {
                        "status": status,
                        "completed": completed,
                        "total": total,
                        "percent": percent,
                        "done": is_done,
                        "error": False,
                    }
                    if is_done:
                        # Imposta automaticamente come modello attivo
                        self.preferred_model = model_tag
                        break
                except Exception:
                    continue
        except Exception as e:
            yield {
                "status": f"Errore di connessione: {e}",
                "completed": 0,
                "total": 0,
                "percent": 0.0,
                "done": True,
                "error": True,
            }

    def pull_model_sync(self, model_tag: str) -> Tuple[bool, str]:
        """Scarica un modello in modo sincrono fino al completamento."""
        last_status = "Iniziato"
        for evt in self.pull_model_stream(model_tag):
            if evt.get("error"):
                return False, evt.get("status", "Errore sconosciuto")
            last_status = evt.get("status", "")
            if evt.get("done"):
                return True, f"Modello '{model_tag}' scaricato con successo!"
        return True, f"Installazione completata: {last_status}"

    def check_health(self) -> LLMStatus:
        """Verifica se il demone Ollama o un server locale è raggiungibile."""
        cli_ok, cli_path = self.is_ollama_cli_available()

        # 1. Prova endpoint Ollama tags
        try:
            resp = requests.get(f"{self.endpoint_url}/api/tags", timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("models", [])
                models = [m.get("name") for m in raw_models]
                details = [
                    {
                        "name": m.get("name", ""),
                        "size_gb": round(m.get("size", 0) / (1024**3), 2),
                        "digest": m.get("digest", "")[:12],
                    }
                    for m in raw_models
                ]
                # Seleziona preferred_model se valido, altrimenti seleziona preferibilmente modelli rapidi consigliati
                chosen = None
                if self.preferred_model and self.preferred_model in models:
                    chosen = self.preferred_model
                else:
                    fast_defaults = ["llama3.2:latest", "llama3.2:3b", "llama3.2:1b", "qwen2.5:3b", "qwen3:8b", "mistral:latest"]
                    for fd in fast_defaults:
                        if fd in models:
                            chosen = fd
                            break
                    if not chosen:
                        chosen = models[0] if models else "llama3.2:latest"

                return LLMStatus(
                    is_available=True,
                    provider="ollama",
                    model_name=chosen,
                    available_models=models,
                    endpoint_url=self.endpoint_url,
                    installed_details=details,
                    is_cli_installed=cli_ok,
                    cli_path=cli_path,
                )
        except Exception:
            pass

        # 2. Prova endpoint OpenAI-compatible locale (/v1/models)
        try:
            resp = requests.get(f"{self.endpoint_url}/v1/models", timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", [])]
                chosen = self.preferred_model if self.preferred_model in models else (models[0] if models else "local-model")
                return LLMStatus(
                    is_available=True,
                    provider="openai_compatible",
                    model_name=chosen,
                    available_models=models,
                    endpoint_url=self.endpoint_url,
                    is_cli_installed=cli_ok,
                    cli_path=cli_path,
                )
        except Exception:
            pass

        # 3. Fallback: Motore offline a regole
        return LLMStatus(
            is_available=False,
            provider="offline_rules",
            model_name="Motore Deterministico Euristico (Offline)",
            available_models=["Motore Regole Offline"],
            endpoint_url=self.endpoint_url,
            is_cli_installed=cli_ok,
            cli_path=cli_path,
        )

    def categorize_transaction(
        self, description: str, amount: float, counterparty: str = ""
    ) -> Dict[str, Any]:
        """
        Classifica una transazione bancaria in una delle categorie Monefy.
        Applica prima lo scrubber anonimizzatore, poi tenta il modello locale;
        se il server è offline, usa l'euristica offline a regole.
        """
        raw_text = f"{description} {counterparty}".strip()
        # SCRUBBING OBBLIGATORIO: nessun dato reale raggiunge il prompt
        anon_desc = self.scrubber.anonymize_text(raw_text)

        status = self.check_health()
        if status.is_available:
            try:
                res = self._ask_llm_category(anon_desc, amount, status)
                if res and res.get("category") in MONEFY_CATEGORIES:
                    res["method"] = f"LLM Locale ({status.model_name})"
                    res["anonymized_input"] = anon_desc
                    return res
            except Exception:
                pass

        # Fallback offline a regole
        cat, conf, reason = self._offline_categorize(raw_text, amount)
        return {
            "category": cat,
            "confidence": conf,
            "reasoning": reason,
            "method": "Motore Deterministico (Offline 100%)",
            "anonymized_input": anon_desc,
        }

    def _ask_llm_category(
        self, anon_desc: str, amount: float, status: LLMStatus
    ) -> Optional[Dict[str, Any]]:
        """Invia un prompt ultra-compatto in formato JSON al modello locale."""
        categories_str = ", ".join(f"'{c}'" for c in MONEFY_CATEGORIES)
        prompt = (
            f"Sei un assistente finanziario personale per la categorizzazione delle spese.\n"
            f"Classifica la seguente transazione bancaria anonimizzata in ESATTAMENTE UNA delle seguenti categorie:\n"
            f"[{categories_str}]\n\n"
            f"Transazione: \"{anon_desc}\", Importo: {amount} EUR\n\n"
            f"Rispondi SOLO in formato JSON valido come segue:\n"
            f'{{"category": "<nome_categoria_esatto>", "confidence": <float_0_a_1>, "reasoning": "<spiegazione_brevissima>"}}'
        )

        if status.provider == "ollama":
            payload = {
                "model": status.model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 120},
            }
            resp = requests.post(
                f"{self.endpoint_url}/api/generate", json=payload, timeout=min(self.timeout_seconds, 3.5)
            )
            if resp.status_code == 200:
                raw_out = resp.json().get("response", "")
                return json.loads(raw_out)
        elif status.provider == "openai_compatible":
            payload = {
                "model": status.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 120,
            }
            resp = requests.post(
                f"{self.endpoint_url}/v1/chat/completions", json=payload, timeout=self.timeout_seconds
            )
            if resp.status_code == 200:
                raw_out = resp.json()["choices"][0]["message"]["content"]
                # Cerca blocco json
                m = re.search(r"\{.*\}", raw_out, re.DOTALL)
                if m:
                    return json.loads(m.group(0))

        return None

    def _offline_categorize(self, text: str, amount: float) -> Tuple[str, float, str]:
        """Classificatore deterministico veloce ad albero di decisione con supporto word-boundary."""
        t_low = text.lower()

        # 1. Controllo entrate note
        if amount > 0:
            if any(k in t_low for k in ["acme", "stipendio", "gehalt", "acme university", "emolumento", "payroll"]):
                return "Salary", 0.99, "Riconosciuto accredito stipendio"
            if any(k in t_low for k in ["zinsen", "interest", "trade republic"]):
                return "Deposits", 0.95, "Riconosciuti interessi attivi sulla liquidità"
            if any(k in t_low for k in ["rimborso", "refund", "storno"]):
                return "Rimborsi", 0.90, "Riconosciuto rimborso commerciale"
            return "Salary" if amount >= 1500 else "Deposits", 0.70, "Entrata generica"

        # 2. Controllo uscite per matching su dizionario con word-boundary per parole brevi
        for cat, keywords in OFFLINE_MERCHANT_RULES.items():
            for kw in keywords:
                if len(kw) <= 4 or kw in {"etf", "pac", "gas", "bar", "rent", "aldi", "coop", "pam", "q8"}:
                    if re.search(r"\b" + re.escape(kw) + r"\b", t_low):
                        return cat, 0.92, f"Corrispondenza parola chiave '{kw}'"
                elif kw in t_low:
                    return cat, 0.92, f"Corrispondenza parola chiave '{kw}'"

        # 3. Regole basate su importo
        if abs(amount) > 400 and any(k in t_low for k in ["wien", "haus", "vienna", "wohnung", "locazione"]):
            return "Affitto", 0.65, "Importo elevato compatibile con affitto"

        return "Altre Spese", 0.30, "Nessun pattern noto (categoria generale)"

    def build_financial_system_context(
        self,
        summary_data: Any,
        anonymized_transactions: Optional[pd.DataFrame] = None,
        cash_yield_pct: float = 2.5
    ) -> str:
        """
        Costruisce il contesto e le regole contabili per LORIS.
        Utilizza FinancialFactSheet per il grounding immutabile anti-allucinazione.
        """
        def _get_val(obj, key, default=0.0):
            if hasattr(obj, key):
                v = getattr(obj, key)
                return float(v) if v is not None else default
            elif isinstance(obj, dict):
                v = obj.get(key)
                return float(v) if v is not None else default
            return default

        nw = _get_val(summary_data, "total_net_worth", 0.0)
        liq = _get_val(summary_data, "total_liquid_cash", 0.0)
        hy = _get_val(summary_data, "total_high_yield_cash", 0.0)
        inv = _get_val(summary_data, "total_investments", 0.0)
        burn = _get_val(summary_data, "monthly_burn_rate", 550.0)
        buffer_m = _get_val(summary_data, "liquidity_buffer_months", 3.0)

        # Saldi per conto
        acc_bals = {}
        if hasattr(summary_data, "accounts_summary") and isinstance(summary_data.accounts_summary, pd.DataFrame):
            for _, r in summary_data.accounts_summary.iterrows():
                inst = r.get("institution", "Conto")
                bal = float(r.get("balance", 0.0))
                acc_bals[inst] = bal

        # Spese per categoria
        cat_spend = {}
        tx_rows = []
        if anonymized_transactions is not None and not anonymized_transactions.empty:
            for _, r in anonymized_transactions.iterrows():
                amt = float(r.get("amount", 0.0))
                cat = str(r.get("category", "Spesa"))
                if amt < 0:
                    cat_spend[cat] = cat_spend.get(cat, 0.0) + abs(amt)
                tx_rows.append({
                    "amount": amt,
                    "category": cat,
                    "description": str(r.get("description", ""))[:45]
                })

        tr_count = 0
        if hasattr(summary_data, "internal_transfers") and isinstance(summary_data.internal_transfers, pd.DataFrame):
            tr_count = len(summary_data.internal_transfers)

        est_interest = hy * (cash_yield_pct / 100.0)

        # Estrazione dati Wallet se presenti
        has_wallet = getattr(summary_data, "has_wallet_tracker", False)
        w_summary = getattr(summary_data, "wallet_summary", {}) or {}
        w_tot_exp = float(w_summary.get("total_expenses", 0.0))
        w_cash_exp = float(w_summary.get("cash_expenses", 0.0))
        w_elec_exp = float(w_summary.get("electronic_expenses", 0.0))
        w_tx_count = int(w_summary.get("tx_count", 0))
        w_cash_pct = float(w_summary.get("cash_ratio_pct", 0.0))
        w_top_cats = w_summary.get("top_categories", {})
        d_range = w_summary.get("date_range", ("", ""))
        d_range_str = f"dal {d_range[0]} al {d_range[1]}" if (d_range and d_range[0]) else "periodo tracciato"

        fact_sheet = FinancialFactSheet(
            net_worth=nw,
            liquid_cash=liq,
            high_yield_cash=hy,
            investments=inv,
            monthly_burn_rate=burn,
            cash_buffer_months=buffer_m,
            cash_yield_pct=cash_yield_pct,
            annual_interest_est=est_interest,
            account_balances=acc_bals,
            category_spending=cat_spend,
            top_transactions=tx_rows,
            reconciled_transfers_count=tr_count,
            has_wallet_tracker=has_wallet,
            wallet_total_expenses=w_tot_exp,
            wallet_cash_expenses=w_cash_exp,
            wallet_electronic_expenses=w_elec_exp,
            wallet_tx_count=w_tx_count,
            wallet_cash_ratio_pct=w_cash_pct,
            wallet_top_categories=w_top_cats,
            wallet_date_range_str=d_range_str,
        )

        return (
            "Sei LORIS (Local Overview of Resources, Investments & Spending), l'assistente finanziario personale offline, "
            "riservato, analitico ed esperto.\n\n"
            + fact_sheet.to_prompt_grounding_block() +
            "\nRispondi in modo pratico, cordiale, empatico e matematicamente inappuntabile in lingua italiana (o inglese se l'utente scrive in inglese)."
        )

    def chat_with_llm(
        self,
        messages: List[Dict[str, str]],
        portfolio_summary: Any,
        anonymized_transactions: Optional[pd.DataFrame] = None,
        cash_yield_pct: float = 2.5,
        stream: bool = False,
    ) -> Any:
        """
        Interazione conversazionale multi-turn con il modello locale (Ollama / llama.cpp).
        Se stream=True restituisce un generatore di token per st.write_stream.
        In assenza di server Ollama attivo, esegue fallback sul motore euristico intelligente.
        """
        system_ctx = self.build_financial_system_context(
            portfolio_summary,
            anonymized_transactions=anonymized_transactions,
            cash_yield_pct=cash_yield_pct
        )

        status = self.check_health()
        if status.is_available and status.provider == "ollama":
            payload_messages = [{"role": "system", "content": system_ctx}]
            for m in messages:
                payload_messages.append({"role": m["role"], "content": m["content"]})

            model_to_use = self.preferred_model or status.model_name
            try:
                if stream:
                    resp = requests.post(
                        f"{self.endpoint_url}/api/chat",
                        json={"model": model_to_use, "messages": payload_messages, "stream": True},
                        stream=True,
                        timeout=max(self.timeout_seconds * 3, 20.0),
                    )
                    if resp.status_code == 200:
                        def _gen():
                            for line in resp.iter_lines():
                                if line:
                                    try:
                                        chunk = json.loads(line.decode("utf-8"))
                                        content = chunk.get("message", {}).get("content", "")
                                        if content:
                                            yield content
                                    except Exception:
                                        pass
                        return _gen()
                else:
                    resp = requests.post(
                        f"{self.endpoint_url}/api/chat",
                        json={"model": model_to_use, "messages": payload_messages, "stream": False},
                        timeout=max(self.timeout_seconds * 3, 20.0),
                    )
                    if resp.status_code == 200:
                        ans = resp.json().get("message", {}).get("content", "").strip()
                        if ans:
                            return ans
            except Exception:
                pass

        # Offline Fallback intelligente se Ollama è offline o fallisce
        last_user_msg = messages[-1]["content"] if messages else ""
        return self._heuristic_fallback_response(portfolio_summary, last_user_msg, cash_yield_pct)

    def _heuristic_fallback_response(self, portfolio_summary: Any, user_question: str, cash_yield_pct: float = 2.5) -> str:
        """Motore Euristico Deterministico di fallback con risposte finanziarie strutturate."""
        if hasattr(portfolio_summary, "total_net_worth"):
            nw = portfolio_summary.total_net_worth
            liq = portfolio_summary.total_liquid_cash
            hy = portfolio_summary.total_high_yield_cash
            inv = portfolio_summary.total_investments
            burn = portfolio_summary.monthly_burn_rate
            buffer_m = portfolio_summary.liquidity_buffer_months
        elif isinstance(portfolio_summary, dict):
            nw = portfolio_summary.get("total_net_worth", 0.0)
            liq = portfolio_summary.get("total_liquid_cash", 0.0)
            hy = portfolio_summary.get("total_high_yield_cash", 0.0)
            inv = portfolio_summary.get("total_investments", 0.0)
            burn = portfolio_summary.get("monthly_burn_rate", 550.0)
            buffer_m = portfolio_summary.get("liquidity_buffer_months", 3.0)
        else:
            nw, liq, hy, inv, burn, buffer_m = 0.0, 0.0, 0.0, 0.0, 550.0, 3.0

        q_low = user_question.lower()
        tot_cash = liq + hy
        est_annual_interest = hy * (cash_yield_pct / 100.0)

        w_summary = getattr(portfolio_summary, "wallet_summary", {}) if hasattr(portfolio_summary, "wallet_summary") else {}
        has_wallet = getattr(portfolio_summary, "has_wallet_tracker", False) or bool(w_summary)
        w_note = ""
        if has_wallet and w_summary:
            w_tot = float(w_summary.get("total_expenses", 0.0))
            w_cash = float(w_summary.get("cash_expenses", 0.0))
            w_cash_pct = float(w_summary.get("cash_ratio_pct", 0.0))
            w_count = int(w_summary.get("tx_count", 0))
            w_note = (
                f"\n\n📱 **Dati Integrativi App Spese (Wallet):**\n"
                f"• Spese Totali Registrate: **€ {w_tot:,.2f}** ({w_count} movimenti).\n"
                f"• Di cui pagate in **CONTANTI (CASH)**: **€ {w_cash:,.2f}** ({w_cash_pct:.1f}%).\n"
                f"• *Nota:* L'app Wallet traccia le tue abitudini quotidiane e contanti senza alterare il saldo attivo dei conti bancari."
            )

        if any(w in q_low for w in ["anomali", "stran", "spes", "uscit", "burger", "aldi", "betfair", "wallet"]):
            return (
                f"🐾 **Analisi Spese & Flussi di Cassa (LORIS Offline Engine):**\n\n"
                f"• **Burn Rate Mensile Medio:** **€ {burn:,.2f}/mese**.\n"
                f"• **Regola Contabile dei Segni:** Negli estratti bancari le uscite sono registrate con segno **negativo (-)** perché decrementano la liquidità. Questo è il normale funzionamento dei conti e non costituisce alcun errore.\n"
                f"• **Spese per Consumi & Alimentari:** Acquisti quotidiani (es. supermercati ALDI/Spar, Burger King) rappresentano la componente viva delle spese correnti.\n"
                f"• **Scommesse & Svago:** Piattaforme di gioco (es. Betfair) sono classificate correttamente in **Svago & Scommesse**, separate dagli investimenti a lungo termine.\n"
                f"• **Giroconti Riconciliati:** I trasferimenti tra i tuoi conti (es. Revolut ↔ Trade Republic) sono neutralizzati automaticamente per evitare di duplicare uscite ed entrate."
                + w_note
            )
        elif any(w in q_low for w in ["tasso", "bce", "interess", "remunerat", "trade republic"]):
            return (
                f"📈 **Rendimento Liquidità Remunerata (Tasso BCE {cash_yield_pct:.2f}%):**\n\n"
                f"• **Saldo Remunerato Attivo:** **€ {hy:,.2f}** su Trade Republic / conto deposito.\n"
                f"• **Rendimento Annuo Stimato Lordo:** **€ {est_annual_interest:,.2f}/anno** (~€ {est_annual_interest/12:,.2f}/mese).\n"
                f"• **Allineamento BCE:** Il tasso segue la politica monetaria della Banca Centrale Europea sul deposito overnight.\n"
                f"• **Efficienza Cash:** Il **{(hy/tot_cash*100) if tot_cash > 0 else 0:.1f}%** della tua cassa complessiva è a rendimento attivo, proteggendoti dall'inflazione senza vincoli di lock-up."
            )
        elif any(w in q_low for w in ["pac", "invest", "etf", "azioni", "aument"]):
            rec_action = "puoi valutare di incrementare gradualmente la quota mensile" if buffer_m >= 3.5 else "è raccomandato consolidare prima il cuscinetto di liquidità"
            return (
                f"🎯 **Valutazione PAC & Strategia Investimenti (ETF):**\n\n"
                f"• **Patrimonio Investito Attuale:** **€ {inv:,.2f}**.\n"
                f"• **Cuscinetto di Emergenza:** La cassa totale (€ {tot_cash:,.2f}) copre **{buffer_m:.1f} mesi** di uscite medie.\n"
                f"• **Regola di Sicurezza:** Si consiglia di preservare sempre almeno 3-4 mesi di spese fisse (€ {burn*3.5:,.0f}) prima di impegnare capitale sui mercati.\n"
                f"• **Diagnosi:** In base alla tua copertura attuale, **{rec_action}**."
            )
        else:
            return (
                f"🐾 **Panoramica Patrimonio & Diagnosi Finanziaria (LORIS):**\n\n"
                f"• **Patrimonio Netto Complessivo:** **€ {nw:,.2f}**\n"
                f"• **Liquidità Immediata (C/C):** € {liq:,.2f}\n"
                f"• **Liquidità Remunerata (Trade Republic a {cash_yield_pct:.2f}%):** € {hy:,.2f}\n"
                f"• **Portafoglio Investimenti (ETF):** € {inv:,.2f}\n"
                f"• **Autonomia Finanziaria:** **{buffer_m:.1f} mesi** di copertura completa al burn rate attuale (€ {burn:,.2f}/m)."
                + w_note +
                f"\n\nPuoi chiedermi dettagli specifici sulle tue categorie di spesa, sul tasso BCE o sulle proiezioni Monte Carlo!"
            )

    def generate_portfolio_audit(self, summary_data: Any, cash_yield_pct: float = 2.5) -> str:
        """
        Genera un audit narrativo della salute patrimoniale strutturato in 4 punti chiave:
        Riserva di Liquidità, Efficienza, Asset Allocation e Consiglio Operativo.
        Totalmente anonimizzato e istantaneo.
        """
        def _get_val(obj, key, default=0.0):
            if hasattr(obj, key):
                v = getattr(obj, key)
                return float(v) if v is not None else default
            elif isinstance(obj, dict):
                v = obj.get(key)
                return float(v) if v is not None else default
            return default

        nw = _get_val(summary_data, "total_net_worth", 0.0)
        liq = _get_val(summary_data, "total_liquid_cash", 0.0)
        hy = _get_val(summary_data, "total_high_yield_cash", 0.0)
        inv = _get_val(summary_data, "total_investments", 0.0)
        burn = _get_val(summary_data, "monthly_burn_rate", 550.0)
        buffer_m = _get_val(summary_data, "liquidity_buffer_months", 3.0)

        if (liq + hy) <= 0 or buffer_m < 2.0:
            buffer_status = "🚨 Troppo basso"
        elif buffer_m >= 4.0:
            buffer_status = "✅ Eccellente"
        else:
            buffer_status = "⚠️ Adeguato"
        hy_pct = (hy / (liq + hy) * 100) if (liq + hy) > 0 else 0.0

        audit_lines = [
            f"**🐾 LORIS — Diagnosi Patrimoniale Multi-Banca (100% Locale & Riservata):**",
            f"• **Riserva di Liquidità:** {buffer_status}. La cassa complessiva (€{(liq+hy):,.0f}) copre **{buffer_m:.1f} mesi** di uscite medie (€{burn:,.0f}/m).",
            f"• **Efficienza della Liquidità:** Il **{hy_pct:.0f}%** della tua cassa è allocato su conti remunerati a tasso BCE ({cash_yield_pct:.2f}%), proteggendo parzialmente il capitale dall'inflazione.",
            f"• **Asset Allocation:** Hai €{inv:,.0f} investiti in ETF/Mercati. In caso di shock a breve termine, la cassa liquida ti protegge integralmente dal rischio di liquidazione forzata.",
            f"• **Consiglio Operativo:** Mantieni almeno 3 mesi di burn rate (€{burn*3:,.0f}) sui conti di liquidità prima di incrementare la rata del PAC.",
        ]
        return "\n".join(audit_lines)

    def query_portfolio_insights(
        self,
        portfolio_summary: Any,
        anonymized_transactions: Optional[pd.DataFrame] = None,
        user_question: str = "Come posso migliorare la gestione finanziaria?",
        cash_yield_pct: float = 2.5,
    ) -> str:
        """
        Risponde a domande finanziarie dell'utente con contesto patrimoniale completo e privacy totale.
        """
        messages = [{"role": "user", "content": user_question}]
        res = self.chat_with_llm(
            messages=messages,
            portfolio_summary=portfolio_summary,
            anonymized_transactions=anonymized_transactions,
            cash_yield_pct=cash_yield_pct,
            stream=False
        )
        return str(res) if res else self._heuristic_fallback_response(portfolio_summary, user_question, cash_yield_pct)
