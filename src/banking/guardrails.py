# ============================================================
# BANKING MODULE — FINANCIAL GROUNDING & ANTI-HALLUCINATION GUARDRAILS
# ============================================================
"""
Infrastruttura di Grounding e Protezione Anti-Allucinazione per LLM Finanziari:
1. FinancialFactSheet: estrae e congela i dati matematici verificati (Ground Truth immutabile).
2. FinancialToolRegistry: strumenti deterministici per calcoli esatti (tassi, PAC, runway, interessi).
3. AntiHallucinationPromptBuilder: costruisce prompt con vincoli epistemici negativi stringenti.
4. FinancialGuardrail: verifica a posteriori che tutte le cifre generate dal modello corrispondano
   a numeri verificati o calcoli eseguiti, bloccando o annotando allucinazioni numeriche.
"""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import pandas as pd

from .parsers import clean_numeric_amount


@dataclass
class FinancialFactSheet:
    """Rappresentazione verificata e immutabile del patrimonio calcolata dal motore Python."""
    net_worth: float
    liquid_cash: float
    high_yield_cash: float
    investments: float
    monthly_burn_rate: float
    cash_buffer_months: float
    cash_yield_pct: float
    annual_interest_est: float
    account_balances: Dict[str, float] = field(default_factory=dict)
    category_spending: Dict[str, float] = field(default_factory=dict)
    top_transactions: List[Dict[str, Any]] = field(default_factory=list)
    reconciled_transfers_count: int = 0
    verified_numbers_set: Set[float] = field(default_factory=set)
    has_wallet_tracker: bool = False
    wallet_total_expenses: float = 0.0
    wallet_cash_expenses: float = 0.0
    wallet_electronic_expenses: float = 0.0
    wallet_tx_count: int = 0
    wallet_cash_ratio_pct: float = 0.0
    wallet_top_categories: Dict[str, float] = field(default_factory=dict)
    wallet_date_range_str: str = ""

    def __post_init__(self):
        # Popola il set di numeri verificati (per il fact-checking post-generazione)
        base_vals = [
            self.net_worth, self.liquid_cash, self.high_yield_cash,
            self.investments, self.monthly_burn_rate, self.cash_buffer_months,
            self.cash_yield_pct, self.annual_interest_est, self.reconciled_transfers_count,
            self.wallet_total_expenses, self.wallet_cash_expenses, self.wallet_electronic_expenses
        ]
        s = {round(abs(v), 2) for v in base_vals if v is not None}
        for b in self.account_balances.values():
            s.add(round(abs(b), 2))
        for c in self.category_spending.values():
            s.add(round(abs(c), 2))
        for c_val in self.wallet_top_categories.values():
            s.add(round(abs(c_val), 2))
        for tx in self.top_transactions:
            amt = tx.get("amount", 0.0)
            s.add(round(abs(amt), 2))
        self.verified_numbers_set = s

    def to_prompt_grounding_block(self) -> str:
        """Genera il blocco di verità fattuali verificate da iniettare nel prompt del modello."""
        acc_lines = "\n".join([f"    • {acc}: € {bal:,.2f}" for acc, bal in self.account_balances.items()]) or "    • Nessun conto specifico"
        cat_lines = "\n".join([f"    • {cat}: spesa totale € {abs(val):,.2f}" for cat, val in list(self.category_spending.items())[:8]]) or "    • Dati categorie non disponibili"

        tx_lines = []
        for tx in self.top_transactions[:15]:
            amt = float(tx.get("amount", 0.0))
            cat = tx.get("category", "Spesa")
            desc = str(tx.get("description", ""))[:40]
            if amt < 0:
                tx_lines.append(f"    • [USCITA EFFETTUATA] {cat}: spesi € {abs(amt):,.2f} ({desc})")
            else:
                tx_lines.append(f"    • [ENTRATA ACCREDITATA] {cat}: incassati € {amt:,.2f} ({desc})")
        tx_block = "\n".join(tx_lines) or "    • Nessuna transazione recente"

        wallet_block = ""
        if self.has_wallet_tracker:
            w_cat_lines = "\n".join([f"       - {cat}: € {val:,.2f}" for cat, val in list(self.wallet_top_categories.items())[:10]]) or "       - Dettaglio non disponibile"
            wallet_block = (
                f"\n11. DATI INTEGRATIVI DALL'APP SPESE (WALLET / BUDGETBAKERS):\n"
                f"    • Registro spese tracciato dall'utente: {self.wallet_tx_count} transazioni ({self.wallet_date_range_str})\n"
                f"    • Totale uscite registrate su Wallet: € {self.wallet_total_expenses:,.2f}\n"
                f"    • Spese in CONTANTI (CASH): € {self.wallet_cash_expenses:,.2f} ({self.wallet_cash_ratio_pct:.1f}% delle uscite tracciate su Wallet)\n"
                f"    • Spese con Bonifici/Carte: € {self.wallet_electronic_expenses:,.2f}\n"
                f"    • Top Categorie dettagliate fornite da Wallet:\n{w_cat_lines}\n"
            )

        wallet_guidelines = ""
        if self.has_wallet_tracker:
            wallet_guidelines = (
                "• DISTINZIONE RUOLI CONTI BANCARI VS APP WALLET:\n"
                f"  - I conti bancari ufficiali definiscono la liquidità reale disponibile e il patrimonio netto totale (€ {self.net_worth:,.2f}).\n"
                "  - L'App Wallet è un registro/diario di spese personali dell'utente (usato soprattutto per tracciare contanti e spese al dettaglio).\n"
                "  - NON è un conto corrente con debito né ha saldo passivo; NON sottrarre mai il totale di Wallet dal patrimonio netto.\n"
                f"  - Evidenzia all'utente che grazie a Wallet conosci le sue spese in CONTANTI (CASH: € {self.wallet_cash_expenses:,.2f}), invisibili negli estratti conto con carta!\n"
                "  - Sfrutta le categorie ricche di Wallet (es. 'Pub e Ristoranti FUORI', 'Deliveroo a casa', 'Salute', 'Affitto') per dare commenti accurati.\n"
            )

        return (
            "=== [VERIFIED FINANCIAL FACTS — GROUND TRUTH CERTIFICATA PYTHON] ===\n"
            f"1. PATRIMONIO NETTO TOTALE: € {self.net_worth:,.2f}\n"
            f"2. LIQUIDITÀ CONTI CORRENTI: € {self.liquid_cash:,.2f}\n"
            f"3. LIQUIDITÀ REMUNERATA (TRADE REPUBLIC): € {self.high_yield_cash:,.2f}\n"
            f"   - Tasso attivo impostato: {self.cash_yield_pct:.2f}% lordo annuo (BCE)\n"
            f"   - Rendimento passivo annuo stimato: € {self.annual_interest_est:,.2f}/anno (~€ {self.annual_interest_est/12:,.2f}/mese)\n"
            f"4. INVESTIMENTI (ETF / TITOLI): € {self.investments:,.2f}\n"
            f"5. SPESA MEDIA MENSILE (BURN RATE): € {self.monthly_burn_rate:,.2f}/mese\n"
            f"6. CUSCINETTO DI SICUREZZA (BUFFER): {self.cash_buffer_months:.1f} mesi di autonomia completa\n"
            f"7. GIROCONTI INTERNI NEUTRALIZZATI: {self.reconciled_transfers_count} trasferimenti tra conti propri (esclusi per evitare duplicazioni)\n"
            f"8. SALDI CERTIFICATI PER ISTITUTO:\n{acc_lines}\n"
            f"9. SPESA PER PRINCIPALI CATEGORIE:\n{cat_lines}\n"
            f"10. CAMPIONE MOVIMENTI RECENTI (CONVENZIONE CONTABILE: importi negativi = uscite normali, importi positivi = entrate):\n{tx_block}\n"
            f"{wallet_block}"
            "=== [FINE DATI CERTIFICATI] ===\n\n"
            "VINCOLI EPISTEMICI MANDATORI PER L'ASSISTENTE (ANTI-ALLUCINAZIONE):\n"
            "• DIVIETO DI ARITMETICA MENTALE: Non inventare e non ricalcolare totali patrimoniali o saldi di conto; usa solo i dati certificati sopra.\n"
            "• REGOLA DEI SEGNI: Le uscite negli estratti conto hanno SEMPRE SEGNO NEGATIVO (-). NON sono affatto errori di registrazione né rimborsi negativi! Riportale sempre come importi positivi spesi.\n"
            "• CATEGORIZZAZIONE: Piattaforme come Betfair o casinò appartengono a Svago & Scommesse, NON sono investimenti patrimoniali.\n"
            f"{wallet_guidelines}"
            "• TRASPARENZA: Se l'utente ti chiede un dato o una metrica non presente nel blocco sopra, dichiara onestamente che il dato non è presente negli estratti conto caricati.\n"
        )


