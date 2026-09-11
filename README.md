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
- `snapshot.json` — la struttura di un ambiente congelata su file (vedi sotto).

DiFFDB propone, non applica: non esegue mai niente sui database confrontati. Le
operazioni distruttive o rischiose (cambio di chiave primaria, NOT NULL su tabelle
popolate, vincoli su dialetti che non li sanno aggiungere in ALTER) non vengono
generate come SQL, ma segnalate come commento nello script.

## Lo script di allineamento

Oltre a essere SQL eseguibile, lo script si preoccupa di **poter essere eseguito
dall'inizio alla fine**:

- **Le tabelle nuove escono in ordine di dipendenza.** Le foreign key stanno
  dentro il `CREATE TABLE`, quindi in ordine alfabetico uno script che crea
  `ordini` prima di `clienti` fallisce a meta'. Se fra le tabelle c'e' un ciclo
  nessun ordine funziona, e lo script lo dichiara invece di fingere.
- **Si apre in transazione**, dove il database sa annullare un DDL:

  | Dialetto | Transazione |
  | --- | --- |
  | PostgreSQL, SQL Server, SQLite | `BEGIN` / `COMMIT`: tutto o niente |
  | MySQL, Oracle | Nessuna: ogni DDL fa commit da solo, e lo script lo dice in testa |

  Avvolgere Oracle e MySQL in un `BEGIN/COMMIT` darebbe l'illusione di poter
  annullare, che e' peggio che non averla.

## Database supportati

PostgreSQL, MySQL/MariaDB, Oracle, SQL Server, SQLite — tramite SQLAlchemy.

## Installazione

Serve Python 3.10+.

```sh
pip install diffdb[gui,report,postgresql]   # interfaccia, Excel e il driver che serve
diffdb-gui                                  # interfaccia grafica
diffdb PROD PRE --fail-on-diff              # riga di comando
```

Le dipendenze sono divise in extra, cosi' una pipeline che vuole solo il
confronto non si porta dietro Qt e pandas:

| Extra | Cosa aggiunge |
| --- | --- |
| `gui` | L'interfaccia grafica (PySide6) |
| `report` | Il report Excel (pandas, openpyxl) |
| `postgresql`, `mysql`, `oracle`, `mssql` | Il driver corrispondente |
| `all` | Tutto quanto |

Senza `report` il confronto funziona lo stesso: gli script SQL vengono scritti e
l'Excel viene saltato con un avviso, invece di far fallire il comando.

### Dai sorgenti

