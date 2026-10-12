# ============================================================
# BANKING MODULE — CLI INTERFACE (100% LOCALE & RISERVATO)
# ============================================================
"""
Interfaccia a riga di comando per analizzare estratti conto multipli,
rilevare giroconti, generare asset allocation e diagnosticare il patrimonio.

Uso:
    python -m banking.cli input/sample_bank_statements/
"""

import argparse
import os
from pathlib import Path
import sys

from .anonymizer import PIIScrubber
from .parsers import parse_bank_statement
from .portfolio import PortfolioAggregator, ASSET_CLASS_LABELS
from .local_llm import LocalLLMClient


def main():
    parser = argparse.ArgumentParser(
        description="Analisi Patrimoniale Multi-Banca Anonima & Locale (v3)"
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Percorso di uno o più file di estratto conto (CSV, Excel, PDF) o cartelle.",
    )
    parser.add_argument(
        "--anonymize-preview",
        action="store_true",
        help="Stampa un estratto anonimizzato delle prime transazioni per verificare il privacy scrubbing.",
    )
    parser.add_argument(
        "--ai-audit",
        action="store_true",
        help="Esegue l'audit diagnostico tramite LLM locale o motore offline.",
    )
    args = parser.parse_args()

    # Raccogli tutti i file
    target_files = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.suffix.lower() in [".csv", ".xlsx", ".xls", ".pdf"] and not f.name.startswith("."):
                    target_files.append(f)
        elif p.is_file():
            target_files.append(p)

    if not target_files:
        print("❌ Nessun file di estratto conto valido trovato.")
        sys.exit(1)

    print(f"🏦 Rilevati {len(target_files)} estratti conto da elaborare...")
    aggregator = PortfolioAggregator()

    for f in target_files:
        try:
            with open(f, "rb") as fp:
                content = fp.read()
            stmt = parse_bank_statement(content, f.name)
            aggregator.add_statement(stmt)
            print(f"  ✅ {f.name:<35} → {stmt.institution} ({len(stmt.transactions)} mov, saldo: €{stmt.ending_balance:,.2f})")
        except Exception as e:
            print(f"  ⚠️ Errore lettura {f.name}: {e}")

    summary = aggregator.aggregate()

    print("\n" + "═" * 64)
    print("📊 PANORAMICA PATRIMONIALE COMPLESSIVA (MULTI-BANCA)")
    print("═" * 64)
    print(f"Patrimonio Netto Totale Accertato:  € {summary.total_net_worth:>10,.2f}")
    print(f"  • Liquidità Immediata (Conti C/C):  € {summary.total_liquid_cash:>10,.2f} ({summary.asset_allocation_pct.get('LIQUID_CASH', 0):.1f}%)")
    print(f"  • Liquidità Remunerata (Depositi):   € {summary.total_high_yield_cash:>10,.2f} ({summary.asset_allocation_pct.get('HIGH_YIELD_CASH', 0):.1f}%)")
    print(f"  • Investimenti (ETF / Broker):       € {summary.total_investments:>10,.2f} ({summary.asset_allocation_pct.get('INVESTMENTS', 0):.1f}%)")
    print(f"Burn Rate Mensile Stimato:          € {summary.monthly_burn_rate:>10,.2f} / mese")
    print(f"Buffer di Liquidità (Autonomia):     {summary.liquidity_buffer_months:>10.1f} mesi")

    if not summary.internal_transfers.empty:
        print("\n🔄 Giroconti e Trasferimenti Interni Rilevati:")
        for _, tr in summary.internal_transfers.iterrows():
            print(f"  • {tr['date'].strftime('%d/%m/%Y')}: €{tr['amount']:,.2f} da [{tr['from_account']}] a [{tr['to_account']}]")

    if args.anonymize_preview:
        scrubber = PIIScrubber()
        print("\n🔒 Anteprima Privacy Scrubbing (Prime 5 transazioni aggregate):")
        sample_df = summary.all_transactions.head(5).copy()
        if not sample_df.empty and "description" in sample_df.columns:
            for idx, r in sample_df.iterrows():
                anon_d = scrubber.anonymize_text(r["description"])
                print(f"  [{r['date'].strftime('%d/%m/%Y')}] €{r['amount']:>8.2f} | {anon_d}")

    if args.ai_audit:
        client = LocalLLMClient()
        status = client.check_health()
        print(f"\n🧠 Audit Finanziario ({status.provider} - {status.model_name}):")
        audit_text = client.generate_portfolio_audit({
            "total_net_worth": summary.total_net_worth,
            "total_liquid_cash": summary.total_liquid_cash,
            "total_high_yield_cash": summary.total_high_yield_cash,
            "total_investments": summary.total_investments,
            "monthly_burn_rate": summary.monthly_burn_rate,
            "liquidity_buffer_months": summary.liquidity_buffer_months,
        })
        print(audit_text)


if __name__ == "__main__":
    main()
