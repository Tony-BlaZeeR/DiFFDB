# DiFFDB — Note di progettazione dell'interfaccia

Questo documento raccoglie le scelte di progettazione dell'interfaccia di DiFFDB: le due direzioni visive (**Moderna** e **Retro**), l'architettura delle schermate, i design token e i componenti. Serve come riferimento per mantenere coerente l'interfaccia quando la si estende.

Le due varianti condividono **la stessa architettura informativa, gli stessi flussi, gli stessi dati e gli stessi componenti**: cambia solo il linguaggio visivo.

1. **Moderna** — pulita, contemporanea, dark-first.
2. **Retro** — estetica pixel/terminale ispirata alle interfacce testuali (verde su nero, bordi netti, font bitmap).

---

## 1. Cos'è DiFFDB (contesto)

DiFFDB è uno strumento desktop che **confronta lo schema di due database** dello stesso progetto in ambienti diversi (es. Sviluppo vs Collaudo vs Produzione) e mostra le **differenze strutturali**, poi genera gli **script SQL di allineamento** e un **report Excel**.

Confronta quattro tipi di oggetti di schema:
- **Tabelle** (incluse le colonne mancanti su una tabella comune ai due ambienti)
- **Viste**
- **Sinonimi**
- **Sequenze**

Database supportati: **Oracle, PostgreSQL, MySQL/MariaDB, SQL Server**. Le connessioni sono salvate come coppie `nome, stringa di connessione`.

Esempio di confronto:
- Riferimento: `db1` · Da allineare: `db2` · Differenze trovate: **8**
- Nomi ambiente tipici nel dominio: **SVI** (sviluppo), **COL** (collaudo), **PRE** (preproduzione), **PROD**.

