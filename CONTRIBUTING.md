# Contribuire a DiFFDB

## Partire

```sh
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ --ignore=tests/integration
```

## Prima di aprire una pull request

Sono gli stessi controlli che gira la CI: falli girare prima e non ci saranno
sorprese.

```sh
ruff check .                                      # stile e trappole note
python -m pytest tests/ --ignore=tests/integration --cov=diffdb
python tools/traduzioni.py --check                # nessuna stringa senza traduzione
```

### I test di integrazione

Gli unitari girano su SQLite: veloci, ma non dicono niente sugli altri quattro
dialetti. Se tocchi il generatore SQL o la lettura dello schema, falli girare
anche sui motori veri — almeno su uno.

```sh
DIFFDB_TEST_POSTGRESQL_URL=postgresql+psycopg2://postgres:pw@localhost:5432/postgres \
  python -m pytest tests/integration -v
```

I dettagli (le altre variabili, cosa creano e distruggono i test) stanno nel
README. In locale i dialetti senza variabile vengono saltati; in CI
`DIFFDB_TEST_STRICT=1` li fa fallire, cosi' un job verde significa davvero che
sono stati eseguiti.

## Come e' scritto questo codice

Non sono regole di stile: sono decisioni che hanno una ragione, e cambiarle
richiede una ragione migliore.

**I commenti dicono *perche'*, non *cosa*.** `# incrementa il contatore` non
serve a nessuno. `# senza questo il NOT NULL si perde: MySQL riscrive la colonna
da capo` fa risparmiare mezz'ora a chi legge.

**Le differenze fra dialetti sono dichiarate, non indovinate.** Stanno in
`diffdb/config/dialectConfig.py`, una voce per capacita'. Se scopri che un
dialetto si comporta diversamente, aggiungi una capacita' li' invece di un `if`
sparso nel generatore.

**DiFFDB propone, non applica.** Non esegue mai niente sui database confrontati.
Un'operazione distruttiva o rischiosa si emette come commento con la spiegazione,
mai come SQL pronto da lanciare.

**I segreti non escono mai.** Qualunque cosa esca dal processo — interfaccia,
log, messaggi d'errore, file salvati — passa da `mask_password` o `sanitize`.
Se aggiungi un punto di uscita, aggiungi anche la sanificazione.

**Ogni stringa visibile all'utente passa da `self.tr()`.** La lingua sorgente e'
l'italiano. Dopo averne aggiunta una:

```sh
python tools/traduzioni.py            # aggiorna i .ts e ricompila i .qm
```

poi traduci le voci nuove in `diffdb/translations/diffdb_en.ts`. La CI fallisce
se ne resta una senza traduzione.

## I test

Un test dovrebbe dire cosa si rompe se sparisce. `test_le_tabelle_si_creano_in_ordine_di_dipendenza`
si legge; `test_sort_1` no.

Quando correggi un bug, il test che aggiungi deve **fallire prima** della
correzione. Se passa anche senza, non sta verificando il bug.

Attenzione ai test che non provano niente: un'asserzione che sarebbe vera anche
col codice rotto e' peggio di nessun test, perche' da' fiducia falsa.

## Il messaggio di commit

In italiano, all'imperativo, con il *perche'* nel corpo se non e' ovvio:

```
fix: il cambio di tipo non perde piu' il NOT NULL

MySQL e SQL Server riscrivono la colonna da capo, quindi quello che non si
ripete va perso. Oracle e' l'opposto: ripetere un NOT NULL gia' presente
solleva ORA-01442.
```