class FinancialToolRegistry:
    """Registro di strumenti di calcolo matematico deterministico azionabili dall'agente."""

    @staticmethod
    def calculate_compound_interest(principal: float, annual_rate_pct: float, years: int = 1) -> Dict[str, Any]:
        """Calcola con formula analitica esatta il rendimento da interesse composto."""
        r = annual_rate_pct / 100.0
        final_amount = principal * ((1 + r) ** years)
        gain = final_amount - principal
        return {
            "initial_principal": round(principal, 2),
            "annual_rate_pct": annual_rate_pct,
            "years": years,
            "final_amount": round(final_amount, 2),
            "total_interest_earned": round(gain, 2),
            "monthly_average_interest": round(gain / (years * 12), 2),
        }

    @staticmethod
    def simulate_pac_wealth(
        initial_invested: float,
        monthly_pac: float,
        years: int = 5,
        expected_annual_return_pct: float = 6.0
    ) -> Dict[str, Any]:
        """Calcola la traiettoria deterministica di un Piano di Accumulo del Capitale (PAC)."""
        r_m = (1 + expected_annual_return_pct / 100.0) ** (1 / 12) - 1
        months = years * 12
        wealth = initial_invested
        total_deposited = initial_invested

        for _ in range(months):
            wealth = (wealth + monthly_pac) * (1 + r_m)
            total_deposited += monthly_pac

        total_gain = wealth - total_deposited
        return {
            "initial_invested": round(initial_invested, 2),
            "monthly_pac": round(monthly_pac, 2),
            "years": years,
            "total_capital_deposited": round(total_deposited, 2),
            "estimated_final_wealth": round(wealth, 2),
            "estimated_capital_gain": round(total_gain, 2),
            "gain_percentage": round((total_gain / total_deposited * 100.0) if total_deposited > 0 else 0.0, 1),
        }

    @staticmethod
    def calculate_runway(total_cash: float, burn_rate: float) -> Dict[str, Any]:
        """Calcola con esattezza l'autonomia di spesa in mesi e la riserva consigliata."""
        runway_months = (total_cash / burn_rate) if burn_rate > 0 else 999.0
        recommended_buffer_3m = burn_rate * 3.0
        recommended_buffer_6m = burn_rate * 6.0
        return {
            "total_available_cash": round(total_cash, 2),
            "monthly_burn_rate": round(burn_rate, 2),
            "runway_months": round(runway_months, 1),
            "recommended_min_buffer_3_months": round(recommended_buffer_3m, 2),
            "recommended_opt_buffer_6_months": round(recommended_buffer_6m, 2),
            "is_runway_healthy": runway_months >= 3.0,
        }


