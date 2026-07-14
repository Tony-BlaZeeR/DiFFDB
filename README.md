# DiFFDB

Confronta la **struttura** di due database che dovrebbero avere lo stesso schema
(sviluppo, collaudo, produzione), mostra le differenze e genera lo script SQL per
allinearli. Con interfaccia grafica e con una CLI da mettere in pipeline.

## Cosa rileva

- Tabelle presenti in un ambiente e non nell'altro
- Colonne mancanti, **con tipo, nullability o valore di default diverso**
- **Indici, foreign key, vincoli di unicita' e chiavi primarie**
- Viste (presenza **e corpo della definizione**), sequenze (con i loro valori
  reali di START/INCREMENT) e sinonimi (Oracle e SQL Server)

## Cosa produce

- `differenze_ambienti.xlsx` — un foglio per tabelle, vincoli, viste, sequenze,
  sinonimi. Ogni riga dice *cosa* differisce, *dove* manca e con che *dettaglio*.
- `allinea_<ambiente>.sql` — uno script **per ogni direzione**, con SQL eseguibile
  (CREATE TABLE con colonne, tipi e FK; ALTER TABLE; CREATE INDEX; ADD CONSTRAINT;
  CREATE VIEW; CREATE SEQUENCE), compilato sul dialetto dell'ambiente da allineare.

DiFFDB propone, non applica: non esegue mai niente sui database confrontati. Le
operazioni distruttive o rischiose (cambio di chiave primaria, NOT NULL su tabelle
popolate, vincoli su dialetti che non li sanno aggiungere in ALTER) non vengono
generate come SQL, ma segnalate come commento nello script.

## Database supportati

PostgreSQL, MySQL/MariaDB, Oracle, SQL Server, SQLite — tramite SQLAlchemy.

## Installazione

Serve Python 3.10+.

```sh
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

I driver sono scelti per non richiedere client di sistema: `oracledb` gira in
*thin mode* (niente Oracle Instant Client da installare) e `psycopg2-binary` e
`PyMySQL` non hanno dipendenze native. Per SQL Server, `pymssql` si porta dietro
il client; `pyodbc` (commentato in `requirements.txt`) richiede invece l'ODBC
Driver installato sulla macchina.

## Connessioni

Si gestiscono dalla scheda **Configurazione** e finiscono in `connections.json`,
accanto all'eseguibile (o in `%APPDATA%\DiFFDB` se la cartella non e' scrivibile).
Il file **non e' versionato**: parti da `connections.json.example`.

```json
[
  {
    "name": "collaudo",
    "conn_string": "oracle+oracledb://app:${COL_DB_PWD}@host:1521/?service_name=ORCL",
    "schema": "APP"
  }
]
```

Lo **schema** e' opzionale: su Oracle di solito coincide con l'utente, e serve
quando l'utente di connessione vede piu' schemi. Le password non vanno scritte in
chiaro: `${VAR}` viene espansa dall'ambiente al momento della connessione.

Con `DIFFDB_HOME` puoi spostare la configurazione dove vuoi.

## Uso (GUI)

1. **Configurazione** — aggiungi le connessioni (nome, URL, schema).
2. **Scelta** — seleziona i due ambienti e premi *Confronta*.
3. **Risultati** — le differenze compaiono in un albero raggruppato per categoria,
   con un colore per direzione (manca di qua / manca di la' / diverso). Filtra per
   nome, spunta le voci che ti interessano ed esporta: *Excel* per tutto il report,
   *SQL* solo per le differenze selezionate.

Il confronto gira su un thread separato: la finestra resta reattiva anche su
schemi grandi. Non viene scritto nulla su disco finche' non premi *Esporta*.

## Uso (CLI, per la pipeline)

```sh
python -m src.cli --list                                  # connessioni configurate
python -m src.cli SVI COL --out ./report                  # confronta e scrive gli output
python -m src.cli SVI COL --fail-on-diff                  # esce con 1 se divergono
python -m src.cli sqlite:///a.db sqlite:///b.db           # anche due URL al volo
```

`--fail-on-diff` e' quello che serve in CI: fa fallire la build se collaudo e
produzione hanno smesso di somigliarsi.

## Build (eseguibile portable)

```sh
pip install -r requirements-dev.txt
pyinstaller DiFFDB.spec
```

Un eseguibile unico in `dist/`, senza installazione e senza Python: lo copi dove
vuoi insieme al suo `connections.json`. PyInstaller non fa cross-compile: l'exe
Windows si costruisce su Windows, il binario Linux su Linux — la pipeline in
`.github/workflows/ci.yml` li produce per tutti e tre i sistemi a ogni tag.

Per l'icona su Windows serve un `.ico` (opzionale):

```sh
python -c "from PIL import Image; Image.open('images/logo.png').save('images/logo.ico')"
```

## Test

```sh
python -m pytest tests/
```

I test creano due database SQLite reali, li confrontano, **eseguono** lo script
generato e verificano che le differenze siano sparite. La finestra viene
istanziata headless (`QT_QPA_PLATFORM=offscreen`), quindi anche la GUI e' coperta.

Limite noto: su SQLite, SQLAlchemy non riflette l'`UNIQUE` dichiarato inline sulla
colonna (solo quello a livello di tabella). Sugli altri database non succede.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| `main.py` | Avvio della GUI |
| `src/cli.py` | Interfaccia a riga di comando |
| `src/main_window.py` | Finestra principale, tab, gestione connessioni |
| `src/diff_DB.py` | Confronto e generazione degli script SQL |
| `src/schema_snapshot.py` | Lettura della struttura di un database |
| `src/results_tab.py` | Tab dei risultati: albero, filtro, export selettivo |
| `src/report.py` | Scrittura di Excel e script (usata da GUI e CLI) |
| `src/worker.py` | Confronto fuori dal thread della GUI |
| `src/qt.py` | Unico punto di accesso a Qt e caricamento dei file `.ui` |
| `src/connections.py`, `src/paths.py` | Connessioni e percorsi (anche da eseguibile) |
| `config/dialectConfig.py` | Template SQL e capacita' di ogni dialetto |
| `utils/tableUtilities.py` | Confronto di due file DDL testuali (utility a se') |
| `ui/`, `styles/`, `images/` | Layout Qt Designer, tema scuro, icone |

## Licenza

MIT (vedi `LICENSE`). La GUI usa **PySide6** (LGPL), non PyQt5: quest'ultimo e'
GPL/commerciale e distribuire l'eseguibile avrebbe richiesto di rilasciare tutto
sotto GPL o di comprare una licenza.