```sh
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
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
quando l'utente di connessione vede piu' schemi.

Con `DIFFDB_HOME` puoi spostare la configurazione dove vuoi.

### Le password non stanno nel file

Nel `connections.json` va un **riferimento**, mai la password:

| Riferimento | Dove sta davvero il segreto |
| --- | --- |
| `${keyring}` | Portachiavi del sistema operativo: Credential Manager su Windows, Keychain su macOS, Secret Service su Linux |
| `${VARIABILE}` | Variabile d'ambiente: e' quello che si usa in CI, dove a custodire il segreto e' il secret store della pipeline |

```sh
python -m diffdb.cli --set-password PROD    # chiede la password e la mette nel portachiavi
```

Il comando salva la password nel portachiavi e **riscrive la connessione nel
file sostituendo la password con `${keyring}`**. Dalla GUI fa lo stesso il
pulsante *Password nel portachiavi* nel dialog della connessione.

Cosi' un `connections.json` copiato su un'altra macchina non contiene niente di
utile: il segreto e' legato all'account utente del sistema operativo.

Se una password resta scritta in chiaro, DiFFDB lo segnala a ogni connessione.
Per **vietarla** del tutto:

```sh
DIFFDB_REQUIRE_SECRET_REFS=1    # la connessione fallisce invece di procedere
```

Le connection string vengono mascherate ovunque escano dal processo: interfaccia,
messaggi d'errore, file di log e snapshot salvati.

## Snapshot: confrontare nel tempo, e senza il database

Uno snapshot e' la struttura di un ambiente salvata su file JSON. Serve a tre cose
che con il solo confronto dal vivo non si possono fare:

- **drift detection** — congeli PROD oggi, e fra un mese verifichi cos'e' cambiato;
- **baseline in git** — versioni lo schema atteso e fai fallire la CI quando un
  ambiente se ne allontana;
- **confronto offline** — il DBA esporta lo snapshot di produzione e il confronto
  si fa altrove, senza accesso di rete a quel database.

Lo snapshot riletto e' un ambiente a tutti gli effetti: si confronta e **genera lo
script di allineamento** come se fossi connesso, perche' conserva tipi, vincoli e
dialetto. Le password non ci finiscono mai dentro: l'URL viene salvato mascherato.

```sh
python -m diffdb.cli PROD --snapshot baseline/prod.json    # congela
python -m diffdb.cli baseline/prod.json PROD --fail-on-diff  # drift dalla baseline
python -m diffdb.cli baseline/prod.json baseline/pre.json    # confronto offline
```

Se i due ambienti hanno lo stesso nome (la baseline di PROD contro PROD di oggi)
vengono distinti automaticamente: `PROD (prod)` e `PROD (live)`.

Dalla GUI, nella scheda **Scelta**: *Salva snapshot del primo ambiente* e
*Confronta con uno snapshot su file*.

## Regole: cosa guardare, e cosa e' gia' stato deciso

Su uno schema vero — due, tremila tabelle — un confronto senza regole produce
centinaia di differenze di cui la gran parte e' rumore: tabelle temporanee,
copie di backup, residui di migrazioni. Un elenco cosi' non lo legge nessuno.

Le regole stanno in un `diffdb.rules.json` accanto al codice, **versionato**:
le esclusioni sono decisioni di squadra, non preferenze di chi lancia il comando.

```json
{
  "format": 1,
  "escludi": {
    "tabelle": ["TMP_*", "BCK_*", "*_20??????"],
    "viste": ["V_DEBUG_*"],
    "categorie": ["sequences"]
  },
  "includi_solo": { "tabelle": [] },
  "accettate": []
}
```

I modelli non distinguono maiuscole e minuscole: Oracle restituisce i nomi tutti
maiuscoli e PostgreSQL tutti minuscoli, e un modello scritto a mano non deve
dipendere da quale dei due si sta guardando.

I filtri si applicano **prima** di leggere lo schema, quindi tolgono anche il
tempo di riflettere quello che non guarderai.

### Le differenze accettate

Ci sono differenze note e volute: produzione ha un indice in piu' per le
prestazioni, collaudo ha una colonna di debug. Non vanno escluse per modello —
nasconderebbero anche quelle future dello stesso oggetto — ma **accettate una
volta**, per ricomparire solo se cambiano:

```sh
diffdb SVI COL --accept        # da qui in poi il confronto e' verde
diffdb SVI COL --fail-on-diff  # esce 0 finche' non cambia qualcosa
```

E' lo stesso meccanismo della baseline di un linter, ed e' quello che rende
`--fail-on-diff` utilizzabile in pipeline su uno schema che parte gia' con
differenze note. Senza, la build e' rossa dal primo giorno e dopo una settimana
qualcuno toglie il controllo.

`--no-rules` ignora il file e mostra tutto.

**I filtri fanno parte dell'impronta.** Due snapshot presi con filtri diversi
descrivono insiemi diversi: se i filtri non entrassero nell'impronta, `--verify`
direbbe "tutto a posto" su uno script generato con altre regole.

### Su schemi grandi

I due ambienti vengono letti **in parallelo** — sono indipendenti, e la lettura
e' quasi tutto il tempo del confronto. Ogni connessione ha un timeout (15
secondi), perche' senza si eredita quello di sistema su TCP, che puo' essere di
minuti. E nella scheda *Scelta* compare un pulsante **Annulla** mentre la
lettura e' in corso: chiude le connessioni e il confronto si ferma.

## Tracciabilita': da dove viene questo script

Lo script `.sql` che DiFFDB produce e' un *change* che finira' in produzione.
Ognuno porta in testa chi l'ha generato, quando, confrontando cosa con cosa, con
quale versione di DiFFDB, e l'**impronta** dei due ambienti:

```sql
-- DiFFDB 1.2.0 - script di allineamento
-- Ambiente da allineare : PROD (oracle, schema APP)
-- Allineato a           : PRE
-- Generato il           : 2026-08-06T10:55:20+00:00
-- Generato da           : antonio@PC-ANTONIO
-- Impronta di PRE  : sha256:4e093e11...
-- Impronta di PROD : sha256:bc78f2ca...
```

La versione serve a una cosa poco ovvia e molto utile: quando esce una
correzione al generatore, dice **quali script prodotti in passato ne sono
affetti**, invece di doverli sospettare tutti.

L'impronta rende lo script verificabile *prima* di eseguirlo:

```sh
python -m diffdb.cli --verify allinea_prod.sql PROD
```

Esce con 0 se l'ambiente e' ancora quello di quando lo script e' stato generato,
con 1 se e' cambiato nel frattempo — nel qual caso lo script non e' piu' valido e
va rigenerato. L'impronta copre la struttura (tabelle, viste, sequenze, sinonimi,
dialetto e schema): rinominare un ambiente o rifare lo snapshot un minuto dopo
non la cambia.

Lo stesso vale per l'Excel, che ha un foglio **Informazioni**, e per gli snapshot,
che portano la propria impronta dentro il file. Se esporti solo una parte delle
differenze, l'intestazione lo dichiara.

Il log applicativo sta in `diffdb.log` accanto alla configurazione, con rotazione.

## Accessibilita'

**Il colore non e' l'unico canale.** Ogni differenza porta anche un simbolo, e
una legenda in cima ai risultati dice cosa vuol dire — prima quel significato
esisteva solo in un commento nel codice:

```text
←  manca in SVILUPPO      →  manca in COLLAUDO      ≠  presente in entrambi ma diverso
```

**Il contrasto e' misurato, non stimato.** I colori del tema rispettano WCAG AA
(4.5:1 per il testo, 3:1 per gli elementi di interfaccia) su *tutti* i fondi su
cui possono capitare, righe alternate comprese. `tests/test_accessibilita.py`
calcola i rapporti e fallisce se qualcuno scende sotto la soglia — inclusi i
colori aggiunti in futuro, che vengono pescati direttamente dallo stylesheet.

**Tastiera.** Le scorciatoie hanno la portata della loro scheda: `Ctrl+S` nella
scheda delle connessioni non esporta niente.

| Scorciatoia | Azione |
| --- | --- |
| `Ctrl+1` … `Ctrl+4` | Vai alla scheda |
| `Ctrl+Invio` | Avvia il confronto |
| `Ctrl+I` | Inverti la direzione |
| `F5` | Ripeti il confronto |
| `Ctrl+F` | Vai al filtro dei risultati |
| `Ctrl+E` / `Ctrl+S` | Esporta Excel / SQL |

**Lettori di schermo.** I pulsanti a sola icona hanno un nome accessibile che
include l'oggetto su cui agiscono ("Elimina la connessione PRODUZIONE"), non un
generico "pulsante".

## Lingua

L'interfaccia parla **italiano e inglese**. Di default segue la lingua del
sistema operativo; si cambia dalla scheda *Configurazione* e ha effetto al
riavvio.

La lingua sorgente del progetto e' l'italiano: le stringhe nel codice sono in
italiano e i cataloghi `diffdb/translations/diffdb_<lingua>.qm` contengono le traduzioni verso
le altre lingue. Per aggiungerne una:

```sh
python tools/traduzioni.py            # aggiorna i .ts ed emette i .qm
pyside6-linguist diffdb/translations/diffdb_en.ts    # traduce (o si modifica il .ts a mano)
python tools/traduzioni.py --check    # verifica che non manchi niente
```

Il controllo gira anche in CI: una stringa nuova non tradotta fa fallire la
build, invece di comparire in italiano dentro l'interfaccia inglese.

Sono tradotti l'interfaccia e i messaggi che vede l'utente. Restano in italiano
i log, gli errori tecnici dei driver e i commenti dentro lo script SQL generato:
sono artefatti diagnostici, e cambiarli a seconda di chi li ha prodotti
renderebbe piu' difficile confrontarli.

## Uso (GUI)

1. **Home** — cosa hai confrontato l'ultima volta (con *Ripeti* per rifarlo),
   come stanno le connessioni configurate, e le due azioni per ricominciare.
2. **Configurazione** — le connessioni, con una pastiglia che dice **dove sta la
   password** di ciascuna: portachiavi, variabile d'ambiente o in chiaro. Il
   pulsante *Testa connessione* si collega davvero e dice cosa ha trovato:
   dialetto, versione del server, quante tabelle vede e se lo schema indicato
   esiste — sbagliare lo schema e' l'errore piu' comune, e senza questo controllo
   si scopre molto piu' tardi, come un confronto che non trova niente.
3. **Scelta** — i due ambienti si scelgono affiancati, *riferimento* a sinistra e
   *da allineare* a destra, con il pulsante ⇄ per invertire la direzione. Sotto
   ogni tendina compaiono dialetto, host e schema: scambiare collaudo con
   produzione e' un clic, e il solo nome non basta a impedirlo.
4. **Risultati** — in cima quante differenze, in che direzione e come si
   distribuiscono per categoria. Sotto, l'albero raggruppato con un colore per
   direzione (manca di qua / manca di la' / diverso). Filtra per nome, spunta le
   voci che ti interessano ed esporta: *Excel* per tutto il report, *SQL* solo
   per le differenze selezionate.

Il confronto gira su un thread separato: la finestra resta reattiva anche su
schemi grandi. Non viene scritto nulla su disco finche' non premi *Esporta*.

## Uso (CLI, per la pipeline)

```sh
python -m diffdb.cli --list                                  # connessioni configurate
python -m diffdb.cli SVI COL --out ./report                  # confronta e scrive gli output
python -m diffdb.cli SVI COL --fail-on-diff                  # esce con 1 se divergono
python -m diffdb.cli sqlite:///a.db sqlite:///b.db           # anche due URL al volo
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
`.github/workflows/ci.yml` li produce per tutti e tre i sistemi a ogni tag, con
le impronte SHA256 e una release vera (gli artifact scadono dopo 90 giorni).

