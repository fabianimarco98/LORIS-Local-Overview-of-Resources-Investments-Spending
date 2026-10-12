#!/usr/bin/env python3
# ============================================================
# CLI TOOL — EXPENSES PREDICTION & BANKING (LORIS v4_speciale)
# 100% Statement-Driven with Local AI Management & Bilingual CLI
# ============================================================
import argparse
import sys
from pathlib import Path
import pandas as pd

import banking
from banking.anonymizer import PIIScrubber
from banking.local_llm import LocalLLMClient, RECOMMENDED_MODELS
from banking.portfolio import ASSET_CLASS_LABELS, get_asset_class_label
import bank_data_manager as bdm
import simulation_engine as se
from i18n import t, get_category_translation

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if (BASE_DIR.parent / "input").exists() else BASE_DIR
STATEMENTS_DIR = PROJECT_ROOT / "input" / "bank_statements"


def cmd_status(args):
    lang = getattr(args, "lang", "it")
    print("=" * 70)
    print(" 🐾 LORIS — Local Overview of Resources, Investments & Spending")
    print("=" * 70)
    statements, summary = bdm.load_all_bank_statements(str(STATEMENTS_DIR), as_of_date=args.as_of)
    print(f"📁 {t('loaded_accounts', lang)}: {len(statements)}")
    if len(statements) == 0:
        if lang == "it":
            print("ℹ️  Nessun estratto conto presente in 'input/bank_statements/'")
            print("👉 Copia o trascina qui i tuoi estratti conto (CSV, Excel o PDF) per avviare l'analisi!")
        else:
            print("ℹ️  No statements found in 'input/bank_statements/'")
            print("👉 Copy or drop your bank statements (CSV, Excel or PDF) here to start!")
        print("=" * 70)
        return

    for stmt in statements:
        print(f"  • {stmt.institution:18} [{stmt.account_id:15}] Saldo: €{stmt.ending_balance:10,.2f} ({len(stmt.transactions)} mov.)")

    print("-" * 70)
    print(f"💰 {t('total_net_worth', lang):30}: € {summary.total_net_worth:12,.2f}")
    print(f"💧 {t('liquid_cash', lang):30}: € {summary.total_liquid_cash:12,.2f}")
    print(f"📈 {t('high_yield_cash', lang):30}: € {summary.total_high_yield_cash:12,.2f}")
    print(f"📊 {t('investments', lang):30}: € {summary.total_investments:12,.2f}")
    print(f"🔥 {t('avg_monthly_spending', lang):30}: € {summary.monthly_burn_rate:12,.2f}")
    print(f"🛡️  {t('liquidity_buffer', lang):30}: {summary.liquidity_buffer_months:12.1f} " + ("Mesi" if lang == "it" else "Months"))
    print("-" * 70)
    print(f"📊 {t('asset_allocation', lang)}:")
    for ac, val in summary.asset_allocation.items():
        pct = summary.asset_allocation_pct.get(ac, 0.0)
        label = get_asset_class_label(ac, lang)
        print(f"  • {label:42}: €{val:10,.2f} ({pct:5.1f}%)")

    if not summary.internal_transfers.empty:
        print("-" * 70)
        print(f"🔄 {t('internal_transfers_table', lang)}: {len(summary.internal_transfers)}")
        for _, tr in summary.internal_transfers.iterrows():
            print(f"  [{tr['date']}] €{tr['amount']:.2f}: {tr['from_account']} -> {tr['to_account']}")
    print("=" * 70)


def cmd_analyze(args):
    lang = getattr(args, "lang", "it")
    print("=" * 70)
    print(f" 📊 {t('historical_title', lang).upper()}")
    print("=" * 70)
    _, summary = bdm.load_all_bank_statements(str(STATEMENTS_DIR))
    df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
    stats = bdm.compute_bank_monthly_statistics(df_cat)

    if summary.all_transactions.empty:
        print(t("no_statements_found", lang))
        print("=" * 70)
        return

    print(f"📅 {t('tracked_period', lang):30}: {stats['total_tracked_months']} " + ("Mesi" if lang == "it" else "Months"))
    print(f"💵 {t('total_inflows', lang):30}: € {stats['total_inflow']:12,.2f}")
    print(f"💸 {t('total_outflows', lang):30}: € {stats['total_outflow']:12,.2f}")
    print(f"💰 {t('net_savings', lang):30}: € {stats['net_savings']:12,.2f}")
    print(f"📈 {t('avg_savings_rate', lang):30}: {stats['average_savings_rate']:12.1f}%")
    print(f"🔥 {t('avg_monthly_spending', lang):30}: € {stats['monthly_expenses_mean']:12,.2f} (± €{stats['monthly_expenses_std']:,.2f})")
    print(f"💼 {t('detected_income', lang):30}: € {stats['detected_salary']:12,.2f}/" + ("mese" if lang == "it" else "month"))

    # Top Payees
    top_p = stats.get("top_payees", pd.DataFrame())
    if not top_p.empty:
        print("-" * 70)
        print(f"🏷️ {t('top_payees', lang)}:")
        for _, r in top_p.head(5).iterrows():
            print(f"  • {str(r['beneficiario'])[:30]:30}: €{r['totale_speso']:8,.2f} ({r['numero_transazioni']} tx)")

    # Category Summary
    cat_df = stats.get("category_summary", pd.DataFrame())
    if not cat_df.empty:
        print("-" * 70)
        print(f"📑 {t('spending_by_category', lang)}:")
        for _, r in cat_df.head(6).iterrows():
            c_label = get_category_translation(r['category'], lang)
            print(f"  • {c_label:30}: €{r['totale_uscito']:8,.2f} ({r.get('percentuale', 0.0):4.1f}%)")

    print("=" * 70)


