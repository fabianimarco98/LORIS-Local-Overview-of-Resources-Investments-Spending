# ============================================================
# BANKING MODULE — PACKAGE INIT
# ============================================================
"""
Modulo Multi-Bank & Asset Allocation per Previsione Spese v3:
- PII Scrubber & Anonymizer
- Parsers (Trade Republic, Erste Bank, Banche Italiane, Revolut, PDF, Generic)
- Portfolio Aggregator & Reconciliation Engine
- Local LLM Client & Offline Rule-based Assistant
"""

from .anonymizer import PIIScrubber
from .parsers import (
    BankStatement,
    parse_bank_statement,
    TradeRepublicParser,
    ErsteBankParser,
    ItalianBankParser,
    DigitalBankParser,
    WalletAppParser,
    GenericBankParser,
)
from .portfolio import PortfolioAggregator, PortfolioSummary, ASSET_CLASS_LABELS, ASSET_CLASS_COLORS
from .local_llm import LocalLLMClient, LLMStatus, MONEFY_CATEGORIES

__all__ = [
    "PIIScrubber",
    "BankStatement",
    "parse_bank_statement",
    "TradeRepublicParser",
    "ErsteBankParser",
    "ItalianBankParser",
    "DigitalBankParser",
    "WalletAppParser",
    "GenericBankParser",
    "PortfolioAggregator",
    "PortfolioSummary",
    "ASSET_CLASS_LABELS",
    "ASSET_CLASS_COLORS",
    "LocalLLMClient",
    "LLMStatus",
    "MONEFY_CATEGORIES",
]
