# 🐾 LORIS — STATO DEL PROGETTO (`v4_speciale`)
### Local Overview of Resources, Investments & Spending (Primate Loris Edition)

**Ultimo Aggiornamento:** 10 Ottobre 2026  
**Stato Operativo:** 🟢 Operativo & Verificato  
**Test Suite:** Test Unitari & Stress Test Completi (100% Pass)

---

## 🎯 Obiettivi & Evoluzione di LORIS (`v4_speciale`)

**LORIS** (*Local Overview of Resources, Investments & Spending* — intitolato all'omonimo primate notturno della famiglia *Lorisidae* / generi *Nycticebus*, *Xanthonycticebus*, *Loris*) è il sistema finanziario autonomo, privato ed open-source trasformato in una **vera applicazione desktop nativa per macOS** ed **estremamente immediato e fondato al 100% unicamente sugli estratti conto bancari**:

1. **Vera Applicazione Desktop macOS (`LORIS.app`)**:
   - Non più un semplice script `.sh` da terminale: pacchetto `.app` nativo con icona ad alta risoluzione (`AppIcon.icns`) raffigurante il primate Slow Loris (*Nycticebus*) con occhi grandi e riflettenti, codice compilato in Swift con Cocoa/AppKit e WebKit.
   - Si avvia con un doppio clic dal Finder, dal Dock o tramite **Spotlight** (`Cmd + Spazio` -> *LORIS*).
   - Finestra nativa scura (*Dark Aqua*), menu di sistema macOS completo (Modifica con copia/incolla, Vista con ricarica `Cmd+R`, Informazioni e chiusura pulita `Cmd+Q`).
   - Gestione automatica del ciclo di vita: avvia in background il motore locale senza aprire finestre di terminale e termina tutti i processi figli alla chiusura.
2. **100% Basato Solo su Estratti Conto (Zero Tabelle Ausiliarie Richieste)**:
   - Non richiede file di configurazione esterni, né la compilazione di tabelle per le spese ricorrenti.
   - Tutti i parametri chiave (cassa reale, investimenti, stipendio o salario regolare, burn rate medio mensile e deviazione standard) vengono estratti direttamente e matematicamente dai file bancari (Erste Bank Austria George, Trade Republic, Revolut, Banche Italiane).
3. **Analisi Storica & Statistiche Retrospettive**:
   - Analisi retrospettiva completa di tutti gli estratti conto caricati (PDF, CSV, Excel): periodo tracciato, entrate totali, uscite totali, tasso di risparmio medio mensile (%), volatilità delle spese (dev. std), ranking top destinatari di spesa e rilevamento automatico impegni fissi.
4. **Bilinguismo Completo (Italiano 🇮🇹 & English 🇬🇧)**:
   - Supporto nativo bilingue in tutta l'applicazione (Desktop, Dashboard Web a 6 tab, CLI con opzione `--lang` e reportistica).
5. **Neutralizzazione Istantanea dei Giroconti**:
   - I trasferimenti interni tra conti propri (ricariche carte, trasferimenti verso pocket/salvadanai, conversioni valuta ed esborsi a se stessi) vengono riconciliati e neutralizzati automaticamente, impedendo duplicazioni contabili nelle entrate e uscite.
6. **Simulazione Monte Carlo Empirica Generalizzata**:
   - Il motore stocastico (5.000 scenari su orizzonte temporale flessibile: 12, 24, 36, 60 mesi) si calibra in modo automatico sui flussi reali degli estratti conto, restituendo probabilità di scoperto e scenari a ventaglio senza alcuna configurazione manuale.
7. **Selezione Modelli AI Locali & Installazione 1-Click**:
   - Riconoscimento dinamico di tutti i modelli Ollama installati sulla macchina.
   - Catalogo di modelli consigliati per la finanza personale (`llama3.2:3b`, `llama3.2:1b`, `qwen2.5:3b`, `mistral:7b`, ecc.) o campo per tag personalizzati.
   - **Download e installazione 1-click in streaming**: barra di avanzamento e percentuale in tempo reale sia nella dashboard che da CLI (`./cli.py models --install <tag>`) e API REST (`/api/llm/pull`).
   - Se Ollama non è in esecuzione: avvio con 1-click (`./cli.py models --start`). Se assente, istruzioni dirette (`brew install ollama`).
   - Fallback sempre attivo: il motore euristico deterministico offline garantisce risposte immediate anche a server spento.
8. **Zero-Knowledge Privacy Shield**:
   - Modulo `PIIScrubber` integrato a monte: maschera IBAN, carte di credito, codici fiscali e nomi prima di qualsiasi elaborazione. Nessun dato lascia mai il computer.

---

## 🏗️ Architettura & Componenti

| Componente | File Sorgente | Funzione Principale |
| :--- | :--- | :--- |
| **Applicazione Desktop macOS** | `LORIS.app` / `src/macos_app/` | App nativa macOS (Swift 6.x + AppKit + WebKit) con menu di sistema, icona e gestione daemon |
| **Builder macOS App** | [build_macos_app.py](../src/build_macos_app.py) | Compilazione binario nativo, generazione icona con `iconutil` e firma ad-hoc codesign |
| **Dashboard Web** | [app_streamlit.py](../src/app_streamlit.py) | Interfaccia a 6 tab bilingue (IT/EN) con analisi storica profonda, Monte Carlo e chat locale |
| **Motore i18n Bilingue** | [i18n.py](../src/i18n.py) | Traduzioni e dizionari dinamici Italiano 🇮🇹 / English 🇬🇧 per UI, CLI e categorie |
| **API REST** | [app.py](../src/app.py) | Backend FastAPI con endpoint per portfolio, transazioni, simulazione empirica e gestione/pull modelli AI |
| **Interfaccia CLI** | [cli.py](../src/cli.py) | Tool CLI bilingue con comandi `status`, `analyze`, `simulate`, `ask`, `models`, `anonymize` |
| **Bank Data Manager** | [bank_data_manager.py](../src/bank_data_manager.py) | Ingestion estratti conto, analisi retrospettiva flussi, cashflow mensile e rilevamento spese fisse |
| **Simulation Engine** | [simulation_engine.py](../src/simulation_engine.py) | Motore Monte Carlo stocastico (5.000 simulazioni) con orizzonte configurabile (12-120 mesi) |
| **Modulo Bancario** | `src/banking/` | Parser universali (PDF, CSV, Excel), `PIIScrubber`, `PortfolioAggregator`, `LocalLLMClient` |
| **Launcher Globale** | [run_app.sh](../run_app.sh) | Launcher intelligente che avvia la vera app nativa LORIS.app (o `--browser`, `--api`, `--cli`, `--build`) |

---

## 📈 Tab della Dashboard Web Bilingue (`app_streamlit.py`)

1. **🏦 Patrimonio & Saldi / Net Worth & Accounts**: Saldi consolidati per banca/broker, Donut Chart Asset Allocation e conti tracciati.
2. **📊 Analisi Storica & Statistiche / Historical Analytics**: Periodo tracciato, entrate/uscite totali, risparmio netto, tasso di risparmio, evoluzione mensile cash flow, ripartizione spese per categoria, top 10 esercenti/beneficiari e spese fisse rilevate.
3. **📑 Estratti Conto & Transazioni / Statements & Transactions**: Drag & drop multi-file (PDF, CSV, Excel), registro con filtri per banca, categoria e ricerca testo, tabella dei giroconti neutralizzati.
4. **🎲 Previsioni Future (Monte Carlo) / Future Forecasting**: Orizzonte temporale flessibile (12, 24, 36, 60 mesi), fan-chart percentili (5°-95°), rischio di scoperto di liquidità, traiettoria cassa vs investimenti e potere d'acquisto reale.
5. **🧠 Assistente AI Locale / Local AI Assistant**: Consulente finanziario AI in locale (Ollama / offline), catalogo modelli con download 1-click in streaming, chat interattiva con memoria e audit rapido.
6. **⚙️ Impostazioni & Privacy / Settings & Privacy**: Selettore lingua live (Italiano / English), ispettore live anonimizzazione PII, placeholder per Google Sheet opzionale.

---

## 🧪 Validazione & Stress Test Suite (`tests/test_stress.py`)

La suite di test completa comprende **37 test totali (21 test unitari/integrazione + 16 stress test ad alto carico)**, tutti superati al 100%:

| Ambito di Stress Test | Condizioni di Carico & Scenari Limite | Tempo & Prestazioni | Esito |
| :--- | :--- | :--- | :--- |
| **Monte Carlo 10.000 Iterazioni** | 10k scenari su 38 mesi, verifica monotonicità dei quantili (p5, p25, mediana, p75, p95) e assenza di NaN/Inf | **~1.8 secondi** | ✅ Pass |
| **Monte Carlo 20.000 Iterazioni (Orizzonte Esteso)** | 20k scenari su 61 mesi (5 anni), allocazione dinamica, stabilità della memoria | **~4.5 secondi** | ✅ Pass |
| **Casi Limite: Cassa 0 e Negativa** | Cassa iniziale €0.00 e cassa iniziale fortemente negativa (-€5.000 scoperto bancario), calcolo rischio insolvenza | **Istantaneo** | ✅ Pass |
| **Iperinflazione & Crash di Mercato** | Inflazione al 25% annuo combinata con crollo azionario del -40%, test convergenza | **~0.4 secondi** | ✅ Pass |
| **Volatilità Estrema & Grandi Shock** | Std spese di €4.000 (volatilità > 2.5x media) e shock improvvisi da €37.500 | **~0.4 secondi** | ✅ Pass |
| **Universal Bank Parser (10k Movimenti)** | Parsing ad alta velocità di 10.000 transazioni CSV continue multi-anno | **~1.2 secondi** | ✅ Pass |
| **Input Numerici Caotici & Valute** | Formati europei con virgola, anglosassoni con punto, valute multiple (`EUR`, `CHF`, `USD`), segni contabili (`100-`, `(100)`), valori nulli | **Istantaneo** | ✅ Pass |
| **Date Sporche & File Corrotti** | Date europee, ISO, leap year, valori invalidi, CSV con colonne mancanti/extra (`on_bad_lines='skip'`), file vuoti a 0 byte | **Istantaneo** | ✅ Pass |
| **500 Giroconti Circolari Multi-Banca** | 5 banche in circuito chiuso (Erste, Trade Republic, Revolut, UniCredit, Fineco), latenza bancaria 1-3 giorni, neutralizzazione perfetta del doppio conteggio | **~0.4 secondi** | ✅ Pass |
| **Throughput PII Scrubber (5.000 Voci)** | Scrubbing di 5.000 causali complesse con IBAN IT/AT/DE, CF italiani, carte, email e audit di zero-leakage | **~1.1 secondi** | ✅ Pass |
| **Categorizzazione Euristica di Massa** | Oltre 1.100 descrizioni bancarie eterogenee categorizzate offline a zero latenza | **~0.15 secondi** | ✅ Pass |
| **Pipeline End-to-End Reale** | Pipeline completa da file grezzi a Monte Carlo 5.000 scenari e diagnosi patrimoniale AI | **~5.5 secondi** | ✅ Pass |