def cmd_simulate(args):
    lang = getattr(args, "lang", "it")
    horizon = args.horizon or 36
    print("=" * 70)
    print(f" 🎲 {t('forecast_title', lang).upper()} ({args.n_sims:,} SCENARIOS — {horizon} " + ("MESI" if lang == "it" else "MONTHS") + ")")
    print("=" * 70)
    _, summary = bdm.load_all_bank_statements(str(STATEMENTS_DIR))
    df_cat = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
    stats = bdm.compute_bank_monthly_statistics(df_cat)

    if summary.all_transactions.empty:
        if lang == "it":
            print("ℹ️  Nessun estratto conto presente in 'input/bank_statements/'")
            print("👉 Simulazione eseguita con parametri di stima standard.")
        else:
            print("ℹ️  No statements found in 'input/bank_statements/'")
            print("👉 Running simulation with standard default estimates.")
        starting_cash = args.cash if args.cash is not None else 3000.0
        starting_inv = args.inv if args.inv is not None else 1000.0
    else:
        starting_cash = args.cash if args.cash is not None else summary.recommended_starting_cash
        starting_inv = args.inv if args.inv is not None else summary.total_investments

    emp_salary = stats.get("detected_salary", 0.0)
    emp_burn_mean = stats.get("monthly_expenses_mean", 0.0)
    emp_burn_std = stats.get("monthly_expenses_std", 0.0)

    print(f"Parametri di partenza:" if lang == "it" else "Initial Parameters:")
    print(f"  • {t('starting_cash', lang)}:        € {starting_cash:,.2f}")
    print(f"  • {t('starting_investments', lang)}: € {starting_inv:,.2f}")
    print(f"  • {t('expected_monthly_income', lang)}:     € {emp_salary:,.2f}/" + ("mese" if lang == "it" else "month"))
    print(f"  • {t('monthly_burn_rate', lang)}:           € {emp_burn_mean:,.2f}/" + ("mese" if lang == "it" else "month") + f" (std: €{emp_burn_std:,.2f})")
    print(f"  • {t('monthly_pac', lang)}:                 € {args.pac or 100.0:,.2f}")
    print(f"  • {t('horizon_months', lang)}:              {horizon} " + ("mesi" if lang == "it" else "months"))

    res = se.run_simulation(
        start="2026-10-01",
        horizon_months=horizon,
        n_sims=args.n_sims,
        pac=args.pac or 100.0,
        starting_cash=starting_cash,
        starting_inv=starting_inv,
        monthly_income=emp_salary,
        recurring_df=None,
        shocks_df=None,
        monthly_expenses_mean=emp_burn_mean,
        monthly_expenses_std=emp_burn_std,
    )

    print("-" * 70)
    print(f"📈 {t('projection_results', lang).upper()}:")
    print(f"  • {t('pessimistic_p5', lang):42}: € {res['p5']:10,.2f}")
    print(f"  • 25° Percentile:                           € {res['p25']:10,.2f}")
    print(f"  • {t('median_p50', lang):42}: € {res['p50']:10,.2f}")
    print(f"  • 75° Percentile:                           € {res['p75']:10,.2f}")
    print(f"  • {t('optimistic_p95', lang):42}: € {res['p95']:10,.2f}")
    print(f"  • {t('ruin_probability', lang):42}:   {res['prob_ruin']:5.1f}%")
    print(f"  • {t('real_vs_nominal', lang):42}: € {res['p50_real']:10,.2f}")
    print("=" * 70)


def cmd_ask(args):
    lang = getattr(args, "lang", "it")
    print("=" * 70)
    print(" 🐾 LORIS — LOCAL AI QUERY (ZERO-KNOWLEDGE)")
    print("=" * 70)
    _, summary = bdm.load_all_bank_statements(str(STATEMENTS_DIR))
    df = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)

    scrubber = PIIScrubber()
    anon_df = scrubber.anonymize_dataframe(df.head(40), ["description"]) if not df.empty else pd.DataFrame()

    llm = LocalLLMClient(preferred_model=args.model)
    status = llm.check_health()
    if status.is_available:
        print(f"🟢 Connected to local {status.provider} (Model: {status.model_name})")
    else:
        print("🟡 Ollama offline -> Using deterministic rule engine")

    print(f"\nQuestion: '{args.question}'\n")
    ans = llm.query_portfolio_insights(summary, anon_df, args.question)
    print("-" * 70)
    print(ans)
    print("=" * 70)


