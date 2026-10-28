# Diario delle modifiche

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e le
versioni [SemVer](https://semver.org/lang/it/).

La versione conta piu' del solito, qui: ogni script generato la porta in testa.
Quando esce una correzione al generatore, e' quello che dice **quali script
prodotti in passato ne sono affetti**, invece di doverli sospettare tutti.

## [Non rilasciato]

### Aggiunto

- **Interfaccia ridisegnata, a due varianti.** *Moderna* (pulita, dark-first) e
  *Retro* (terminale/TUI: font a blocchi, spigoli vivi, titoli incisi sul
  bordo), ognuna in **chiaro e scuro**. Si cambiano a caldo dalla barra del
  titolo e la scelta e' salvata in `diffdb.ini`. Lo stile vive in `theme.py`
  (token) + due fogli QSS riempiti a runtime: la tavolozza sta in un posto
  solo e l'applicazione non e' stata riscritta, perche' era gia' stilizzata per
  proprieta' QSS.
- **Colore dell'interfaccia scelto dall'utente** (preset o selettore libero):
  non tinge solo i pulsanti ma **l'intero tema** — fondi, bordi, testi — a
  parita' di luminosita', cosi' il contrasto resta WCAG AA qualunque colore si
  scelga. I colori semantici del diff restano distinti.
- **Schermate dedicate** per avanzamento, errore e "nessuna differenza", al
  posto delle finestre di dialogo: la schermata d'errore mostra il messaggio
  (mascherato) e le azioni per rimediare (riprova, modifica connessione).
- **Nuovo logo**: un Delta a tre strati (la differenza, e i livelli di un
  database), in due stili dello stesso marchio — trapezi lisci nella Moderna,
  blocchi pixel nel Retro. Disegnato a runtime col gradiente del tema, quindi
  segue variante e colore come il resto; piu' `logo.ico` multi-size per
  finestra, taskbar ed eseguibile.
- **README in inglese** (`README.en.md`), con selettore di lingua in testa a
  entrambi.
- **Vincoli CHECK** nel confronto: quarto tipo di vincolo dopo indici, foreign
  key e unique. Si confrontano per condizione normalizzata, non per nome — i
  nomi sono spesso autogenerati dal motore e cambiano da un ambiente
  all'altro. Generazione e annullamento seguono lo stesso schema degli altri
  vincoli (MySQL ha una sintassi propria per toglierli, `DROP CHECK`, diversa
  da `DROP CONSTRAINT`). Letti su tutti e quattro i motori veri: su SQL
  Server con una query diretta sul catalogo di sistema, perche' il driver
  `pymssql` non implementa affatto la riflessione dei CHECK in SQLAlchemy. Su
  SQLite la lettura resta disattivata: la riflessione e' inaffidabile anche
  con un solo vincolo.
- **Timeout di interrogazione** (60 secondi, oltre a quello di connessione
  gia' esistente): protegge da una query che si blocca *dopo* essersi
  connessa, non solo durante la connessione. Un secondo per driver: pymssql ha
  un vero timeout per chiamata passato in connessione, oracledb lo stesso
  concetto come proprieta' impostata sulla connessione appena aperta,
  PostgreSQL e MySQL usano una variabile di sessione impostata a ogni nuova
  connessione fisica. Verificato sui quattro motori, incluso il caso che una
  prima versione perdeva in silenzio: il timeout doveva reggere anche al
  secondo prestito della stessa connessione dal pool, non solo al primo (e su
  Oracle, il caso che passare `call_timeout` come argomento di connessione
  invece che come proprieta' post-connessione rompeva la connessione stessa).
- **`--dry-run`**: mostra le differenze come sempre ma non scrive niente su
  disco — nessuno script, nessun Excel, nessuno snapshot, nessuna regola
  accettata. Utile per vedere cosa farebbe un comando prima di lasciarlo
  toccare il filesystem, specialmente in pipeline.
- **`--json`**: le differenze in un oggetto JSON su stdout invece del
  riepilogo testuale, con chiavi stabili in inglese pensate per essere lette
  da un altro programma. Si combina con `--dry-run` e `--fail-on-diff`.
- **Trigger** nel confronto: nessun dialetto li riflette via SQLAlchemy,
  l'Inspector non ha nemmeno un metodo per elencarli. Letti con il modo
  nativo di ogni motore di ricostruire il CREATE TRIGGER completo
  (`pg_get_triggerdef`, `DBMS_METADATA.GET_DDL`, `sys.sql_modules`, `SHOW
  CREATE TRIGGER`). Confronto e allineamento sempre DROP + CREATE, mai
  CREATE OR REPLACE: MySQL non lo supporta per i trigger in nessuna versione.
  Limite noto: su PostgreSQL e Oracle il corpo che conta e' spesso nella
  funzione/procedura richiamata, non nel testo del trigger — confrontare
  anche quelle e' un lavoro a parte, non ancora fatto.
- **Stored procedure e funzioni** nel confronto: stesso principio dei
  trigger, stesso DROP + CREATE sempre. Solo le routine standalone, non i
  membri di un package Oracle. Su PostgreSQL una funzione puo' essere
  sovraccaricata: il DROP indica anche gli argomenti
  (`pg_get_function_identity_arguments`), non solo il nome. Chiude (in parte)
  il limite dei trigger appena sopra: la funzione richiamata da un trigger
  ora si confronta anche lei, non solo il legame col trigger.

### Corretto

- L'albero dei risultati non e' piu' quadratico nel numero di differenze:
  passare il genitore al costruttore di ogni riga, una alla volta, e'
  quadratico in Qt. Su 100.000 differenze si passa da 7-8 secondi di
  interfaccia bloccata a poco piu' di uno, costruendo le righe senza genitore
  e attaccandole tutte insieme.
- `--accept` non muta piu' sul posto `rules.NESSUNA`: e' un singleton
  condiviso da tutto il processo, usato come regole predefinite in una
  dozzina di firme di funzione. Mutarlo inquinava ogni chiamata successiva
  che ricadeva sullo stesso default per il resto del processo — invisibile
  in CLI (un processo per comando), ma reale nella GUI, che resta aperta e
  richiama le stesse funzioni piu' volte. Scoperto da un test di `--dry-run`
  che si e' trovato le regole di un test precedente.

## [1.2.0]

### Aggiunto

- **Snapshot su file** (`--snapshot`): la struttura di un ambiente si congela in
  JSON e si riconfronta piu' avanti. Sblocca la drift detection, la baseline
  versionata in git e il confronto offline. Uno snapshot riletto genera lo
  script di allineamento come se fossi connesso.
- **Regole di confronto** (`diffdb.rules.json`): filtri per modello di nome,
  applicati prima della lettura, piu' una baseline di differenze accettate
  (`--accept`). E' quello che rende `--fail-on-diff` utilizzabile in pipeline su
  uno schema che parte gia' con differenze note.
- **Password nel portachiavi del sistema operativo** (`--set-password`): nel file
  delle connessioni resta il segnaposto `${keyring}`. Con
  `DIFFDB_REQUIRE_SECRET_REFS=1` le password in chiaro vengono rifiutate.
- **Tracciabilita' degli script**: ogni `.sql` porta versione, data, autore e
  l'impronta dei due ambienti. `--verify` dice se l'ambiente e' cambiato dopo la
  generazione, cioe' se lo script e' ancora valido.
- **Suite di integrazione** sui motori veri (PostgreSQL, MySQL, SQL Server,
  Oracle) con lo stesso contratto degli unitari: confronta, genera, esegue,
  riconfronta.
- **Test della connessione** nell'interfaccia: dice dialetto, versione, quante
  tabelle vede e se lo schema indicato esiste.
- **Interfaccia in italiano e inglese**, con selettore della lingua.
- **Pacchetto installabile**: `pip install diffdb`, comandi `diffdb` e
  `diffdb-gui`.
- Lettura dei due ambienti **in parallelo**, timeout di connessione e pulsante
  **Annulla**.
- File di log con rotazione, con le connection string mascherate.
- **Script di annullamento** (`annulla_<ambiente>.sql`) accanto a ogni script di
  allineamento: disfa quello che il primo ha fatto. Verificato sui quattro
  motori veri — si allinea, si disfa, e l'impronta dell'ambiente torna
  identica.

### Modificato

- `src/`, `config/` e `utils/` sono diventati un unico pacchetto **`diffdb/`**:
  erano nomi generici che, installati in un ambiente condiviso, collidono.
  Gli import cambiano da `src.x` a `diffdb.x`.
- Le tabelle nuove si creano in **ordine di dipendenza**, e lo script si apre in
  transazione dove il database sa annullare un DDL.
- Interfaccia ridisegnata: la direzione del confronto e' esplicita, i risultati
  hanno un riepilogo con i conteggi, la finestra si ridimensiona.
- Le password nella tabella delle connessioni mostrano **dove stanno davvero**.

### Corretto

- Il cambio di tipo non perde piu' il `NOT NULL` su MySQL e SQL Server, che
  riscrivono la colonna da capo. Su Oracle il vincolo si riafferma solo quando
  cambia davvero, perche' ripeterlo solleva ORA-01442.
- Gli `ALTER TABLE` generati sono **qualificati con lo schema**: senza, finivano
  sulla tabella omonima dello schema di default dell'utente connesso.
- Una chiave primaria intera non diventa piu' `SERIAL` quando la tabella viene
  ricreata da uno snapshot: PostgreSQL le avrebbe aggiunto una sequenza e un
  default che l'originale non ha.
- La finestra si puo' ridimensionare: il layout dichiarava minimo e massimo
  uguali.
- Contrasto dei colori portato a WCAG AA, e la direzione di una differenza non
  e' piu' affidata al solo colore.
- Le viste di MySQL non vengono piu' avvolte in un secondo `CREATE VIEW`: MySQL
  restituisce la definizione completa, con `ALGORITHM` e `DEFINER` fra `CREATE`
  e `VIEW`, e l'intestazione non veniva riconosciuta.
- I tipi di SQL Server con collation non rompono piu' l'`ALTER TABLE`: `str()`
  li rende con le virgolette (`COLLATE "SQL_Latin1_..."`) e il server le
  rifiuta. Lo snapshot ora tiene separata la forma per il confronto da quella
  per il DDL.

  Entrambi trovati dalla prima esecuzione della CI di integrazione sui motori
  veri: PostgreSQL passava da sempre, MySQL e SQL Server no, e senza eseguirli
  non c'era modo di accorgersene.

## [1.1.0] e precedenti

Vedi la storia dei commit. Da questa versione il diario viene tenuto.
