# ============================================================
# AGENT RUNTIME — loop ReAct locale con tool-calling e grounding
# ============================================================
"""
Ciclo: il modello locale propone chiamate a tool -> il runtime le valida ed esegue
(sola lettura) -> i risultati tornano al modello -> risposta finale.

Garanzie:
- solo endpoint locale (riusa la validazione di LocalLLMClient);
- massimo `max_steps` iterazioni e `max_tool_calls` totali, niente chiamate identiche ripetute;
- errori dei tool restituiti al modello (auto-correzione), mai propagati;
- ripiego testuale se il modello non supporta il tool-calling nativo;
- ogni importo in € della risposta viene confrontato con i numeri letti dai tool.
"""

from dataclasses import dataclass, field
import json
import math
import re
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Set

import requests

from banking.parsers import clean_numeric_amount
from .tools import ToolRegistry, ToolResult

ChatFn = Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]]

SYSTEM_PROMPT_IT = """Sei LORIS, analista finanziario personale che lavora 100% in locale sui dati dell'utente.
Regole:
- Per QUALSIASI cifra, data o confronto usa i tool: non inventare e non stimare a memoria.
- Formati: mesi YYYY-MM, date YYYY-MM-DD. Importi in euro.
- Se un tool restituisce un errore, leggi il messaggio e riprova con argomenti corretti.
- Chiama solo i tool necessari (di solito 1-4), poi rispondi.
- Risposta in italiano, concisa, con le cifre chiave in evidenza e le ipotesi dichiarate.
- Le simulazioni sono proiezioni, non garanzie; non dare consigli di acquisto di titoli specifici."""

SYSTEM_PROMPT_EN = """You are LORIS, a personal finance analyst working 100% locally on the user's data.
Rules:
- For ANY figure, date or comparison use the tools: never invent or estimate from memory.
- Formats: months YYYY-MM, dates YYYY-MM-DD. Amounts in euros.
- If a tool returns an error, read the message and retry with corrected arguments.
- Call only the tools you need (usually 1-4), then answer.
- Answer in English, concise, highlighting key figures and stating assumptions.
- Simulations are projections, not guarantees; do not recommend specific securities."""

TEXT_TOOL_PROTOCOL = (
    '\nSe non puoi usare il tool-calling nativo, rispondi SOLO con un oggetto JSON: '
    '{"tool": "<nome>", "arguments": {...}}.'
)


@dataclass
class AgentEvent:
    kind: str                       # "tool_call" | "tool_result" | "warning" | "final"
    step: int = 0
    name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[ToolResult] = None
    text: Optional[str] = None
    final: Optional["AgentResult"] = None


@dataclass
class AgentResult:
    answer: str
    steps: int
    tool_calls: List[ToolResult] = field(default_factory=list)
    grounding: Dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0
    stopped_reason: str = "answered"   # answered | max_steps | max_tool_calls | empty_answer


class AgentBackendError(RuntimeError):
    """Il backend LLM non è raggiungibile o ha risposto con errore."""


