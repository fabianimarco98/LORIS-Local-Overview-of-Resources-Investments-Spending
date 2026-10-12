# 🐾 Guida Completa: Esportazione Dati Bancari & Installazione LORIS

Questa guida fornisce istruzioni passo-passo per:
1. **Esportare gli estratti conto** dalle principali banche e app (Trade Republic, Revolut, Wallet App, banche tradizionali).
2. **Installare ed eseguire LORIS** su macOS, Windows e Linux.
3. **Condividere ed esportare il progetto** in totale sicurezza senza dati personali.

---

## 1. Come Esportare i Dati Bancari

LORIS supporta nativamente file **PDF, CSV ed Excel**. Per ottenere i migliori risultati, segui queste indicazioni per ogni banca o applicazione:

### 📱 Revolut
1. Apri l'app **Revolut** sul telefono (o accedi su [revolut.com](https://revolut.com)).
2. Dalla Home, tocca l'icona con i tre puntini `...` accanto al saldo (oppure tocca il conto e seleziona **Estratti conto** / *Statement*).
3. Seleziona **Estratto conto** (*Account Statement*).
4. Formato: seleziona **CSV** (consigliato per la massima precisione dei metadati) oppure **PDF**.
5. Seleziona l'intervallo temporale desiderato (es. *Tutto il periodo*, *Ultimi 12 mesi*, o un intervallo personalizzato).
6. Tocca **Genera** / **Esporta** e salva o condividi il file sul computer.

### 📱 Trade Republic
- **Metodo 1 — Rendiconto/Estratto conto PDF (Ufficiale)**:
  1. Apri l'app **Trade Republic** sullo smartphone.
  2. Tocca l'icona del profilo (in basso a destra o iniziale in alto).
  3. Vai alla sezione **Documenti** (o *Attività* / *Inbox*).
  4. Cerca e apri i documenti trimestrali o mensili denominati **Estratto conto** (*Account Statement* o *Kontoauszug*).
  5. Scarica o condividi il file PDF sul tuo computer.
