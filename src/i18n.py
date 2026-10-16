# ============================================================
# LORIS — INTERNATIONALIZATION (i18n) MODULE
# Supported Languages: Italian (it), English (en)
# ============================================================
"""
Provides bilingual localization strings and helper functions for
LORIS UI, CLI, simulation engine, and reports.
"""

from typing import Any, Dict

DEFAULT_LANG = "it"
AVAILABLE_LANGUAGES = {
    "it": "🇮🇹 Italiano",
    "en": "🇬🇧 English",
}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # App Title & Subtitles
    "app_title": {
        "it": "🐾 LORIS — Gestione Finanziaria Personale & Previsioni",
        "en": "🐾 LORIS — Personal Financial Analytics & Forecasting",
    },
    "app_subtitle": {
        "it": "Local Overview of Resources, Investments & Spending — 100% Locale, Privato & Basato su Estratti Conto",
        "en": "Local Overview of Resources, Investments & Spending — 100% Local, Private & Bank Statement Driven",
    },
    
    # Navigation Tabs
    "tab_overview": {
        "it": "🏦 Patrimonio & Saldi",
        "en": "🏦 Net Worth & Accounts",
    },
    "tab_analytics": {
        "it": "📊 Analisi Storica & Statistiche",
        "en": "📊 Historical Analytics & Trends",
    },
    "tab_transactions": {
        "it": "📑 Estratti Conto & Transazioni",
        "en": "📑 Statements & Transactions",
    },
    "tab_forecasting": {
        "it": "🎲 Previsioni Future (Monte Carlo)",
        "en": "🎲 Future Forecasts (Monte Carlo)",
    },
    "tab_ai": {
        "it": "💬 Chat AI con LORIS",
        "en": "💬 LORIS AI Chat",
    },
    "tab_settings": {
        "it": "⚙️ Impostazioni & Privacy",
        "en": "⚙️ Settings & Privacy",
    },

    # Language Switcher
    "language": {
        "it": "Lingua",
        "en": "Language",
    },

    # Overview Metrics
    "total_net_worth": {
        "it": "Patrimonio Netto Totale",
        "en": "Total Net Worth",
    },
    "liquid_cash": {
        "it": "Liquidità / Conti Correnti",
        "en": "Liquid Cash / Checking",
    },
    "high_yield_cash": {
        "it": "Liquidità Remunerata / Depositi",
        "en": "High-Yield Cash / Savings",
    },
    "investments": {
        "it": "Investimenti & Titoli",
        "en": "Investments & Securities",
    },
    "liquidity_buffer": {
        "it": "Cuscinetto di Liquidità",
        "en": "Liquidity Buffer",
    },
    "months_of_expenses": {
        "it": "mesi di spese coperte",
        "en": "months of expenses covered",
    },
    "loaded_accounts": {
        "it": "Conti Rilevati",
        "en": "Tracked Accounts",
    },
    "total_transactions": {
        "it": "Transazioni Totali",
        "en": "Total Transactions",
    },
    "asset_allocation": {
        "it": "Ripartizione del Patrimonio (Asset Allocation)",
        "en": "Asset Allocation Breakdown",
    },
    "balance_by_account": {
        "it": "Saldi Consolidati per Conto / Istituto",
        "en": "Consolidated Balances by Account",
    },

    # Historical Analytics Tab
    "historical_title": {
        "it": "Analisi Storica dei Flussi di Cassa",
        "en": "Historical Cash Flow Analytics",
    },
    "historical_subtitle": {
        "it": "Statistiche retrospettive empiriche calcolate direttamente dagli estratti conto caricati.",
        "en": "Retrospective empirical statistics computed directly from your uploaded bank statements.",
    },
    "tracked_period": {
        "it": "Periodo Analizzato",
        "en": "Analyzed Period",
    },
    "total_inflows": {
        "it": "Entrate Totali",
        "en": "Total Inflows",
    },
    "total_outflows": {
        "it": "Uscite Totali",
        "en": "Total Outflows",
    },
    "net_savings": {
        "it": "Risparmio Netto Cumulato",
        "en": "Cumulative Net Savings",
    },
    "avg_monthly_income": {
        "it": "Entrata Media Mensile",
        "en": "Average Monthly Income",
    },
    "avg_monthly_spending": {
        "it": "Spesa Media Mensile (Burn Rate)",
        "en": "Average Monthly Spending (Burn Rate)",
    },
    "spending_std": {
        "it": "Volatilità Spese (Dev. Std)",
        "en": "Spending Volatility (Std. Dev.)",
    },
    "avg_savings_rate": {
        "it": "Tasso di Risparmio Medio",
        "en": "Average Savings Rate",
    },
    "cashflow_trend": {
        "it": "Evoluzione Mensile: Entrate vs Uscite e Risparmio Netto",
        "en": "Monthly Evolution: Income vs Expenses & Net Savings",
    },
    "spending_by_category": {
        "it": "Ripartizione Spese per Categoria",
        "en": "Spending Breakdown by Category",
    },
    "monthly_category_trend": {
        "it": "Evoluzione Spese per Categoria nel Tempo",
        "en": "Spending by Category Over Time",
    },
    "top_payees": {
        "it": "Top 10 Destinatari / Negozi di Spesa",
        "en": "Top 10 Payees / Merchants",
    },
    "data_view_mode": {
        "it": "Vista Dati Analitica",
        "en": "Analytical Data View",
    },
    "view_all_combined": {
        "it": "Tutto Integrato (Banche + Wallet)",
        "en": "All Combined (Banks + Wallet)",
    },
    "view_banks_only": {
        "it": "Solo Estratti Bancari Ufficiali",
        "en": "Official Bank Statements Only",
    },
    "view_wallet_only": {
        "it": "Solo App Spese (Wallet)",
        "en": "Expense Tracker Only (Wallet)",
    },
    "wallet_deepdive_title": {
        "it": "Approfondimento App Spese (Wallet - BudgetBakers)",
        "en": "Expense Tracker Deep-Dive (Wallet - BudgetBakers)",
    },
    "wallet_deepdive_subtitle": {
        "it": "Dati dettagliati e pagamenti in contanti tracciati dall'utente (integrati senza alterare i saldi bancari)",
        "en": "Detailed expenses & cash payments tracked by user (integrated without altering bank balances)",
    },
    "wallet_total_tracked": {
        "it": "Spese Totali Registrate",
        "en": "Total Tracked Expenses",
    },
    "wallet_cash_spent": {
        "it": "Spese in Contanti (CASH)",
        "en": "Cash Spending (CASH)",
    },
    "wallet_electronic_spent": {
        "it": "Spese Bonifici / Carte",
        "en": "Transfer / Card Spending",
    },
    "wallet_cash_pct": {
        "it": "% Spese in Contanti",
        "en": "Cash Spending %",
    },
    "detected_recurring": {
        "it": "Spese Ricorrenti & Fisse Rilevate",
        "en": "Detected Recurring & Fixed Expenses",
    },
    "recurring_explanation": {
        "it": "Identificate automaticamente per frequenza o categoria (affitto, utenze, abbonamenti, palestra).",
        "en": "Automatically identified by frequency or category (housing, utilities, subscriptions, gym).",
    },
    "detected_income": {
        "it": "Flussi di Reddito Rilevati",
        "en": "Detected Income Streams",
    },

    # Statements & Upload Tab
    "upload_title": {
        "it": "Caricamento & Gestione Estratti Conto",
        "en": "Statement Upload & Management",
    },
    "upload_drag_drop": {
        "it": "Trascina qui i tuoi estratti conto (CSV, TSV, Excel .xlsx o PDF)",
        "en": "Drop your bank statements here (CSV, TSV, Excel .xlsx or PDF)",
    },
    "upload_help": {
        "it": "I file vengono salvati ed elaborati al 100% in locale nella cartella protetta input/bank_statements/. Nessun dato lascia mai la macchina.",
        "en": "Files are saved and processed 100% locally in input/bank_statements/. Zero data leaves your device.",
    },
    "upload_success": {
        "it": "Estratti conto salvati ed elaborati con successo!",
        "en": "Bank statements successfully saved and processed!",
    },
    "disk_statements": {
        "it": "Estratti conto caricati da cartella locale (input/bank_statements/)",
        "en": "Statements loaded from local folder (input/bank_statements/)",
    },
    "no_statements_found": {
        "it": "Nessun estratto conto caricato. Trascina i tuoi file qui sopra o copiali in 'input/bank_statements/' per iniziare!",
        "en": "No statements loaded yet. Drop your files above or copy them into 'input/bank_statements/' to start!",
    },
    "filter_transactions": {
        "it": "Filtra Transazioni",
        "en": "Filter Transactions",
    },
    "filter_account": {
        "it": "Conto / Banca",
        "en": "Account / Bank",
    },
    "filter_category": {
        "it": "Categoria",
        "en": "Category",
    },
    "filter_search": {
        "it": "Cerca nella causale / descrizione",
        "en": "Search in description / payee",
    },
    "internal_transfers_table": {
        "it": "Giroconti Interni Riconciliati (Neutralizzati)",
        "en": "Reconciled Internal Transfers (Neutralized)",
    },
    "internal_transfers_desc": {
        "it": "I trasferimenti tra conti propri sono stati identificati e neutralizzati per evitare conteggi doppi.",
        "en": "Transfers between your own accounts have been identified and neutralized to prevent double-counting.",
    },

    # Future Forecasting (Monte Carlo) Tab
    "forecast_title": {
        "it": "Previsioni Finanziarie Future (Simulazione Monte Carlo)",
        "en": "Future Financial Projections (Monte Carlo Simulation)",
    },
    "forecast_subtitle": {
        "it": "Simula migliaia di traiettorie stocastiche per prevedere l'evoluzione del patrimonio, la crescita degli investimenti e il rischio di liquidità.",
        "en": "Simulates thousands of stochastic paths to forecast net worth evolution, investment growth, and liquidity risks.",
    },
    "sim_parameters": {
        "it": "Parametri della Proiezione",
        "en": "Projection Parameters",
    },
    "horizon_months": {
        "it": "Orizzonte Temporale (Mesi)",
        "en": "Time Horizon (Months)",
    },
    "num_simulations": {
        "it": "Numero di Scenari Simulati",
        "en": "Number of Simulated Paths",
    },
    "starting_cash": {
        "it": "Liquidità di Partenza (€)",
        "en": "Starting Liquid Cash (€)",
    },
    "starting_investments": {
        "it": "Investimenti di Partenza (€)",
        "en": "Starting Investments (€)",
    },
    "expected_monthly_income": {
        "it": "Entrate Mensili Attese (€)",
        "en": "Expected Monthly Income (€)",
    },
    "monthly_burn_rate": {
        "it": "Spese Medie Mensili (€)",
        "en": "Average Monthly Spending (€)",
    },
    "spending_volatility": {
        "it": "Volatilità Spese Mensili (€ std)",
        "en": "Monthly Spending Volatility (€ std)",
    },
    "monthly_pac": {
        "it": "Investimento Mensile Programmato / PAC (€)",
        "en": "Monthly Investment Plan / PAC (€)",
    },
    "annual_market_return": {
        "it": "Rendimento Annuo Mercato Atteso (%)",
        "en": "Expected Annual Market Return (%)",
    },
    "annual_market_volatility": {
        "it": "Volatilità Annua Mercato (%)",
        "en": "Annual Market Volatility (%)",
    },
    "annual_inflation": {
        "it": "Inflazione Annua Attesa (%)",
        "en": "Expected Annual Inflation (%)",
    },
    "capital_gains_tax": {
        "it": "Aliquota Fiscale Plusvalenze (%)",
        "en": "Capital Gains Tax Rate (%)",
    },
    "run_simulation_btn": {
        "it": "🎲 Esegui Simulazione Monte Carlo",
        "en": "🎲 Run Monte Carlo Simulation",
    },
    "projection_results": {
        "it": "Risultati al Termine dell'Orizzonte di Proiezione",
        "en": "Projection Results at Target Horizon",
    },
    "pessimistic_p5": {
        "it": "5° Percentile (Scenario Sfavorevole)",
        "en": "5th Percentile (Pessimistic Scenario)",
    },
    "median_p50": {
        "it": "50° Percentile (Mediana / Più Probabile)",
        "en": "50th Percentile (Median / Most Likely)",
    },
    "optimistic_p95": {
        "it": "95° Percentile (Scenario Favorevole)",
        "en": "95th Percentile (Optimistic Scenario)",
    },
    "ruin_probability": {
        "it": "Rischio Scoperto di Cassa (Cassa < 0)",
        "en": "Cash Depletion Risk (Cash < 0)",
    },
    "real_vs_nominal": {
        "it": "Patrimonio Reale (Potere d'Acquisto Odierno)",
        "en": "Real Net Worth (Today's Purchasing Power)",
    },
    "fan_chart_title": {
        "it": "Evoluzione Proiettata del Patrimonio Netto Totale (Fan Chart)",
        "en": "Projected Net Worth Evolution (Fan Chart)",
    },
    "cash_vs_investments_title": {
        "it": "Traiettoria Mediana: Liquidità vs Portafoglio Investimenti",
        "en": "Median Trajectory: Liquid Cash vs Investment Portfolio",
    },

    # AI Assistant Tab
    "ai_title": {
        "it": "Assistente Finanziario AI Locale & Privato",
        "en": "Local & Private AI Financial Assistant",
    },
    "ai_subtitle": {
        "it": "Esegui modelli LLM direttamente sulla tua macchina tramite Ollama o utilizza il motore euristico offline.",
        "en": "Run LLM models directly on your hardware via Ollama or use the offline heuristic engine.",
    },
    "model_selection": {
        "it": "Modello LLM Selezionato",
        "en": "Selected LLM Model",
    },
    "ollama_status": {
        "it": "Stato Server Ollama",
        "en": "Ollama Server Status",
    },
    "install_model": {
        "it": "Installa Nuovo Modello (1-Click)",
        "en": "Install New Model (1-Click)",
    },
    "download_progress": {
        "it": "Download in streaming...",
        "en": "Streaming download in progress...",
    },
    "agent_mode_toggle": {
        "it": "🧰 Modalità agente (usa strumenti sui tuoi dati)",
        "en": "🧰 Agent mode (uses tools on your data)",
    },
    "agent_mode_help": {
        "it": "Il modello locale interroga i tuoi dati con strumenti di sola lettura e verifica ogni cifra. Più lento ma più preciso.",
        "en": "The local model queries your data with read-only tools and checks every figure. Slower but more accurate.",
    },
    "agent_working": {
        "it": "L'agente sta lavorando in locale...",
        "en": "The agent is working locally...",
    },
    "agent_done": {
        "it": "Ragionamento completato",
        "en": "Reasoning complete",
    },
    "agent_fallback": {
        "it": "Agente non disponibile, uso la chat standard.",
        "en": "Agent unavailable, using standard chat.",
    },
    "chat_placeholder": {
        "it": "Fai una domanda sulle tue finanze (es. 'Qual è la mia spesa più alta?', 'Posso aumentare il mio PAC?')...",
        "en": "Ask a question about your finances (e.g., 'What is my highest expense category?', 'Can I increase my monthly investments?')...",
    },
    "quick_audit_btn": {
        "it": "📋 Esegui Audit Completo Patrimonio",
        "en": "📋 Run Full Portfolio Audit",
    },
    "quick_cashflow_btn": {
        "it": "💡 Consigli di Ottimizzazione Risparmio",
        "en": "💡 Savings Optimization Advice",
    },

    # Settings Tab
    "settings_title": {
        "it": "Impostazioni, Integrazioni & Privacy",
        "en": "Settings, Integrations & Privacy",
    },
    "privacy_shield": {
        "it": "Scudo di Anonimizzazione Dati (PII Scrubber)",
        "en": "Data Anonymization Shield (PII Scrubber)",
    },
    "privacy_desc": {
        "it": "Tutti i dati sensibili (IBAN, numeri carta, codici fiscali, nomi) vengono rimossi o mascherati prima dell'elaborazione AI.",
        "en": "All sensitive data (IBANs, card numbers, tax IDs, full names) are scrubbed or masked prior to any AI processing.",
    },
    "optional_google_sheet": {
        "it": "Integrazione Opzionale Google Sheets (Placeholder)",
        "en": "Optional Google Sheets Integration (Placeholder)",
    },
    "google_sheet_help": {
        "it": "Se possiedi un foglio Google con dati aggiuntivi da importare, incolla qui il link pubblico o CSV export. Lascia vuoto per usare solo gli estratti conto.",
        "en": "If you have a Google Sheet with additional data to import, paste the public URL or CSV export link here. Leave empty to use only bank statements.",
    },

    # Common Categories (Bilingual Mapping)
    "cat_rent": {"it": "Affitto & Casa", "en": "Rent & Housing"},
    "cat_groceries": {"it": "Spesa & Alimentari", "en": "Groceries & Food"},
    "cat_utilities": {"it": "Bollette & Utenze", "en": "Utilities & Bills"},
    "cat_gym": {"it": "Palestra & Sport", "en": "Gym & Sports"},
    "cat_dining": {"it": "Ristoranti & Svago", "en": "Dining & Leisure"},
    "cat_transport": {"it": "Trasporti & Viaggi", "en": "Transport & Travel"},
    "cat_subscriptions": {"it": "Abbonamenti & IT", "en": "Subscriptions & Tech"},
    "cat_health": {"it": "Salute & Farmacia", "en": "Health & Pharmacy"},
    "cat_investments": {"it": "Investimenti & PAC", "en": "Investments & Savings"},
    "cat_gambling": {"it": "Svago & Scommesse", "en": "Betting & Gaming"},
    "cat_interest": {"it": "Interessi & Rendite", "en": "Interest & Dividends"},
    "cat_salary": {"it": "Stipendio & Compensi", "en": "Salary & Income"},
    "cat_other_expenses": {"it": "Altre Spese", "en": "Other Expenses"},
    "cat_other_income": {"it": "Entrate Varie", "en": "Other Inflows"},
    "cat_internal_transfer": {"it": "Giroconto Interno", "en": "Internal Transfer"},
    "cash_interest_rate": {"it": "Tasso Liquidità Remunerata (BCE / Trade Republic %)", "en": "High-Yield Cash Interest Rate (ECB / Trade Republic %)"},
    "portfolio_etf_title": {"it": "Portafoglio Investimenti & ETF", "en": "Investment Portfolio & ETFs"},
    "holdings_ticker": {"it": "Ticker / Simbolo", "en": "Ticker / Symbol"},
    "holdings_name": {"it": "Strumento / ETF", "en": "Instrument / ETF"},
    "holdings_shares": {"it": "Quote / Pezzi", "en": "Shares / Units"},
    "holdings_buy_price": {"it": "Prezzo Medio Acquisto", "en": "Avg Buy Price"},
    "holdings_current_price": {"it": "Prezzo Attuale", "en": "Current Price"},
    "holdings_market_value": {"it": "Controvalore", "en": "Market Value"},
    "holdings_pnl": {"it": "Plusvalenza (P&L)", "en": "Gain/Loss (P&L)"},

    # Undo, Revert & File Management
    "undo_upload": {"it": "↩️ Annulla Ultimo Caricamento", "en": "↩️ Undo Last Upload"},
    "undo_edit": {"it": "↩️ Annulla Ultima Modifica", "en": "↩️ Undo Last Change"},
    "reset_overrides": {"it": "♻️ Ripristina Dati Originali", "en": "♻️ Reset to Original Data"},
    "delete_file": {"it": "🗑️ Elimina File", "en": "🗑️ Delete File"},
    "file_deleted_success": {"it": "File eliminato con successo!", "en": "File deleted successfully!"},
    "undo_success": {"it": "Azione annullata con successo!", "en": "Action undone successfully!"},
    "loaded_files_list": {"it": "File Caricati su Disco:", "en": "Statements Stored on Disk:"},

    # Manual Adjustments & Overrides
    "manual_balances_title": {"it": "✏️ Modifica Manuale Saldi dei Conti", "en": "✏️ Manual Account Balances Editor"},
    "manual_balances_desc": {
        "it": "Puoi correggere o forzare il saldo finale di qualunque conto se l'estratto conto non lo riporta o presenta anomalie.",
        "en": "You can adjust or override the balance of any account if the statement missed it or had an anomaly."
    },
    "save_balances_btn": {"it": "💾 Salva Saldi Personalizzati", "en": "💾 Save Custom Balances"},
    "custom_balance": {"it": "Saldo Manuale (€)", "en": "Custom Balance (€)"},
    "original_balance": {"it": "Saldo Rilevato (€)", "en": "Detected Balance (€)"},
    "edit_tx_title": {"it": "✏️ Modifica Transazioni & Categorie", "en": "✏️ Edit Categories & Transactions"},
    "edit_tx_help": {
        "it": "Puoi modificare la categoria, contrassegnare come giroconto o escludere movimenti direttamente dalla tabella.",
        "en": "You can edit categories, flag internal transfers, or exclude transactions directly in the table."
    },
    "save_tx_changes": {"it": "💾 Salva Modifiche Transazioni", "en": "💾 Save Transaction Edits"},
    "manual_tx_title": {"it": "➕ Aggiungi Movimento Manuale", "en": "➕ Add Manual Transaction"},
    "add_tx_btn": {"it": "➕ Aggiungi Movimento", "en": "➕ Add Transaction"},
    "tx_added_success": {"it": "Movimento aggiunto con successo!", "en": "Transaction added successfully!"},
    "tx_saved_success": {"it": "Modifiche alle transazioni salvate con successo!", "en": "Transaction edits saved successfully!"},
    "balances_saved_success": {"it": "Saldi personalizzati salvati con successo!", "en": "Custom balances saved successfully!"},
    "reset_success": {"it": "Tutti i dati sono stati ripristinati alle letture originali degli estratti conto!", "en": "All data has been reset to original statement readings!"},

    # Donations & Community Support
    "support_project_title": {"it": "☕ Supporta il Progetto", "en": "☕ Support the Project"},
    "support_project_desc": {
        "it": "Se trovi utile LORIS per monitorare le tue finanze, comprendere i tuoi flussi di cassa o pianificare con le simulazioni Monte Carlo, puoi supportare lo sviluppo indipendente e open-source!",
        "en": "If you find LORIS useful for tracking your finances, understanding cash flows, or planning with Monte Carlo simulations, you can support its independent open-source development!"
    },
    "buy_me_a_coffee_btn": {"it": "☕ Offrimi un Caffè su Buy Me a Coffee", "en": "☕ Buy Me a Coffee"},
    "github_repo_btn": {"it": "⭐ Repository su GitHub", "en": "⭐ Star on GitHub"},
    "github_sponsor_btn": {"it": "💖 Sponsorizza su GitHub", "en": "💖 Sponsor on GitHub"},
    "support_sidebar_box": {"it": "Ti piace LORIS?", "en": "Enjoying LORIS?"},
    "support_sidebar_sub": {
        "it": "Supporta lo sviluppo indipendente e 100% offline!",
        "en": "Support 100% private, offline open-source development!"
    },
}


