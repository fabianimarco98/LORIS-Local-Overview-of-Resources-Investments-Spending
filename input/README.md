# 📂 Cartella Dati & Input Utente — LORIS

Questa cartella è riservata ai tuoi file personali e ai dati di input.

---

### 📥 1. Estratti Conto Bancari (`input/bank_statements/`)
Per analizzare il tuo patrimonio reale e avviare le simulazioni:
* Trascina o copia qui dentro i tuoi estratti conto bancari in formato **CSV, Excel (.xlsx/.xls) o PDF**.
* Oppure trascinali direttamente nell'interfaccia grafica dell'applicazione (nella barra laterale sinistra di **LORIS**).

**Banche supportate nativamente:**
* 🇦🇹 **Erste Bank / Sparkasse (George Austria)** (CSV/PDF)
* 🇩🇪 **Trade Republic** (Estratto conto mensile / Conto Titoli / Cash CSV)
* 🇪🇺 **Revolut** (Estratto conto in Euro / Multi-valuta CSV/Excel)
* 🇮🇹 **Banche Italiane** (UniCredit, Intesa Sanpaolo, Fineco, Widiba, Poste Italiane)
* 🌐 **Qualsiasi altro istituto bancario** (gestito tramite il parser euristico universale).

---

### 📑 2. Modelli Opzionali (`input/templates/`)
Contiene modelli di configurazione avanzata (parametri macroeconomici, spese fisse manuali o shock programmati). 
**Non sono obbligatori**: LORIS opera al 100% in modo autonomo derivando cassa reale, spese, stipendio e volatilità esclusivamente dai movimenti bancari.

---

### 🛡️ Privacy Totale (Zero-Knowledge)
Tutti i file depositati in questa cartella vengono elaborati **esclusivamente in locale** sulla tua macchina. Nessun dato lascia mai il tuo computer.
