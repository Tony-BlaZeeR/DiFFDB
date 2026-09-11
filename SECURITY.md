# Sicurezza

## Segnalare una vulnerabilita'

**Non aprire una issue pubblica.** Usa
[Report a vulnerability](https://github.com/antoniobis98/DiFFDB/security/advisories/new)
su GitHub, che apre una segnalazione privata.

Nella segnalazione servono: la versione di DiFFDB (`diffdb --help` la mostra, e
sta anche in testa a ogni script generato), il sistema operativo, il dialetto del
database e come riprodurre il problema. **Non allegare connection string vere**:
mascherale.

Rispondiamo entro 5 giorni lavorativi e concordiamo con te i tempi di
pubblicazione.

## Cosa fa DiFFDB con i tuoi database

E' la domanda che conta per capire quale sia il rischio:

- **Legge soltanto.** DiFFDB non esegue mai niente sui database che confronta:
  interroga i cataloghi di sistema e basta. Lo script SQL di allineamento viene
  scritto su file e lo esegui tu, quando e se vuoi.
- **Le operazioni distruttive non vengono generate.** Cambio di chiave primaria,
  `NOT NULL` su tabelle popolate, vincoli su dialetti che non sanno aggiungerli
  in ALTER: vengono segnalate come commento, non come SQL.
- **Non manda niente da nessuna parte.** Nessuna telemetria, nessuna chiamata di
  rete che non sia verso i database che gli indichi tu.

## Le password

Nel `connections.json` non va mai una password, ma un riferimento: `${keyring}`
(portachiavi del sistema operativo) o `${VARIABILE}` (variabile d'ambiente).
Vedi il README, sezione *Le password non stanno nel file*.

Per **vietare** le password in chiaro a livello di configurazione:

```sh
DIFFDB_REQUIRE_SECRET_REFS=1
```

Le connection string vengono mascherate ovunque escano dal processo: interfaccia,
messaggi d'errore, file di log, snapshot salvati. Se trovi un punto dove una
password esce in chiaro, **e' una vulnerabilita'**: segnalala.

## Privilegi minimi

DiFFDB ha bisogno di leggere i cataloghi di sistema, niente di piu'. Non dargli
un utente amministrativo:

| Dialetto | Cosa basta |
| --- | --- |
| PostgreSQL | `CONNECT` sul database, `USAGE` sullo schema, `SELECT` su `information_schema` e `pg_catalog` (di norma gia' concesso a `PUBLIC`) |
| MySQL/MariaDB | `SELECT` sullo schema da confrontare; i metadati arrivano da `information_schema` |
| Oracle | `CREATE SESSION` e `SELECT` su `ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`, `ALL_INDEXES`, `ALL_VIEWS`, `ALL_SEQUENCES`, `ALL_SYNONYMS` |
| SQL Server | `VIEW DEFINITION` sul database e `SELECT` sulle viste di sistema |

Per **eseguire** lo script generato servono ovviamente privilegi di DDL: e' un
utente diverso, e conviene che lo resti.

## Dipendenze

Le versioni sono fissate in `requirements.txt`. La CI esegue `pip-audit` a ogni
push: una dipendenza con una vulnerabilita' nota fa fallire la build.

## Versioni supportate

Riceve correzioni di sicurezza solo l'ultima versione pubblicata.