### Firma

Un eseguibile non firmato non e' solo un avviso: con SmartScreen la maggior
parte degli utenti si ferma, e dove c'e' AppLocker o WDAC **non parte affatto**.
Su macOS Gatekeeper lo blocca. In piu' i binari PyInstaller finiscono spesso
nei falsi positivi degli antivirus, proprio perche' anche il malware li usa.

La CI firma se trova i segreti configurati, altrimenti produce i binari non
firmati senza fallire. Serve configurare:

| Dove | Cosa serve |
| --- | --- |
| Windows | Certificato di code signing. Dal giugno 2023 la chiave privata deve stare su hardware o su un servizio cloud: **un `.pfx` in un secret non e' piu' possibile**. La CI usa Azure Trusted Signing (`AZURE_SIGNING_*`); DigiCert KeyLocker e SSL.com eSigner hanno action equivalenti |
| macOS | Iscrizione all'Apple Developer Program, certificato *Developer ID Application* (`MACOS_CERTIFICATE_P12`), e `APPLE_ID` / `APPLE_TEAM_ID` / `APPLE_APP_PASSWORD` per la notarizzazione |

Un certificato EV da' reputazione SmartScreen subito; uno OV se la costruisce
nel tempo. La marca temporale e' obbligatoria: senza, la firma smette di valere
quando il certificato scade.

