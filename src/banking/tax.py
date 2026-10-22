# ============================================================
# BANKING MODULE — REGIMI FISCALI (aliquote usate dalla previsione)
# ============================================================
"""
Aliquote semplificate per persone fisiche residenti, usate dal Monte Carlo:
- plusvalenze su ETF/azioni (applicate alla vendita e come imposta latente sul patrimonio finale)
- interessi sulla liquidità (prelevati alla fonte, quindi netti nel tasso di cassa)
- imposta di bollo: percentuale annua sul valore dei titoli e importo fisso sul conto oltre una soglia

Il paese si imposta in `input/user_profile.json` con "tax_country" (es. "IT", "AT").
Senza indicazione si assume l'Italia e il risultato lo segnala (`tax_country_assumed`).

Limiti noti: titoli di Stato (IT 12,5%), ETF armonizzati con tassazione per redditi diversi,
compensazione delle minusvalenze, regime amministrato vs dichiarativo, patrimoniale su immobili
e conti esteri non sono modellati.
"""

from dataclasses import dataclass
from typing import Optional

from .user_profile import get_profile


@dataclass(frozen=True)
class TaxRegime:
    country: str
    capital_gains: float            # aliquota su plusvalenze di titoli
    interest: float                 # aliquota sugli interessi della liquidità
    securities_stamp_pct: float     # imposta di bollo annua sul valore dei titoli (frazione)
    account_stamp_eur: float        # bollo annuo fisso sul conto corrente
    account_stamp_threshold: float  # saldo oltre il quale si applica il bollo fisso


REGIMES = {
    "IT": TaxRegime("IT", 0.26, 0.26, 0.002, 34.20, 5000.0),
    "AT": TaxRegime("AT", 0.275, 0.275, 0.0, 0.0, 0.0),     # KESt 27,5%
}
DEFAULT_COUNTRY = "IT"


def tax_regime(country: Optional[str] = None) -> TaxRegime:
    """Regime del paese indicato, altrimenti quello del profilo, altrimenti l'Italia."""
    code = str(country or get_profile().get("tax_country") or "").strip().upper()
    return REGIMES.get(code, REGIMES[DEFAULT_COUNTRY])


def tax_country_assumed(country: Optional[str] = None) -> bool:
    """True se il paese non è stato indicato (o non è supportato) e si è ripiegato sull'Italia."""
    code = str(country or get_profile().get("tax_country") or "").strip().upper()
    return code not in REGIMES