Terminologia (l'app è in italiano):
- "Connessione", "Stringa di Connessione", "Configurazione", "Scelta", "Confronta", "Differenze", "Ambiente di riferimento", "Ambiente da allineare".

---

## 2. Architettura informativa e schermate

L'app è una singola finestra desktop con **barra del titolo personaliz­zata (frameless)** e **navigazione a tab/sezioni**. Le schermate seguenti esistono in entrambe le varianti.

### 2.1 App shell / Title bar
- Finestra senza cornice di sistema. Barra del titolo custom con: **logo** + wordmark **"DiFFDB"** a sinistra; pulsanti **minimizza** e **chiudi** a destra.
- Navigazione principale a 3 sezioni: **Home**, **Configurazione** (connessioni), **Scelta** (confronto). In più la vista **Risultati** (post-confronto).
- Larghezza finestra di riferimento: ~**1000×650** (la dimensione reale di default). Desktop-first; deve reggere fino a ~1400px e non rompersi sotto i 900px.

### 2.2 Home
- Hero con il **logo** (pixel-art, vedi §4) e un saluto/claim breve.
- Card **"Ultimo confronto"**: riferimento → da allineare, numero differenze, data/ora.
- CTA primaria: **"Nuovo confronto"** → porta a Scelta.

### 2.3 Configurazione — gestione connessioni
- **Tabella** delle connessioni salvate con colonne: **Nome**, **Stringa di connessione** (parzialmente mascherata, es. password offuscata), **Tipo DB** (badge: Oracle / PostgreSQL / MySQL / SQL Server), azioni **Modifica** (icona matita) e **Elimina** (icona cestino) per riga.
- Pulsante **"Aggiungi stringa di connessione"**.
- Stato **vuoto**: nessuna connessione → messaggio + CTA aggiungi.

### 2.4 Dialog Aggiungi / Modifica connessione
- Campi: **Nome Connessione** (input), **Tipo DB** (select: Oracle/PostgreSQL/MySQL/SQL Server), **Stringa di Connessione** (input monospace, es. `oracle+cx_oracle://user:pwd@host:1521/?service_name=schema`), **Schema** (opzionale).
- Azione secondaria: **"Prova connessione"** con esito (success/errore).
- Pulsante primario: **Aggiungi** (o **Modifica** in edit).

### 2.5 Scelta — impostazione del confronto
- Due selettori: **Database 1** (ambiente di **riferimento**) e **Database 2** (ambiente **da allineare**), popolati dalle connessioni salvate.
- Campi schema opzionali per ciascun lato.
- Pulsante primario dinamico: **"Confronta {DB1} vs {DB2}"** (il testo cambia con la selezione).
- Rappresentare visivamente la **direzione** del confronto (riferimento → da allineare): è concettualmente importante.

### 2.6 Stato di avanzamento (loading)
- Vista/overlay mentre il confronto gira: connessione ai due DB, lettura oggetti, calcolo differenze. Mostrare progressione per i 4 tipi di oggetto.

### 2.7 Risultati del confronto — schermata chiave
È la vista più importante. Deve mostrare le differenze in modo scansionabile.
- **Riepilogo** in alto: totale differenze (es. **8**), suddiviso per categoria con contatori: Tabelle N · Viste N · Sinonimi N · Sequenze N. Indicare i due ambienti a confronto.
- **Sezioni/tab per categoria**: Tabelle · Viste · Sinonimi · Sequenze.
- Ogni **riga di differenza** mostra:
  - **Nome oggetto**
  - **In quale ambiente è presente / manca** (es. "presente solo in SVI", "manca in COL")
  - Per le tabelle: eventuale **colonna/campo** mancante
  - Un segno direzionale/semantico (vedi colori diff §5).
- Azioni: **Esporta script SQL** (gli `ALTER/CREATE/DROP` di allineamento) e **Esporta report Excel**. Mostrare anche un'anteprima degli script SQL generati (blocco codice).
- Stato **"Nessuna differenza"**: schermata positiva dedicata.

### 2.8 Stati di errore
- Errore di connessione al database (messaggio chiaro, con il tipo DB e l'host; CTA "Riprova" / "Modifica connessione").

---

## 3. Contenuti d'esempio usati nelle schermate

Connessioni d'esempio:

| Nome | Tipo | Stringa (mascherata) | Schema |
|---|---|---|---|
| SVI  | Oracle     | `oracle+cx_oracle://app:••••@svi-db:1521/?service_name=APPDB` | APP |
| COL  | Oracle     | `oracle+cx_oracle://app:••••@col-db:1521/?service_name=APPDB` | APP |
| PRE  | PostgreSQL | `postgresql://app:••••@pre-db:5432/appdb` | public |
| PROD | SQL Server | `mssql+pyodbc://app:••••@prod-db:1433/APPDB` | dbo |

Esempi di righe-differenza (confronto **SVI → COL**, 8 differenze):

| Categoria | Oggetto | Dettaglio |
|---|---|---|
| Tabella  | `ORDINI`        | presente solo in **SVI** |
| Tabella  | `CLIENTI`       | colonna `EMAIL_PEC` manca in **COL** |
| Tabella  | `FATTURE`       | colonna `DATA_SCADENZA` manca in **SVI** |
| Vista    | `V_ORDINI_APERTI` | presente solo in **SVI** |
| Vista    | `V_SALDI`       | presente solo in **COL** |
| Sinonimo | `SYN_CLIENTI`   | presente solo in **SVI** |
| Sequenza | `SEQ_ORDINI`    | presente solo in **SVI** |
| Sequenza | `SEQ_FATTURE`   | presente solo in **COL** |

Esempio di script SQL generato (per l'anteprima):
```sql
-- Tables Scripts --
CREATE TABLE ORDINI (...);
ALTER TABLE CLIENTI ADD EMAIL_PEC ...;
-- Views Scripts --
CREATE VIEW V_ORDINI_APERTI AS ...;
-- Sequences Scripts --
CREATE SEQUENCE SEQ_ORDINI ...;
```

---

## 4. Il logo e l'estetica retro (riferimento visivo)

Il logo è un **wordmark pixel-art** ("DiFFDB") a blocchi, con un **gradiente verticale verde** su sfondo **nero verdastro**: dal **menta chiaro in alto** al **verde-teal scuro in basso**. È la firma visiva da cui deriva soprattutto la variante Retro.

Caratteristiche della Retro:
- Pixel/blocchi a spigolo vivo, nessun arrotondamento.
- Gradiente verde verticale menta → teal profondo.
- Sfondo quasi nero con tinta verde.
- Sensazione "terminale / TUI".

---

## 5. Design tokens (base condivisa + override per variante)

### 5.1 Palette verde (derivata dal logo) — usata da entrambe, pesata diversamente

```
/* Sfondi */
--bg-base:        #0B110D;  /* nero verdastro */
--bg-surface:     #111A14;
--bg-raised:      #18241C;
--border:         #243528;

/* Scala verde (gradiente del logo, chiaro -> scuro) */
--green-50:       #D6EBDD;  /* menta/quasi-bianco (highlight, testo primario) */
--green-100:      #B9DCC6;
--green-200:      #93C4A6;
--green-300:      #6FA888;
--green-400:      #4E8A6B;  /* primario azioni */
--green-500:      #3C7156;
--green-600:      #2E5A44;
--green-700:      #224634;
--green-800:      #17311F;  /* teal profondo (fondo gradiente) */

/* Testo */
--text-primary:   #D6EBDD;
--text-secondary: #8FB39C;
--text-muted:     #5E7A68;
```

### 5.2 Colori semantici per le differenze (diff) — concetto chiave della Results view
- **Presente solo nel riferimento (DB1)** → tono **verde** (es. `--green-300/400`): "da aggiungere nell'ambiente da allineare".
- **Presente solo nel da-allineare (DB2)** → tono **ambra/caldo** di contrasto: "in più / da rimuovere".
- **Colonna mancante** → stato **attenzione** (ambra), con indicazione del lato.
- **Nessuna differenza** → verde pieno positivo.
- Ambra suggerita: `#C9A227`. Rosso errore: `#C65F4A`.
  - Nella **Retro**, mantenere la palette il più possibile **monocromatica verde**: usare luminosità/intensità per distinguere, e l'ambra solo come unico accento caldo. Niente arcobaleni.
  - Nella **Moderna** è ammessa una palette semantica più ricca (verde/ambra/rosso/neutro) ma sobria.

### 5.3 Badge tipo DB
Pillola con colore/etichetta per: **Oracle**, **PostgreSQL**, **MySQL/MariaDB**, **SQL Server**. Nella Retro resa come tag testuale tipo `[ORACLE]`.

---

## 6. Linee guida per variante

### 6.1 UI MODERNA
- **Tono**: strumento professionale per DBA/sviluppatori, dark-first, ordinato, respiro generoso.
- **Tipografia**: sans contemporanea (Inter / simili) per UI; **monospace** (JetBrains Mono / simile) per stringhe di connessione, nomi oggetto e SQL.
- **Forma**: raggi morbidi (8–12px), gerarchia con elevazione/ombre sottili, separatori leggeri.
- **Colore**: sfondi `--bg-*`, verde come accento primario; palette semantica sobria per i diff. Possibile accento gradiente verde solo su elementi chiave (hero, CTA primaria).
- **Tabelle**: righe comode, hover, allineamento numerico dei contatori, header sticky.
- **Microinterazioni**: focus ring verde, transizioni fluide, toast di conferma export.
- Supporto anche a tema **chiaro** (il default è scuro).

### 6.2 UI RETRO
- **Tono**: terminale / TUI reinterpretata.
- **Tipografia**: **font bitmap/pixel** per titoli e wordmark; **monospace** per tutto il corpo. Nessun antialiasing percepito sui titoli.
- **Forma**: **spigoli vivi**, `border-radius: 0`. Bordi a linea netta (anche doppia linea stile TUI/box-drawing `┌─┐│└┘`). Elementi come "finestre" ASCII.
- **Colore**: verde su nero come principio dominante; gradiente verticale menta→teal sui titoli (come il logo). Accenti: solo l'ambra come unico colore caldo.
- **Dettagli d'atmosfera** (sottili, con moderazione): leggere **scanline**, etichette in **UPPERCASE**, eventuale glow tenue sul testo verde. Niente che comprometta la leggibilità.
- **Componenti**: pulsanti come `[ CONFRONTA ]`, barra di avanzamento a blocchi `[████████░░] 80%`, tabelle delimitate da caratteri box-drawing, badge come `[ORACLE]`.
- **Title bar**: stile barra di una finestra testuale; controlli come `[_]` `[X]`.
- La **Results view** in retro ricorda l'output di un comando `diff`: elenco a griglia monospace, segni `+ / - / ~` per presente-solo-in-A / presente-solo-in-B / modificato, allineato in colonne.

---

## 7. Componenti

Per ciascuno vanno previsti gli stati: **default, hover, focus, active, disabled, loading** (dove applicabile) e **vuoto/errore** per i contenitori.

- Barra del titolo custom + controlli finestra
- Navigazione a sezioni (tab Home / Configurazione / Scelta + Risultati)
- Pulsanti: primario, secondario, pericoloso (elimina), icona
- Input testo + input monospace (stringa connessione)
- Select / combobox (tipo DB, scelta connessioni)
- Tabella dati (connessioni) con azioni per riga
- Riga-differenza (diff row) con indicatore direzionale/semantico
- Badge/pill (tipo DB, ambiente, categoria oggetto)
- Card riepilogo ("Ultimo confronto", contatori differenze)
- Dialog/modal (aggiungi/modifica connessione)
- Barra/indicatore di avanzamento
- Blocco codice (anteprima SQL)
- Toast/notifica (esito export, esito "prova connessione")
- Stati: vuoto, nessuna differenza, errore connessione

---

## 8. Vincoli trasversali

Desktop-first (finestra ~1000×650, reggere 900–1400px), dark come default, accessibile: contrasto **AA** sul testo e, per i diff, non affidarsi al solo colore ma usare anche icone/segni `+ - ~`. Contenuti in **italiano** (con traduzione inglese).