def cmd_models(args):
    print("=" * 70)
    print(" 🤖 LOCAL AI MODEL MANAGEMENT (OLLAMA / LLAMA.CPP)")
    print("=" * 70)
    client = LocalLLMClient()
    st = client.check_health()

    if args.start:
        print("▶️ Starting Ollama daemon in background...")
        ok, msg = client.start_ollama_daemon()
        print(f"{'✅' if ok else '❌'} {msg}")
        return

    if args.install:
        tag = args.install.strip()
        print(f"📥 Downloading and installing model '{tag}'...")
        if not st.is_available:
            print("❌ Ollama daemon not reachable. Start it with: ./cli.py models --start")
            return
        last_pct = -1
        for evt in client.pull_model_stream(tag):
            if evt.get("error"):
                print(f"\n❌ Error: {evt.get('status')}")
                return
            pct = int(evt.get("percent", 0.0))
            if pct != last_pct and pct % 10 == 0:
                print(f"  • {evt.get('status')} [{pct}%]")
                last_pct = pct
            if evt.get("done"):
                print(f"\n✅ Model '{tag}' installed successfully!")
                return
        print(f"\n✅ Completed.")
        return

    if st.is_available:
        print(f"🟢 Ollama Daemon: ACTIVE on localhost:11434")
        print(f"🎯 Preferred model: {st.model_name}\n")
        print("📦 INSTALLED MODELS:")
        details = client.get_detailed_models()
        if details:
            for m in details:
                print(f"  • {m['name']:25} ({m['size_gb']:4.1f} GB) [ID: {m['digest']}]")
        else:
            print("  (No models installed yet)")
    else:
        print("🟡 Ollama Daemon: INACTIVE")
        cli_ok, cli_path = client.is_ollama_cli_available()
        if cli_ok:
            print(f"ℹ️ Executable detected: {cli_path}")
            print("👉 Start with: ./cli.py models --start")
        else:
            print(f"👉 Install with: brew install ollama")

    print("\n🌟 RECOMMENDED MODELS FOR LORIS:")
    for r in RECOMMENDED_MODELS:
        installed = any(r['tag'] in m['name'] for m in client.get_detailed_models()) if st.is_available else False
        badge = " [✅ INSTALLED]" if installed else f" (Install: ./cli.py models --install {r['tag']})"
        print(f"  • {r['display_name']:32}: ~{r['size_est']} {badge}")
    print("=" * 70)


def cmd_anonymize(args):
    scrubber = PIIScrubber()
    clean = scrubber.anonymize_text(args.text)
    is_clean, leaks = scrubber.audit_cleanliness(clean)
    print("Anonymized Output:")
    print(clean)
    print(f"\nSecurity Audit: {'✅ 100% Clean' if is_clean else f'⚠️ Leaks found: {leaks}'}")


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--lang", type=str, choices=["it", "en"], default="it", help="Language / Lingua (default: it)")

    parser = argparse.ArgumentParser(description="LORIS — Local Overview of Resources, Investments & Spending", parents=[parent_parser])
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Status
    p_status = subparsers.add_parser("status", parents=[parent_parser], help="Show consolidated portfolio & accounts status")
    p_status.add_argument("--as-of", type=str, help="Cutoff date (e.g. 2026-09-30)")
    p_status.set_defaults(func=cmd_status)

    # Analyze
    p_analyze = subparsers.add_parser("analyze", parents=[parent_parser], help="Show deep retrospective cashflow & category statistics")
    p_analyze.set_defaults(func=cmd_analyze)

    # Simulate
    p_sim = subparsers.add_parser("simulate", parents=[parent_parser], help="Run generalized Monte Carlo simulation (100% statement-driven)")
    p_sim.add_argument("--horizon", type=int, default=36, help="Projection horizon in months (default: 36)")
    p_sim.add_argument("--n-sims", type=int, default=5000, help="Number of simulation paths (default: 5000)")
    p_sim.add_argument("--cash", type=float, help="Starting cash override")
    p_sim.add_argument("--inv", type=float, help="Starting investments override")
    p_sim.add_argument("--pac", type=float, help="Monthly PAC investment override")
    p_sim.set_defaults(func=cmd_simulate)

    # Ask
    p_ask = subparsers.add_parser("ask", parents=[parent_parser], help="Query local AI on anonymized financial data")
    p_ask.add_argument("question", type=str, help="Question for the AI")
    p_ask.add_argument("--model", type=str, help="Local model tag (e.g. llama3.2:3b)")
    p_ask.set_defaults(func=cmd_ask)

    # Models
    p_models = subparsers.add_parser("models", parents=[parent_parser], help="Manage and install local AI models")
    p_models.add_argument("--list", action="store_true", help="List installed and recommended models")
    p_models.add_argument("--install", type=str, help="Download and install a model (e.g. llama3.2:1b)")
    p_models.add_argument("--start", action="store_true", help="Start Ollama daemon in background")
    p_models.set_defaults(func=cmd_models)

    # Anonymize
    p_anon = subparsers.add_parser("anonymize", parents=[parent_parser], help="Test PII scrubber on text")
    p_anon.add_argument("text", type=str, help="Text to anonymize")
    p_anon.set_defaults(func=cmd_anonymize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