class OllamaChat:
    """Backend `/api/chat` di Ollama con `tools`. Solo endpoint locale."""

    def __init__(self, client: Any, model: Optional[str] = None, timeout_s: float = 300.0, temperature: float = 0.1):
        client._validate_local_endpoint(client.endpoint_url)
        self.endpoint = client.endpoint_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.model = model or client.preferred_model
        if not self.model:
            status = client.check_health()
            if not (status.is_available and status.provider == "ollama" and status.model_name):
                raise AgentBackendError("Ollama non disponibile o nessun modello installato")
            self.model = status.model_name

    def __call__(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "model": self.model, "messages": messages, "stream": False,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools
        try:
            resp = requests.post(f"{self.endpoint}/api/chat", json=payload, timeout=self.timeout_s)
        except requests.RequestException as e:
            raise AgentBackendError(f"Ollama non raggiungibile: {e}") from e
        if resp.status_code != 200:
            raise AgentBackendError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("message", {}) or {}


# ------------------------------------------------------------
# Utilità
# ------------------------------------------------------------
_EURO_RE = re.compile(r"€\s*([\d.,]+)|([\d.,]+)\s*(?:€|EUR\b)")


def collect_numbers(obj: Any, out: Optional[Set[float]] = None) -> Set[float]:
    """Tutti i numeri presenti in una struttura JSON (valori assoluti)."""
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.add(abs(float(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, out)
    return out


def audit_grounding(answer: str, observed: Set[float]) -> Dict[str, Any]:
    """Importi in € della risposta non riconducibili (±5%) a numeri letti dai tool."""
    mentioned, unverified = [], []
    for m in _EURO_RE.finditer(answer):
        raw = (m.group(1) or m.group(2)).rstrip(".,")
        val = abs(clean_numeric_amount(raw))
        if val == 0.0:
            continue
        mentioned.append(val)
        if val > 10.0 and not any(abs(val - o) <= max(0.5, 0.05 * o) for o in observed):
            unverified.append(val)
    return {
        "is_grounded": not unverified,
        "mentioned_amounts": len(mentioned),
        "unverified_amounts": unverified,
    }


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_text_tool_call(content: str, registry: ToolRegistry) -> Optional[Dict[str, Any]]:
    """Ripiego: estrae {"tool": ..., "arguments": {...}} dal testo (anche in blocco ```json)."""
    if not content:
        return None
    m = _JSON_OBJ_RE.search(content)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("tool") or obj.get("name")
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(name, str) and name in registry:
        return {"function": {"name": name, "arguments": args if isinstance(args, (dict, str)) else {}}}
    return None


# ------------------------------------------------------------
# Runtime
# ------------------------------------------------------------
class AgentRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        chat_fn: ChatFn,
        lang: str = "it",
        max_steps: int = 6,
        max_tool_calls: int = 10,
        warn_on_ungrounded: bool = True,
    ):
        self.registry = registry
        self.chat_fn = chat_fn
        self.lang = lang
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.warn_on_ungrounded = warn_on_ungrounded

    def _system_prompt(self) -> str:
        return (SYSTEM_PROMPT_IT + TEXT_TOOL_PROTOCOL) if self.lang == "it" else SYSTEM_PROMPT_EN

    def run(self, question: str, history: Optional[List[Dict[str, str]]] = None) -> AgentResult:
        result = None
        for ev in self.stream(question, history):
            if ev.kind == "final":
                result = ev.final
        assert result is not None
        return result

    def stream(self, question: str, history: Optional[List[Dict[str, str]]] = None) -> Generator[AgentEvent, None, None]:
        started = time.perf_counter()
        messages: List[Dict[str, Any]] = [{"role": "system", "content": self._system_prompt()}]
        for m in history or []:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": question})

        schemas = self.registry.schemas()
        executed: List[ToolResult] = []
        seen_calls: Dict[str, ToolResult] = {}
        observed: Set[float] = set()
        reason = "answered"
        answer = ""
        nudged = False
        steps_used = 0

        for step in range(1, self.max_steps + 1):
            steps_used = step
            tools_arg = schemas if len(executed) < self.max_tool_calls else []
            msg = self.chat_fn(messages, tools_arg)
            tool_calls = msg.get("tool_calls") or []
            content = (msg.get("content") or "").strip()

            if not tool_calls and tools_arg:
                fallback = parse_text_tool_call(content, self.registry)
                if fallback:
                    tool_calls, content = [fallback], ""

            if not tool_calls:
                if content:
                    answer = content
                    break
                if not nudged:      # risposta vuota: un solo sollecito
                    nudged = True
                    messages.append({"role": "user", "content": "Rispondi ora alla domanda con i dati raccolti."})
                    continue
                reason = "empty_answer"
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments", {})
                yield AgentEvent("tool_call", step, name=name, args=args if isinstance(args, dict) else {"raw": args})
                sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                if sig in seen_calls:
                    res = ToolResult(name, args if isinstance(args, dict) else {}, False,
                                     error="chiamata già eseguita con gli stessi argomenti: usa il risultato precedente")
                elif len(executed) >= self.max_tool_calls:
                    res = ToolResult(name, {}, False, error="limite di chiamate tool raggiunto: rispondi con i dati già raccolti")
                    reason = "max_tool_calls"
                else:
                    res = self.registry.execute(name, args)
                    seen_calls[sig] = res
                    executed.append(res)
                    if res.ok:
                        collect_numbers(res.data, observed)
                yield AgentEvent("tool_result", step, name=name, result=res)
                messages.append({"role": "tool", "tool_name": name, "content": res.to_message()})
        else:
            # Passi esauriti: richiesta finale senza tool
            reason = "max_steps"
            messages.append({"role": "user", "content": "Rispondi ora con i dati raccolti, senza altri tool."})
            answer = (self.chat_fn(messages, []).get("content") or "").strip()

        if not answer:
            answer = ("Non sono riuscito a produrre una risposta." if self.lang == "it"
                      else "I could not produce an answer.")
            reason = reason if reason != "answered" else "empty_answer"

        grounding = audit_grounding(answer, observed)
        if self.warn_on_ungrounded and not grounding["is_grounded"]:
            amounts = ", ".join(f"€{v:,.2f}" for v in grounding["unverified_amounts"][:5])
            note = (f"\n\n⚠️ Cifre non verificate dai dati ({amounts}): controllale prima di usarle."
                    if self.lang == "it" else
                    f"\n\n⚠️ Figures not verified against your data ({amounts}): double-check before relying on them.")
            answer += note
            yield AgentEvent("warning", text=note.strip())

        yield AgentEvent("final", final=AgentResult(
            answer=answer, steps=steps_used,
            tool_calls=executed, grounding=grounding,
            elapsed_s=time.perf_counter() - started, stopped_reason=reason,
        ))