def t(key: str, lang: str = "it", **kwargs: Any) -> str:
    """
    Restituisce la stringa localizzata per la chiave specificata.
    Se la chiave o la lingua non è presente, esegue fallback su italiano o sulla chiave stessa.
    Supporta formattazione con parametri posizionali o nominali.
    """
    lang = lang.lower() if lang else DEFAULT_LANG
    if lang not in ["it", "en"]:
        lang = DEFAULT_LANG

    entry = TRANSLATIONS.get(key)
    if not entry:
        return key

    text = entry.get(lang) or entry.get("it") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def get_category_translation(category_name: str, lang: str = "it") -> str:
    """Traduce il nome di una categoria nella lingua di destinazione."""
    lang = lang.lower() if lang in ["it", "en"] else "it"
    if lang == "it":
        return category_name

    mapping = {
        "Affitto": "Rent & Housing",
        "Affitto & Casa": "Rent & Housing",
        "Spesa & Alimentari": "Groceries & Food",
        "Bollette & Utenze": "Utilities & Bills",
        "Palestra & Sport": "Gym & Sports",
        "Ristoranti & Svago": "Dining & Leisure",
        "Trasporti & Viaggi": "Transport & Travel",
        "Abbonamenti & IT": "Subscriptions & Tech",
        "Salute & Farmacia": "Health & Pharmacy",
        "Investimenti & PAC": "Investments & Savings",
        "Investimento ETF / Azioni": "ETF & Equity Investments",
        "Svago & Scommesse": "Betting & Gaming",
        "Cazzate e scommesse": "Betting & Gaming",
        "Interessi & Rendite": "Interest & Dividends",
        "Interessi Attivi": "Interest & Yield",
        "Stipendio": "Salary & Income",
        "Stipendio & Compensi": "Salary & Income",
        "Altre Spese": "Other Expenses",
        "Entrate Varie": "Other Inflows",
        "Giroconto Interno": "Internal Transfer",
        "Giroconto": "Internal Transfer",
        "Da Classificare": "To Classify",
    }
    return mapping.get(category_name, category_name)
