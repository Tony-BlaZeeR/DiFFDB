# DiFFDB

Confronta la **struttura** di due database che dovrebbero avere lo stesso schema
(sviluppo, collaudo, produzione), evidenzia le differenze e genera lo script SQL
per allinearli.

## Cosa rileva

- Tabelle presenti in un ambiente e non nell'altro
- Colonne mancanti, **con tipo diverso** o con nullability diversa
- Viste, sequenze e sinonimi (Oracle e SQL Server) mancanti

## Cosa produce

- `differenze_ambienti.xlsx` — un foglio per tabelle, viste, sequenze, sinonimi.
  Ogni riga dice *cosa* differisce, in *quale* ambiente manca e con che *dettaglio*.
- `allinea_<ambiente>.sql` — uno script **per ogni direzione**, con SQL eseguibile
  (CREATE TABLE con colonne e tipi reali, ALTER TABLE, CREATE VIEW), compilato sul
  dialetto dell'ambiente da allineare.

Gli script vanno riletti prima di essere eseguiti in produzione: DiFFDB propone,
non applica. Nessuno statement viene mai eseguito sui database confrontati.

## Database supportati

PostgreSQL, MySQL/MariaDB, Oracle, SQL Server, SQLite — tramite SQLAlchemy.

## Installazione

Serve Python 3.8+.

```sh
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

In `requirements.txt` i driver dei database sono opzionali: installa solo quelli
che ti servono (Oracle richiede `cx_Oracle` e il client Oracle sulla macchina).

## Connessioni

Si gestiscono dalla scheda **Configurazione**. Vengono salvate in `connections.txt`
accanto all'eseguibile (o in `%APPDATA%\DiFFDB` se la cartella non e' scrivibile).
Il file **non e' versionato**: parti da `connections.txt.example`.

Formato, una connessione per riga:

```
sviluppo,postgresql+psycopg2://app:password@localhost:5432/app_svi
```

Per non tenere le password in chiaro, usa una variabile d'ambiente: DiFFDB la
espande al momento della connessione.

```
produzione,postgresql+psycopg2://app:${PROD_DB_PWD}@prod.local:5432/app
```

Con la variabile `DIFFDB_HOME` puoi spostare la configurazione altrove.

## Uso

1. **Configurazione** — aggiungi le connessioni.
2. **Scelta** — seleziona i due ambienti e premi *Confronta*.
3. Scegli la cartella di output: ci trovi il report Excel e gli script SQL.

Il confronto gira su un thread separato: la finestra resta reattiva anche su
schemi grandi.

## Build (eseguibile portable)

```sh
pip install -r requirements-dev.txt
pyinstaller DiFFDB.spec
```

Il risultato e' un eseguibile unico in `dist/`, che non richiede installazione
ne' Python: lo copi dove vuoi insieme al suo `connections.txt`.

Per l'icona su Windows serve un `.ico` (opzionale):

```sh
python -c "from PIL import Image; Image.open('images/logo.png').save('images/logo.ico')"
```

## Test

```sh
python -m pytest tests/
```

I test creano due database SQLite reali, li confrontano, **eseguono** lo script
generato e verificano che le differenze siano sparite.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| `main.py` | Avvio dell'applicazione |
| `src/main_window.py` | Finestra principale, tab, gestione connessioni |
| `src/diff_DB.py` | Confronto e generazione di script SQL ed Excel |
| `src/schema_snapshot.py` | Lettura della struttura di un database |
| `src/worker.py` | Confronto fuori dal thread della GUI |
| `src/connections.py`, `src/paths.py` | Connessioni e percorsi (anche da eseguibile) |
| `config/dialectConfig.py` | Template SQL per dialetto |
| `utils/tableUtilities.py` | Confronto di due file DDL testuali (utility a se') |
| `ui/`, `styles/`, `images/` | Layout Qt Designer, tema scuro, icone |

## Licenza

MIT (vedi `LICENSE`). Nota: PyQt5 e' distribuito con licenza GPL/commerciale; per
distribuire l'applicazione con licenza permissiva conviene passare a PySide6
(LGPL), che ha praticamente la stessa API.