E' l'unica voce dell'intero progetto che **costa denaro** e non tempo: va decisa
prima, perche' senza certificato il passo di firma non si puo' nemmeno provare.

Per l'icona su Windows serve un `.ico` (opzionale):

```sh
python -c "from PIL import Image; Image.open('images/logo.png').save('images/logo.ico')"
```

## Test

```sh
python -m pytest tests/ --ignore=tests/integration    # unitari, senza database
```

I test creano due database SQLite reali, li confrontano, **eseguono** lo script
generato e verificano che le differenze siano sparite. La finestra viene
istanziata headless (`QT_QPA_PLATFORM=offscreen`), quindi anche la GUI e' coperta.

### Controlli di qualita'

Gli stessi che gira la CI, che li esegue **prima** dei test: sono i piu' veloci
a dire di no.

```sh
ruff check .                                   # stile e trappole note
python -m pytest tests/ --ignore=tests/integration --cov=diffdb --cov-fail-under=70
pip-audit --requirement requirements.txt       # vulnerabilita' note nelle dipendenze
```

La soglia di copertura sta sotto quella attuale: serve a impedire che scenda,
non a inseguire un numero. `pip-audit` a ogni push e' come e' stata trovata (e
chiusa) la prima vulnerabilita' in una dipendenza di questo progetto.

La CI produce anche una **SBOM** (CycloneDX) come artifact: la chiede la
sicurezza aziendale prima di approvare l'adozione, e generarla dopo costa molto
piu' che adesso.

### Test di integrazione (sui motori veri)

Gli unitari girano su SQLite: veloci, ma non dicono niente sugli altri quattro
dialetti supportati. `tests/integration` ripete lo stesso contratto —
**confronta, genera, esegue, riconfronta, nessuna differenza** — parlando con i
database veri.

Ogni dialetto si attiva con la sua variabile d'ambiente; senza, i suoi test
vengono **saltati** invece di fallire, quindi si puo' lanciare anche un dialetto
solo:

| Variabile | Esempio |
| --- | --- |
| `DIFFDB_TEST_POSTGRESQL_URL` | `postgresql+psycopg2://postgres:pw@localhost:5432/postgres` |
| `DIFFDB_TEST_MYSQL_URL` | `mysql+pymysql://root:pw@localhost:3306/mysql` |
| `DIFFDB_TEST_MSSQL_URL` | `mssql+pymssql://sa:pw@localhost:1433/master` |
| `DIFFDB_TEST_ORACLE_URL` | `oracle+oracledb://system:pw@localhost:1521/?service_name=FREEPDB1` |

```sh
DIFFDB_TEST_POSTGRESQL_URL=... python -m pytest tests/integration -v
```

In locale un dialetto senza la sua variabile viene **saltato**. In CI no:
`DIFFDB_TEST_STRICT=1` fa *fallire* un dialetto che non risponde, perche' un job
verde che non ha eseguito niente e' peggio di uno rosso — sembra una conferma.

L'URL punta a un database **amministrativo**: i due ambienti da confrontare
(`diffdb_test_svi` e `diffdb_test_col`) vengono creati e distrutti dai test —
database separati, utenti separati su Oracle, dove lo schema *e'* l'utente.
Nessun dato preesistente viene toccato. In CI i quattro dialetti girano su
container (`.github/workflows/ci.yml`), Oracle in un job a parte perche' e' il
piu' lento a partire.

Limite noto: su SQLite, SQLAlchemy non riflette l'`UNIQUE` dichiarato inline sulla
colonna (solo quello a livello di tabella). Sugli altri database non succede.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| `pyproject.toml` | Pacchetto installabile: comandi `diffdb` e `diffdb-gui` |
| `main.py`, `diffdb/app.py` | Avvio della GUI |
| `diffdb/cli.py` | Interfaccia a riga di comando |
| `diffdb/rules.py` | Regole: filtri e differenze accettate |
| `diffdb/main_window.py` | Finestra principale, tab, gestione connessioni |
| `diffdb/diff_DB.py` | Confronto e generazione degli script SQL |
| `diffdb/schema_snapshot.py` | Lettura della struttura di un database |
| `diffdb/snapshot_io.py` | Snapshot su file: salvataggio, rilettura, sorgenti, impronta |
| `diffdb/audit.py` | Intestazione di tracciabilita' degli script |
| `diffdb/urls.py` | Connection string: segreti, mascheramento, policy |
| `diffdb/keystore.py` | Password nel portachiavi del sistema operativo |
| `diffdb/log.py` | Logging su file, con le password mascherate |
| `diffdb/i18n.py`, `diffdb/preferences.py` | Lingua dell'interfaccia e preferenze |
| `i18n/`, `tools/traduzioni.py` | Cataloghi di traduzione e loro rigenerazione |
| `diffdb/home_tab.py`, `diffdb/choose_tab.py` | Schermata iniziale e scelta degli ambienti |
| `diffdb/results_tab.py` | Tab dei risultati: riepilogo, albero, filtro, export selettivo |
| `diffdb/report.py` | Scrittura di Excel e script (usata da GUI e CLI) |
| `diffdb/worker.py` | Confronto fuori dal thread della GUI |
| `diffdb/qt.py` | Unico punto di accesso a Qt e caricamento dei file `.ui` |
| `diffdb/connections.py`, `diffdb/paths.py` | Connessioni e percorsi (anche da eseguibile) |
| `diffdb/config/dialectConfig.py` | Template SQL e capacita' di ogni dialetto |
| `diffdb/utils/tableUtilities.py` | Confronto di due file DDL testuali (utility a se') |
| `ui/`, `styles/`, `images/` | Layout Qt Designer, tema scuro, icone |

## Contribuire

Come partire, cosa far girare prima di una pull request e le decisioni di
progetto che conviene conoscere: [CONTRIBUTING.md](CONTRIBUTING.md).

Per segnalare una vulnerabilita' (**non** con una issue pubblica), i privilegi
minimi che servono a DiFFDB e cosa fa davvero con i tuoi database:
[SECURITY.md](SECURITY.md).

Le modifiche versione per versione: [CHANGELOG.md](CHANGELOG.md).

## Licenza

MIT (vedi `LICENSE`). La GUI usa **PySide6** (LGPL), non PyQt5: quest'ultimo e'
GPL/commerciale e distribuire l'eseguibile avrebbe richiesto di rilasciare tutto
sotto GPL o di comprare una licenza.
