# 🐾 LORIS — Local Overview of Resources, Investments & Spending

[![Tests](https://img.shields.io/badge/Tests-66%2F66%20Passing-brightgreen)]()
[![Platform](https://img.shields.io/badge/Platform-macOS%20Desktop%20%7C%20Web-blue)]()
[![Privacy](https://img.shields.io/badge/Privacy-100%25%20Local%20%7C%20Zero--Knowledge-success)]()
[![Languages](https://img.shields.io/badge/Languages-Italiano%20%7C%20English-orange)]()
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-yellow?style=flat&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/fabianimarco98)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa?style=flat&logo=github-sponsors)](https://github.com/sponsors/fabianimarco98)

> **LORIS** (*Local Overview of Resources, Investments & Spending*) is an open-source, private, zero-knowledge personal finance system built as a **native macOS desktop application (`LORIS.app`)** and interactive web dashboard. It is driven **100% directly from your bank statements** (CSV, TSV, Excel, PDF), featuring deep retrospective cash flow analytics, internal transfer reconciliation, bilingual interface (Italian 🇮🇹 & English 🇬🇧), generalized Monte Carlo stochastic wealth forecasting, and local AI (Ollama).
> 
> *Named after the nocturnal primate Slow Loris (family Lorisidae, subfamily Lorinae, genera Nycticebus, Xanthonycticebus, Loris), celebrated for its large, reflective, vigilant eyes.*

---

## 🌟 Key Features / Caratteristiche Principali

### 1. 🌐 Bilingual Support / Supporto Bilingue (Italiano & English)
- Switch instantly between **Italian (IT)** and **English (EN)** in the desktop app, web interface, CLI, and reports.
- All category names, cash flow analytics, chart titles, financial metrics, and AI assistant dialogues adapt seamlessly.

### 2. 📊 Deep Retrospective Cash Flow Analytics / Analisi Storica dei Flussi
- Upload all your past statements (months or years of history) in PDF, CSV, Excel (`.xlsx`), or TSV format.
- Retrospective empirical analytics computed automatically:
  - **Total Tracked Period**, cumulative inflows, outflows, and net savings.
  - **Savings Rate (%)** timeline and historical evolution.
  - **Monthly Burn Rate** (mean spending and volatility / standard deviation).
  - **Spending by Category** (auto-categorized: Housing/Rent, Groceries, Utilities, Transport, Leisure, Subscriptions, etc.).
  - **Top Payees / Merchants** ranking by total spent and transaction counts.
  - **Essential vs. Discretionary** spending breakdown.
  - **Automatic Recurring Commitments Detection** (rent, subscriptions, gym, utilities).

### 3. 🎲 Generalized Future Forecasting & Monte Carlo Projections / Previsioni Future
- **Configurable Horizon**: project 12 months (1 yr), 24 months (2 yrs), 36 months (3 yrs), 60 months (5 yrs), or custom months.
- **Empirical Calibration**: starting cash, investments, income, burn rate, and volatility are pre-populated directly from your real statements.
- **Stochastic Multi-Path Engine**: runs 5,000 to 10,000 Monte Carlo paths simulating market returns, inflation, spending variance, and capital gains tax.
- **Risk Metrics & Fan Charts**:
  - Percentile fan chart (5th Pessimistic, 25th, 50th Median, 75th, 95th Optimistic).
  - Cash depletion / insolvency risk probability (chance of cash < 0).
  - Real Net Worth (inflation-adjusted purchasing power).
  - Cash vs. Investment portfolio growth trajectories.

### 4. 🔄 Internal Transfers & Reconciled Giroconti
- Automatically detects and neutralizes transfers between your own accounts (e.g. transfers to savings pockets/vaults, top-ups to prepaid cards, broker deposits, transfers to oneself).
- Prevents artificial inflation of income or spending numbers.

### 5. 🛡️ 100% Local, Zero-Knowledge Privacy Vault
- **Zero cloud calls**: your financial data never leaves your computer.
- Integrated `PIIScrubber` scrubs and masks IBANs, credit cards, tax IDs, and personal names before processing.

### 6. 🧠 Local AI Financial Assistant (Ollama 1-Click)
- Run privacy-preserving AI models directly on your hardware via Ollama (`llama3.2:3b`, `llama3.2:1b`, `qwen2.5:3b`, `mistral:7b`).
- 1-click model installation with real-time streaming download progress bar.
- Offline deterministic rule-based assistant fallback always available.

### 7. 🐾 Native macOS App (`LORIS.app`)
- Standalone macOS app bundle compiled with **Swift 6.x**, **Cocoa/AppKit**, and **WebKit**.
- Custom Slow Loris app icon (`AppIcon.icns`), Spotlight and Finder indexing (`Cmd + Space` -> *LORIS*).
- Clean system menus, dark theme, and silent background process lifecycle management.

---

## 🚀 Getting Started / Avvio Rapido

### 1. Launch Native macOS App (Desktop)
Double-click `LORIS.app` in Finder, launch it via Spotlight, or run:
```bash
open LORIS.app
# or
./run_app.sh
```

### 2. Command Line Interface (CLI)
```bash
# Consolidated portfolio status (Italian or English)
./run_app.sh --cli status --lang en
./run_app.sh --cli status --lang it

# Retrospective historical analytics
./run_app.sh --cli analyze --lang en

# Monte Carlo simulation (e.g. 24 or 60 months)
./run_app.sh --cli simulate --horizon 24 --lang en
./run_app.sh --cli simulate --horizon 60 --n-sims 5000

# Query local AI
./run_app.sh --cli ask "What is my largest expense category and can I increase my investments?" --lang en

# Local AI models management
./run_app.sh --cli models
./run_app.sh --cli models --install llama3.2:3b
./run_app.sh --cli models --start
```

### 3. Web Browser & API Mode
```bash
# Launch in web browser
./run_app.sh --browser

# Launch FastAPI REST backend (Swagger at http://localhost:8000/docs)
./run_app.sh --api
```

### 4. Rebuilding the Native App Bundle
To recompile `LORIS.app` from Swift source code:
```bash
python src/build_macos_app.py
```

---

## 📁 Clean Project Structure / Struttura Progetto

```
v4_speciale/
├── LORIS.app                   # 🐾 Native macOS application bundle (Spotlight-indexed)
├── run_app.sh                  # Universal multi-mode launcher (Desktop, Browser, CLI, API)
├── README.md                   # Project documentation (Bilingual EN/IT)
│
├── input/                      # 📁 User Input Directory
│   ├── bank_statements/        # Drop your real bank statements here (PDF, CSV, Excel)
│   └── templates/              # Optional CSV reference templates
│
├── output/                     # 📁 Exported reports, projections & charts
├── logs/                       # Application runtime logs
│
├── src/                        # 💻 Core Source Code
│   ├── app_streamlit.py        # Bilingual Streamlit dashboard (6 tabs)
│   ├── app.py                  # FastAPI REST API backend
│   ├── cli.py                  # Bilingual command-line interface
│   ├── bank_data_manager.py    # Statement ingestion & retrospective analytics
│   ├── simulation_engine.py    # Generalized Monte Carlo wealth simulator
│   ├── i18n.py                 # Bilingual internationalization engine (IT/EN)
│   ├── build_macos_app.py      # Swift compiler & codesign bundle builder
│   │
│   ├── banking/                # Multi-bank processing module
│   │   ├── anonymizer.py       # Zero-Knowledge PII scrubber
│   │   ├── parsers.py          # Universal parsers (PDF, CSV, Excel, Revolut, Erste, TR)
│   │   ├── portfolio.py        # Asset allocation & internal transfers reconciliation
│   │   └── local_llm.py        # Local Ollama client & streaming model manager
│   │
│   ├── macos_app/              # Native Swift Cocoa/WebKit source & icons
│   │   ├── main.swift          # Swift host app with WebKit & window management
│   │   └── AppIcon.icns        # High-res Slow Loris primate app icon
│   └── assets/                 # UI icons and graphics
│
├── tests/                      # 🧪 Automated Test Suite (42/42 Tests Passing)
│   ├── fixtures/               # Isolated synthetic test statements
│   ├── test_banking.py         # Banking parsers & local LLM tests
│   ├── test_v4_simulation.py   # Simulation engine integration tests
│   ├── test_stress.py          # Heavy stress test suite (10,000+ iterations)
│   └── test_i18n_and_analytics.py # Bilingual i18n & retrospective analytics tests
│
└── docs/                       # Detailed documentation & project status
    └── STATO_PROGETTO.md       # Full Italian architectural guide & logs
```

---

## 🧪 Testing

Run all 66 unit, stress, and integration tests:
```bash
./run_app.sh test
# or
python -m unittest discover tests
```
*Current test suite status: 66/66 passing (100% pass rate).*

---

## 🔒 Privacy & Open-Source Security

LORIS was created with strict privacy principles:
- **No telemetry, no tracking, no cloud dependencies.**
- All parsing occurs in local RAM on your machine.
- Your bank account statements, balances, and transaction details remain strictly on your device.

---

## ☕ Support the Project / Donazioni

Se trovi utile **LORIS** per monitorare le tue finanze, comprendere i tuoi flussi di cassa o pianificare il tuo futuro con le simulazioni Monte Carlo, puoi supportare lo sviluppo indipendente e open-source del progetto!

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support%20LORIS-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/fabianimarco98)

👉 **[Supporta su Buy Me a Coffee (fabianimarco98)](https://www.buymeacoffee.com/fabianimarco98)**

Ogni contributo aiuta a mantenere LORIS gratuito, 100% offline, privato ed in continua evoluzione con nuovi parser per banche italiane ed europee.

