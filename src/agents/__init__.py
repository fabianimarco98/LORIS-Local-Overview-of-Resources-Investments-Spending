# ============================================================
# LORIS AGENTS — piattaforma agentica 100% locale
# ============================================================
"""
Agente finanziario basato su LLM locale (Ollama) con tool di SOLA LETTURA sul portafoglio:
- `tools.py`   : registro tool con validazione schema, contesto portafoglio e tool finanziari
- `runtime.py` : loop ReAct con tool-calling nativo (+ ripiego testuale), traccia, grounding
"""

from .tools import PortfolioContext, Tool, ToolRegistry, ToolResult, build_portfolio_registry
from .runtime import AgentEvent, AgentResult, AgentRuntime, OllamaChat

__all__ = [
    "AgentEvent", "AgentResult", "AgentRuntime", "OllamaChat",
    "PortfolioContext", "Tool", "ToolRegistry", "ToolResult", "build_portfolio_registry",
]