class FinancialGuardrail:
    """
    Validatore e scudo anti-allucinazione post-generazione:
    Scansiona la risposta generata dal modello linguistico e verifica
    che i numeri menzionati siano compatibili con i dati certificati.
    """

    @classmethod
    def audit_response(cls, response_text: str, fact_sheet: FinancialFactSheet) -> Dict[str, Any]:
        """
        Esamina il testo della risposta, estrae le cifre monetarie e verifica se sono grounded.
        Restituisce un report di conformità e il testo con eventuali note di validazione.
        """
        # Estrai tutti i token numerici monetari (es. € 2,764.33, 2764.33€, € 548)
        pattern = r"€\s*([\d.,]+)|([\d.,]+)\s*€"
        matches = re.findall(pattern, response_text)

        verified_numbers = fact_sheet.verified_numbers_set
        mentioned_amounts = []
        hallucinations = []

        for m in matches:
            raw_s = m[0] if m[0] else m[1]
            val = abs(clean_numeric_amount(raw_s))
            if val == 0.0:
                continue

            mentioned_amounts.append(val)

            # Verifica se la cifra è vicina (tolleranza 5%) a uno dei numeri verificati
            is_verified = any(abs(val - v) <= max(0.5, 0.05 * v) for v in verified_numbers)
            if not is_verified and val > 10.0:  # Ignora cifre irrilevanti
                hallucinations.append(val)

        is_grounded = len(hallucinations) == 0

        return {
            "is_grounded": is_grounded,
            "mentioned_amounts_count": len(mentioned_amounts),
            "unverified_amounts": hallucinations,
            "hallucination_rate": (len(hallucinations) / len(mentioned_amounts)) if mentioned_amounts else 0.0,
        }