- **Metodo 2 — Transazioni CSV**:
  1. Accedi da computer a [traderepublic.com](https://traderepublic.com).
  2. Nella sezione Saldo / Attività, clicca su **Esporta movimenti** / **Scarica CSV**.
  3. Salva il file CSV sul computer.

### 📱 Wallet App (BudgetBakers — Spese in Contanti CASH)
1. Apri l'app **Wallet** su smartphone o su [web.budgetbakers.com](https://web.budgetbakers.com).
2. Vai su **Impostazioni** (icona ingranaggio) -> **Esporta dati** (*Export data*).
3. Scegli il formato **CSV** e seleziona l'intervallo di date.
4. Scarica il file CSV. LORIS riconosce automaticamente la colonna dei conti e traccia con precisione i movimenti in contanti (*CASH*).

### 🏛️ Banche Tradizionali (Intesa Sanpaolo, UniCredit, Fineco, N26, Widiba, Sparkasse, Poste Italiane, ecc.)
1. Accedi all'area riservata Home Banking dal sito web della banca tramite computer.
2. Vai nella sezione **Conti e Carte** -> **Movimenti** o **Estratti Conto e Documenti**.
3. Seleziona il periodo e clicca sul pulsante **Esporta** / **Scarica Lista Movimenti**.
4. Scegli il formato **CSV**, **Excel (.xlsx o .xls)** oppure **PDF**.
5. Salva il file sul computer.

---

## 2. Come Installare ed Eseguire LORIS

### Requisiti di Sistema
- **macOS** (10.15 Catalina o superiore), **Windows** 10/11, o **Linux**.
- **Python 3.10 o superiore** (se avviato da script).

---

### 🍏 Installazione su macOS

#### Metodo 1: Avvio Rapido con 1 Clic (Consigliato)
1. Estrai la cartella `LORIS` dall'archivio ZIP o dopo aver clonato da GitHub.
2. Fai doppio clic sul file:
   ```bash
   start.command
   ```
3. *Nota per il primo avvio*: se macOS Gatekeeper mostra un avviso (*"Impossibile aprire perché proviene da uno sviluppatore non identificato"*):
   - Fai **Tasto Destro** (o Control + Clic) su `start.command`.
   - Seleziona **Apri** dal menu contestuale.
   - Clicca su **Apri** nella finestra di dialogo.
4. Lo script imposterà l'ambiente virtuale (`venv`), installerà le dipendenze mancanti e aprirà automaticamente la dashboard nel browser predefinito a `http://localhost:8502`.

#### Metodo 2: Da Terminale
```bash
cd LORIS-Local-Overview-of-Resources-Investments-Spending
./run_app.sh
```

#### Metodo 3: Come App Nativa macOS con Icona nel Dock
Per generare un'applicazione desktop standalone per macOS:
```bash
./run_app.sh macos-app
```
Questo comando compila l'eseguibile Swift nativo e genera `LORIS.app` pronta per essere spostata nella cartella `/Applications`.

---

### 🪟 Installazione su Windows

1. Scarica e installa Python 3.10 o versione successiva da [python.org](https://www.python.org/downloads/).
   > [!IMPORTANT]
   > Durante l'installazione di Python, assicurati di selezionare la spunta **"Add Python to PATH"** (Aggiungi Python al PATH di sistema).
2. Estrai la cartella `LORIS`.
3. Fai doppio clic sul file:
   ```cmd
   start.bat
   ```
4. Verrà configurato automaticamente l'ambiente e si aprirà il browser su `http://localhost:8502`.

---

### 🐧 Installazione su Linux

```bash
cd LORIS-Local-Overview-of-Resources-Investments-Spending
chmod +x run_app.sh start.command
./run_app.sh
```

---

## 3. Come Caricare i File e Usare LORIS

Una volta aperta la dashboard:

### A. Caricamento File (Drag & Drop)
- Nella barra laterale a sinistra, trascina i tuoi estratti conto (PDF, CSV o Excel) nel riquadro di caricamento.
- Oppure copia i file nella cartella locale:
  - `input/bank_statements/` per conti correnti e carte.
  - `input/investments/` per posizioni ETF o azioni.
  - `input/wallet/` per export di Wallet App.
- Clicca su **Ricarica Dati**.

### B. Gestione Modifiche & Funzione Undo
- **Annulla Ultimo Caricamento**: se carichi per errore un file non voluto, premi **↩️ Annulla Ultimo Caricamento** nella barra laterale.
- **Elimina File Singoli**: clicca sull'icona **🗑️** accanto a ciascun file memorizzato su disco per rimuoverlo.
- **Modifica Saldi Manuali**: nella scheda *Patrimonio & Saldi*, usa l'editor manuale per forzare o correggere il saldo di qualunque conto.
- **Modifica Transazioni**: nella scheda *Estratti Conto & Transazioni*, puoi ri-categorizzare spese, escludere movimenti o aggiungere entrate/uscite manuali col tasto **➕**.

---

## 4. Come Condividere o Esportare LORIS in Sicurezza

Per condividere LORIS con un amico senza rivelare i tuoi dati personali:

### Opzione 1 — Tramite Repository GitHub
Condividi direttamente il link ufficiale:
👉 **[https://github.com/fabianimarco98/LORIS-Local-Overview-of-Resources-Investments-Spending](https://github.com/fabianimarco98/LORIS-Local-Overview-of-Resources-Investments-Spending)**

Il destinatario può:
- Cliccare su **Code** -> **Download ZIP**.
- Oppure eseguire `git clone https://github.com/fabianimarco98/LORIS-Local-Overview-of-Resources-Investments-Spending.git`.
- Per aggiornare in futuro: `git pull`.

### Opzione 2 — Tramite Pacchetto ZIP Locale
Se preferisci inviare un file compresso via Telegram, AirDrop o email:
```bash
./run_app.sh package
```
Questo comando crea l'archivio `LORIS_Condividi.zip` che:
- Include tutto il codice sorgente, le istruzioni, le icone e i test.
- **Esclude rigorosamente al 100%** tutti i tuoi estratti conto personali (`.pdf`, `.csv`, `.xlsx`), i log e le configurazioni private.

---

## 5. Supporto e Donazioni

LORIS è un progetto completamente indipendente e open-source. Se trovi utile l'applicazione:
- ☕ **Offri un caffè allo sviluppatore**: [https://www.buymeacoffee.com/fabianimarco98](https://www.buymeacoffee.com/fabianimarco98)
- 💖 **Sponsorizza su GitHub**: [https://github.com/sponsors/fabianimarco98](https://github.com/sponsors/fabianimarco98)
- ⭐ **Lascia una stella sul repository GitHub!**
