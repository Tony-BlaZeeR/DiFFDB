# Diario delle modifiche

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e le
versioni [SemVer](https://semver.org/lang/it/).

La versione conta piu' del solito, qui: ogni script generato la porta in testa.
Quando esce una correzione al generatore, e' quello che dice **quali script
prodotti in passato ne sono affetti**, invece di doverli sospettare tutti.

## [Non rilasciato]

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

## [1.1.0] e precedenti

Vedi la storia dei commit. Da questa versione il diario viene tenuto.
