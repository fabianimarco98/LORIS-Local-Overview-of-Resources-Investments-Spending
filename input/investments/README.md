# Cartella Investimenti & Portafoglio ETF / Titoli

Inserisci qui i tuoi file di investimento (esportazioni CSV, Excel o liste personalizzate).

### Formati Supportati:
- File CSV, TSV o Excel con colonne come:
  - `Ticker` / `ISIN` / `Simbolo`
  - `Name` / `Nome Strumento`
  - `Shares` / `Quote` / `Quantità`
  - `Buy_Price` / `Prezzo Acquisto` / `Prezzo Medio di Carico`
  - `Current_Price` / `Prezzo Attuale` / `Quotazione`
  - `Market_Value` / `Valore Totale` / `Controvalore` (opzionale, calcolato in automatico)
  - `Asset_Class` (opzionale: Azionario, Obbligazionario, Mercato Monetario)

Consulta il file di esempio in `input/templates/template_investimenti_etf.csv`.
LORIS lo caricherà automaticamente all'avvio o tramite caricamento file nell'app!
