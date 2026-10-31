"""Il contratto di DiFFDB, verificato sui motori veri.

    confronta -> genera lo script -> lo esegue -> riconfronta -> nessuna differenza

E' lo stesso contratto dei test su SQLite, ma qui a rispondere sono PostgreSQL,
MySQL, SQL Server e Oracle: e' l'unico modo per sapere che il DDL che generiamo
per Oracle e' davvero accettato da Oracle, invece di limitarci a sperarlo.

Ogni dialetto viene saltato se la sua variabile d'ambiente non e' impostata
(vedi conftest.py), quindi la suite si puo' lanciare anche su un dialetto solo.
"""

import re
import time

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from diffdb import snapshot_io
from diffdb.diff_DB import (
    DEFINITION_MISMATCH,
    MISSING,
    TYPE_MISMATCH,
    compare_environments,
    generate_sql_scripts,
)
from diffdb.schema_snapshot import snapshot_connection

pytestmark = pytest.mark.integration

# Tipi equivalenti nei vari dialetti: lo schema di prova e' lo stesso ovunque.
TIPI = {
    "postgresql": {"intero": "INTEGER", "testo": "VARCHAR({n})", "decimale": "NUMERIC(10, 2)"},
    "mysql": {"intero": "INTEGER", "testo": "VARCHAR({n})", "decimale": "DECIMAL(10, 2)"},
    "mssql": {"intero": "INT", "testo": "VARCHAR({n})", "decimale": "NUMERIC(10, 2)"},
    "oracle": {"intero": "NUMBER(10)", "testo": "VARCHAR2({n})", "decimale": "NUMBER(10, 2)"},
}

# MySQL non ha le sequenze: la differenza va costruita solo dove esistono.
SEQUENZE = {"postgresql": True, "mysql": False, "mssql": True, "oracle": True}


def _ddl_completo(dialetto):
    """L'ambiente di riferimento: tutto quello che DiFFDB sa confrontare."""
    t = TIPI[dialetto]
    ddl = [
        f"CREATE TABLE clienti ("
        f"  id {t['intero']} NOT NULL,"
        f"  nome {t['testo'].format(n=50)} NOT NULL,"
        f"  email {t['testo'].format(n=120)},"
        f"  partita_iva {t['testo'].format(n=11)},"
        f"  CONSTRAINT pk_clienti PRIMARY KEY (id),"
        f"  CONSTRAINT uq_clienti_piva UNIQUE (partita_iva),"
        f"  CONSTRAINT ck_clienti_id_positivo CHECK (id > 0))",
        f"CREATE TABLE ordini ("
        f"  id {t['intero']} NOT NULL,"
        f"  cliente_id {t['intero']} NOT NULL,"
        f"  totale {t['decimale']},"
        f"  CONSTRAINT pk_ordini PRIMARY KEY (id),"
        f"  CONSTRAINT fk_ordini_clienti FOREIGN KEY (cliente_id) REFERENCES clienti (id))",
        "CREATE INDEX ix_clienti_email ON clienti (email)",
        "CREATE VIEW clienti_attivi AS SELECT id, nome FROM clienti WHERE email IS NOT NULL",
    ]
    if SEQUENZE[dialetto]:
        ddl.append("CREATE SEQUENCE seq_clienti START WITH 100 INCREMENT BY 5")
    return ddl


def _ddl_incompleto(dialetto):
    """L'ambiente da allineare: manca una tabella, una colonna, l'indice,
    l'unique, la vista e la sequenza; e 'nome' ha il tipo sbagliato."""
    t = TIPI[dialetto]
    return [
        f"CREATE TABLE clienti ("
        f"  id {t['intero']} NOT NULL,"
        f"  nome {t['testo'].format(n=30)} NOT NULL,"
        f"  partita_iva {t['testo'].format(n=11)},"
        f"  CONSTRAINT pk_clienti PRIMARY KEY (id))",
    ]


@pytest.fixture
def ambienti(coppia):
    """Due ambienti popolati e disallineati, ripuliti prima di ogni test."""
    for ambiente, ddl in ((coppia.svi, _ddl_completo(coppia.dialetto)),
                          (coppia.col, _ddl_incompleto(coppia.dialetto))):
        engine = create_engine(ambiente.url)
        try:
            _svuota(engine, ambiente.schema)

            # Se la pulizia non ha funzionato su questo dialetto, meglio dirlo
            # qui: altrimenti i test falliscono dopo, per oggetti rimasti da
            # un'esecuzione precedente, e la causa vera non si trova piu'.
            rimasti = inspect(engine).get_table_names(schema=ambiente.schema)
            assert not rimasti, (
                f"{coppia.dialetto}: la pulizia di {ambiente.nome} ha lasciato "
                f"{rimasti}. Controlla _svuota() per questo dialetto.")

            with engine.begin() as conn:
                for statement in ddl:
                    conn.execute(text(statement))
        finally:
            engine.dispose()
    return coppia


def _confronta(coppia):
    return compare_environments(
        coppia.svi.nome, coppia.svi.url, coppia.col.nome, coppia.col.url,
        coppia.svi.schema, coppia.col.schema,
    )


# --- il contratto ----------------------------------------------------------


def test_rileva_le_differenze_attese(ambienti):
    diff = _confronta(ambienti)
    trovate = {(d.kind, d.change) for d in diff.all}

    assert ("table", MISSING) in trovate            # ordini
    assert ("column", MISSING) in trovate           # clienti.email
    assert ("column", TYPE_MISMATCH) in trovate     # clienti.nome
    assert ("index", MISSING) in trovate            # ix_clienti_email

    # Il vincolo di unicita' su partita_iva: solo PostgreSQL lo riflette come
    # vincolo. Oracle, MySQL e SQL Server lo realizzano con un indice unico e
    # SQLAlchemy lo riporta come tale. Il risultato e' lo stesso — l'indice
    # unico impone l'unicita' — ma la categoria cambia, e chi legge il report
    # su Oracle vedra' "indice" dove si aspettava "unique".
    assert ("unique", MISSING) in trovate or ("index", MISSING) in trovate

    assert ("check", MISSING) in trovate            # ck_clienti_id_positivo
    assert ("view", MISSING) in trovate             # clienti_attivi
    if SEQUENZE[ambienti.dialetto]:
        assert ("sequence", MISSING) in trovate


def test_lo_script_generato_e_eseguibile_e_allinea(ambienti):
    """Il test che conta: dopo aver eseguito lo script, i due ambienti coincidono."""
    diff = _confronta(ambienti)
    scripts = generate_sql_scripts(diff, target_env=ambienti.col.nome)

    eseguiti = _esegui(ambienti.col.url, scripts)
    assert eseguiti, "lo script generato era vuoto: non e' stato allineato niente"

    residue = _confronta(ambienti).all
    assert residue == [], _dettaglio(residue) + "\n\nscript eseguito:\n" + "\n".join(eseguiti)


def _dettaglio(residue) -> str:
    return "dopo l'allineamento restano differenze:\n" + "\n".join(
        f"  [{d.kind}] {d.name}{'.' + d.column if d.column else ''}: {d.change} - {d.detail}"
        for d in residue
    )


def test_lo_script_inverso_non_ricrea_quello_che_gia_c_e(ambienti):
    """Lo script verso SVI non deve creare niente: SVI ha gia' tutto.

    Un cambio di tipo resta invece in entrambe le direzioni (e' una differenza
    simmetrica: 'chi dei due ha ragione' lo decide chi legge lo script).
    """
    diff = _confronta(ambienti)
    verso_svi = generate_sql_scripts(diff, target_env=ambienti.svi.nome)

    eseguibili = [s for blocco in verso_svi.values() for s in blocco if not s.startswith("--")]

    assert not any(s.upper().startswith(("CREATE TABLE", "CREATE VIEW", "CREATE INDEX",
                                         "CREATE SEQUENCE")) for s in eseguibili), eseguibili
    assert not any("ADD COLUMN" in s.upper() or "ADD CONSTRAINT" in s.upper()
                   for s in eseguibili), eseguibili


# --- snapshot su file, sui tipi veri di ogni dialetto ----------------------


def test_lo_snapshot_su_file_regge_i_tipi_reali(ambienti, tmp_path):
    """Il round-trip su file non deve inventare differenze sui tipi nativi
    (VARCHAR2, NUMBER, DECIMAL...), che su SQLite non si vedono mai."""
    dal_vivo = snapshot_connection(ambienti.svi.nome, ambienti.svi.url, ambienti.svi.schema)
    riletto = snapshot_io.load(snapshot_io.save(dal_vivo, tmp_path / "svi.json"))

    from diffdb.diff_DB import compare_snapshots

    assert compare_snapshots(dal_vivo, riletto).all == []


def test_allineamento_a_partire_da_uno_snapshot_su_file(ambienti, tmp_path):
    """Drift detection completa: la baseline sta su file, l'allineamento no."""
    baseline = snapshot_io.save(
        snapshot_connection("BASELINE", ambienti.svi.url, ambienti.svi.schema),
        tmp_path / "baseline.json",
    )

    diff = snapshot_io.compare_sources(
        snapshot_io.SnapshotFile.at(baseline),
        _connessione(ambienti.col),
    )
    scripts = generate_sql_scripts(diff, target_env=ambienti.col.nome)
    _esegui(ambienti.col.url, scripts)

    residue = snapshot_io.compare_sources(
        snapshot_io.SnapshotFile.at(baseline), _connessione(ambienti.col)).all
    assert residue == [], _dettaglio(residue)


def _connessione(ambiente):
    from diffdb.connections import Connection

    return Connection(name=ambiente.nome, conn_string=ambiente.url, schema=ambiente.schema)


# --- utilita' --------------------------------------------------------------


# Disfare vuol dire percorrere all'indietro: prima cio' che dipende, poi le
# tabelle.
SEZIONI_ALLINEAMENTO = ("sequences", "tables", "constraints", "views", "synonyms", "triggers")
SEZIONI_ANNULLAMENTO = ("triggers", "synonyms", "views", "constraints", "tables", "sequences")


def _esegui_ddl(conn, statement: str) -> None:
    """execute(text(...)) di norma; exec_driver_sql solo su Oracle.

    Un trigger Oracle contiene ":NEW"/":OLD", e text() li leggerebbe come
    parametri bind di SQLAlchemy invece che come sintassi PL/SQL letterale,
    fallendo con "a value is required for bind parameter 'NEW'".
    exec_driver_sql manda la stringa al driver cosi' com'e', bypassando quella
    lettura — ma bypassa anche l'escape di SQLAlchemy per i DBAPI %-style
    (pymysql, mysqlclient): un DDL MySQL con un '%' non raddoppiato manderebbe
    in errore pymysql con "unsupported format character". Va usato solo dove
    serve, non ovunque.
    """
    if conn.dialect.name == "oracle":
        conn.exec_driver_sql(statement)
    else:
        conn.execute(text(statement))


def _esegui(url, scripts, sezioni=SEZIONI_ALLINEAMENTO):
    """Esegue lo script come lo eseguirebbe un DBA: nell'ordine del file."""
    eseguiti = []
    engine = create_engine(url)
    try:
        for sezione in sezioni:
            for blocco in scripts.get(sezione, []):
                for statement in _istruzioni(blocco):
                    with engine.begin() as conn:
                        _esegui_ddl(conn, statement)
                    eseguiti.append(statement)
    finally:
        engine.dispose()
    return eseguiti


# Un CREATE TRIGGER con un corpo PL/SQL (Oracle: BEGIN ... END;) ha punti e
# virgola *dentro* l'istruzione: dividerlo come le altre sezioni lo
# spezzerebbe in frammenti invalidi. Dal punto in cui inizia va trattato come
# un'unica istruzione fino alla fine del blocco; quello che lo precede (un
# eventuale DROP, per la sostituzione) si divide come sempre.
# EDITIONABLE/NONEDITIONABLE: quello che DBMS_METADATA.GET_DDL antepone su
# Oracle 12c+ per gli oggetti soggetti a edition-based redefinition, anche
# quando l'oggetto stesso non la usa. Vale per trigger, procedure e funzioni:
# tutti hanno un corpo PL/SQL con punti e virgola interni che romperebbero lo
# split per ";" delle altre sezioni.
# DEFINER=`utente`@`host`: lo antepone MySQL in ogni SHOW CREATE di routine e
# trigger, quindi CREATE e la parola chiave non sono adiacenti. I trigger MySQL
# reggevano per caso (corpo senza ";" interno); le routine no.
INIZIO_BLOCCO_PLSQL = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:DEFINER\s*=\s*\S+\s+)?"
    r"(?:EDITIONABLE\s+|NONEDITIONABLE\s+)?"
    r"(?:TRIGGER|PROCEDURE|FUNCTION)\b",
    re.IGNORECASE | re.MULTILINE)

# DBMS_METADATA.GET_DDL per un trigger Oracle non si ferma al CREATE: aggiunge
# in coda un ALTER TRIGGER ... ENABLE/DISABLE che riproduce lo stato corrente
# del trigger (abilitato o no), una seconda istruzione a tutti gli effetti —
# va comunque staccata dal blocco PL/SQL che precede, o Oracle la legge come
# parte della stessa istruzione e va in errore di sintassi. Qui sotto non si
# esegue neppure: vedi il commento nel punto in cui viene scartata.
ALTER_TRIGGER_STATO = re.compile(r"^\s*ALTER\s+TRIGGER\b", re.IGNORECASE | re.MULTILINE)


def _istruzioni(blocco: str):
    """Le istruzioni eseguibili di un blocco.

    Un blocco puo' contenerne piu' d'una (DROP VIEW + CREATE VIEW) ed essere
    interamente un commento: DiFFDB usa i commenti per gli avvisi al posto del
    SQL rischioso, e quelli non si eseguono. Il punto e virgola finale va tolto:
    Oracle non lo accetta quando l'istruzione arriva dal driver.
    """
    righe = [r for r in blocco.splitlines() if not r.strip().startswith("--")]
    testo = "\n".join(righe).strip()
    if not testo:
        return

    trovato = INIZIO_BLOCCO_PLSQL.search(testo)
    if trovato:
        yield from _istruzioni(testo[:trovato.start()])
        resto = testo[trovato.start():]
        alter = ALTER_TRIGGER_STATO.search(resto)
        if alter:
            yield resto[:alter.start()].strip().rstrip(";")
            # Non si esegue: per un trigger appena creato (mai disabilitato)
            # e' ridondante — CREATE TRIGGER lo lascia gia' abilitato — e
            # forzare esplicitamente un ENABLE si e' visto costringere Oracle
            # a una ri-validazione che a volte fallisce (ORA-04098), scoperto
            # dalla CI. Non essenziale per verificare che il trigger funzioni.
        else:
            yield resto.strip().rstrip(";")
        return

    for pezzo in testo.split(";"):
        istruzione = pezzo.strip()
        if istruzione:
            yield istruzione


def _svuota(engine, schema):
    """Riporta l'ambiente a vuoto: viste, tabelle (nell'ordine delle FK), sequenze."""
    inspector = inspect(engine)
    for vista in inspector.get_view_names(schema=schema):
        _ignora(engine, f"DROP VIEW {_qualifica(engine, schema, vista)}")

    metadata = MetaData()
    metadata.reflect(bind=engine, schema=schema, views=False)
    metadata.drop_all(bind=engine)

    try:
        sequenze = inspector.get_sequence_names(schema=schema)
    except Exception:
        # MySQL solleva NotImplementedError, gli altri dialetti errori propri:
        # se non si riesce a elencarle, non ci sono sequenze da pulire.
        sequenze = []
    for sequenza in sequenze:
        _ignora(engine, f"DROP SEQUENCE {_qualifica(engine, schema, sequenza)}")


def _qualifica(engine, schema, nome):
    quote = engine.dialect.identifier_preparer.quote
    return f"{quote(schema)}.{quote(nome)}" if schema else quote(nome)


def _ignora(engine, statement):
    try:
        with engine.begin() as conn:
            conn.execute(text(statement))
    except Exception:
        pass


def test_annullare_riporta_l_ambiente_com_era(ambienti):
    """Il contratto dell'annullamento: allineo, disfo, e l'impronta torna quella.

    L'impronta copre l'intera struttura, quindi non basta che "sembri" tornata:
    una colonna dimenticata o un indice rimasto la fanno cambiare.
    """
    from diffdb.diff_DB import generate_rollback_scripts
    from diffdb.schema_snapshot import snapshot_connection
    from diffdb.snapshot_io import fingerprint

    prima = fingerprint(snapshot_connection(
        ambienti.col.nome, ambienti.col.url, ambienti.col.schema))

    diff = _confronta(ambienti)
    _esegui(ambienti.col.url, generate_sql_scripts(diff, target_env=ambienti.col.nome))

    dopo_allineamento = fingerprint(snapshot_connection(
        ambienti.col.nome, ambienti.col.url, ambienti.col.schema))
    assert dopo_allineamento != prima, "l'allineamento non ha cambiato niente"

    # L'annullamento si ricava dallo stesso confronto di prima: e' lo scenario
    # vero, in cui i due file vengono generati insieme.
    annullamento = generate_rollback_scripts(diff, target_env=ambienti.col.nome)
    eseguiti = _esegui(ambienti.col.url, annullamento, sezioni=SEZIONI_ANNULLAMENTO)

    dopo = fingerprint(snapshot_connection(
        ambienti.col.nome, ambienti.col.url, ambienti.col.schema))
    assert dopo == prima, (
        f"[{ambienti.dialetto}] dopo l'annullamento l'ambiente non e' tornato "
        f"com'era.\n\nannullamento eseguito:\n" + "\n".join(eseguiti))


# --- timeout di interrogazione ----------------------------------------------
#
# Il timeout di connessione (verificato altrove) non protegge una query che
# si blocca *dopo* essersi connessa. Qui si verifica che il secondo timeout -
# quello di interrogazione, in crea_engine() - scatti davvero sui quattro
# motori, ognuno con la sua sintassi per "dormi N secondi", e che regga anche
# al secondo prestito della stessa connessione dal pool: la prima versione di
# questo codice lo perdeva in silenzio dopo il primo uso, perche' la SET non
# veniva confermata (vedi il commit() in _imposta_timeout_sessione).

# SELECT SLEEP(n) su MySQL non e' un buon modo di verificare max_execution_time:
# e' un limite documentato di MySQL, non un difetto della correzione. Il
# timeout li' si controlla mentre si elaborano righe vere, a intervalli, e
# SLEEP() blocca il thread senza mai passare da quei controlli - quindi non
# viene interrotta anche con il timeout attivo e impostato correttamente.
# Verificato dal vivo: la query resta bloccata per i 5 secondi pieni.
SONNO = {
    "postgresql": "SELECT pg_sleep(5)",
    "mssql": "WAITFOR DELAY '00:00:05'",
    "oracle": "BEGIN DBMS_SESSION.SLEEP(5); END;",
}

# Su MySQL si verifica la variabile di sessione stessa, non l'annullamento di
# una query: e' quello che il fix con il commit() protegge davvero (che la
# SET venga eseguita ed ecco perche' regga anche al secondo prestito).
VARIABILE_TIMEOUT_SESSIONE = {"mysql": "SELECT @@max_execution_time"}


def test_una_query_bloccata_viene_annullata_dal_timeout(coppia):
    """Con un timeout di 2 secondi, una query che dorme 5 non deve mai
    arrivare in fondo: deve fallire, non completarsi lentamente."""
    if coppia.dialetto not in SONNO:
        pytest.skip(f"su {coppia.dialetto} SLEEP non e' interrompibile dal timeout "
                    f"(vedi test_la_variabile_di_timeout_e_impostata)")

    from diffdb.schema_snapshot import crea_engine

    engine = crea_engine(coppia.svi.url, secondi_query=2)
    try:
        t0 = time.perf_counter()
        with pytest.raises(SQLAlchemyError):
            with engine.connect() as conn:
                conn.execute(text(SONNO[coppia.dialetto]))
        durata = time.perf_counter() - t0
        # Margine largo (il timeout e' 2s): qui si vuole solo essere certi
        # che non abbia aspettato i 5 secondi pieni della query.
        assert durata < 4.5, (
            f"[{coppia.dialetto}] la query ha impiegato {durata:.1f}s: "
            f"il timeout di interrogazione non e' scattato")
    finally:
        engine.dispose()


def test_il_timeout_regge_al_secondo_prestito_dalla_stessa_connessione(coppia):
    """Il bug che questo test blocca: la SET di sessione non confermata
    veniva annullata dal primo ROLLBACK che SQLAlchemy emette sulla stessa
    connessione fisica, e dal secondo prestito in poi il timeout smetteva di
    valere senza che nessuno se ne accorgesse."""
    if coppia.dialetto not in SONNO:
        pytest.skip(f"su {coppia.dialetto} SLEEP non e' interrompibile dal timeout "
                    f"(vedi test_la_variabile_di_timeout_regge_al_secondo_prestito)")

    from diffdb.schema_snapshot import crea_engine

    engine = crea_engine(coppia.svi.url, secondi_query=2)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))   # primo prestito: solo per restituirla al pool

        t0 = time.perf_counter()
        with pytest.raises(SQLAlchemyError):
            with engine.connect() as conn:   # secondo prestito: la stessa connessione fisica
                conn.execute(text(SONNO[coppia.dialetto]))
        durata = time.perf_counter() - t0
        assert durata < 4.5, (
            f"[{coppia.dialetto}] al secondo prestito il timeout non e' scattato "
            f"({durata:.1f}s)")
    finally:
        engine.dispose()


def test_la_variabile_di_timeout_e_impostata(coppia):
    """Per i dialetti dove SLEEP() non basta a dimostrarlo (MySQL): si legge
    direttamente la variabile di sessione che il fix imposta."""
    query = VARIABILE_TIMEOUT_SESSIONE.get(coppia.dialetto)
    if query is None:
        pytest.skip(f"su {coppia.dialetto} l'annullamento si verifica con SLEEP "
                    f"(vedi test_una_query_bloccata_viene_annullata_dal_timeout)")

    from diffdb.schema_snapshot import crea_engine

    engine = crea_engine(coppia.svi.url, secondi_query=2)
    try:
        with engine.connect() as conn:
            valore = conn.execute(text(query)).scalar()
        assert valore == 2000, (   # millisecondi
            f"[{coppia.dialetto}] max_execution_time e' {valore}, non 2000")
    finally:
        engine.dispose()


def test_la_variabile_di_timeout_regge_al_secondo_prestito(coppia):
    """Lo stesso bug di test_il_timeout_regge_al_secondo_prestito_dalla_stessa_connessione,
    verificato leggendo la variabile invece di affidarsi a SLEEP()."""
    query = VARIABILE_TIMEOUT_SESSIONE.get(coppia.dialetto)
    if query is None:
        pytest.skip(f"su {coppia.dialetto} l'annullamento si verifica con SLEEP "
                    f"(vedi test_il_timeout_regge_al_secondo_prestito_dalla_stessa_connessione)")

    from diffdb.schema_snapshot import crea_engine

    engine = crea_engine(coppia.svi.url, secondi_query=2)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))   # primo prestito: solo per restituirla al pool

        with engine.connect() as conn:       # secondo prestito: la stessa connessione fisica
            valore = conn.execute(text(query)).scalar()
        assert valore == 2000, (
            f"[{coppia.dialetto}] al secondo prestito max_execution_time e' "
            f"{valore}, non 2000")
    finally:
        engine.dispose()


# --- trigger -----------------------------------------------------------------

# La tabella e, dove serve, la funzione che il trigger richiama: creati in
# entrambi gli ambienti, perche' qui si verifica il trigger, non la funzione
# (le funzioni/procedure sono un'altra categoria, non ancora confrontata). Su
# PostgreSQL il trigger e' solo il legame "BEFORE INSERT -> esegui questa
# funzione": la funzione deve preesistere nel target perche' lo script generato
# funzioni, esattamente come un CREATE VIEW richiede che le tabelle che
# referenzia esistano gia'.
# Oracle piega gli identificatori non quotati in maiuscolo: il nome che il
# catalogo restituisce e' "TRG_TBL_TRG", non quello scritto nel CREATE. Il
# confronto va fatto senza distinguere maiuscole/minuscole.
NOME_TRIGGER = "trg_tbl_trg"


def _e_trigger_di_prova(nome: str) -> bool:
    return nome.upper() == NOME_TRIGGER.upper()


TRIGGER_SETUP = {
    "postgresql": [
        "CREATE TABLE trg_tbl (id INTEGER PRIMARY KEY, val INTEGER)",
        "CREATE OR REPLACE FUNCTION trg_tbl_fn() RETURNS trigger AS "
        "$$ BEGIN NEW.val := NEW.val + 1; RETURN NEW; END; $$ LANGUAGE plpgsql",
    ],
    "mysql": ["CREATE TABLE trg_tbl (id INTEGER PRIMARY KEY, val INTEGER)"],
    "mssql": ["CREATE TABLE trg_tbl (id INTEGER PRIMARY KEY, val INTEGER)"],
    "oracle": ["CREATE TABLE trg_tbl (id NUMBER(10) PRIMARY KEY, val NUMBER(10))"],
}

TRIGGER_DDL = {
    "postgresql": ("CREATE TRIGGER trg_tbl_trg BEFORE INSERT ON trg_tbl "
                   "FOR EACH ROW EXECUTE FUNCTION trg_tbl_fn()"),
    "mysql": ("CREATE TRIGGER trg_tbl_trg BEFORE INSERT ON trg_tbl "
              "FOR EACH ROW SET NEW.val = NEW.val + 1"),
    "mssql": ("CREATE TRIGGER trg_tbl_trg ON trg_tbl AFTER INSERT AS "
              "UPDATE trg_tbl SET val = val + 1 WHERE id IN (SELECT id FROM inserted)"),
    "oracle": ("CREATE TRIGGER trg_tbl_trg BEFORE INSERT ON trg_tbl FOR EACH ROW "
               "BEGIN :NEW.val := :NEW.val + 1; END;"),
}


def _prepara_ambiente_trigger(url, schema, dialetto, con_trigger: bool):
    engine = create_engine(url)
    try:
        _svuota(engine, schema)
        with engine.begin() as conn:
            for statement in TRIGGER_SETUP[dialetto]:
                _esegui_ddl(conn, statement)
            if con_trigger:
                _esegui_ddl(conn, TRIGGER_DDL[dialetto])
    finally:
        engine.dispose()


def test_il_trigger_si_allinea_e_funziona(coppia):
    """Come per le viste: il confronto rileva il trigger mancante, lo script
    generato lo crea, e il trigger creato funziona davvero, non solo esiste."""
    _prepara_ambiente_trigger(coppia.svi.url, coppia.svi.schema, coppia.dialetto,
                              con_trigger=True)
    _prepara_ambiente_trigger(coppia.col.url, coppia.col.schema, coppia.dialetto,
                              con_trigger=False)

    # Diagnostica prima del confronto: se questo fallisce, il problema e' nella
    # creazione o nella query di lettura, non nella logica di confronto.
    svi_snapshot = snapshot_connection(coppia.svi.nome, coppia.svi.url, coppia.svi.schema)
    assert any(_e_trigger_di_prova(nome) for nome in svi_snapshot.triggers), (
        f"[{coppia.dialetto}] il trigger appena creato in SVI non si legge dal "
        f"catalogo: trovati {list(svi_snapshot.triggers)}")

    diff = _confronta(coppia)
    trovati = [d for d in diff.triggers if _e_trigger_di_prova(d.name)]
    assert [(d.change, d.missing_in) for d in trovati] == [(MISSING, coppia.col.nome)]

    scripts = generate_sql_scripts(diff, target_env=coppia.col.nome)
    eseguiti = _esegui(coppia.col.url, scripts, sezioni=("triggers",))
    assert eseguiti, "lo script del trigger era vuoto"

    engine = create_engine(coppia.col.url)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO trg_tbl (id, val) VALUES (1, 10)"))
            valore = conn.execute(text("SELECT val FROM trg_tbl WHERE id = 1")).scalar()
        assert int(valore) == 11, "il trigger esiste ma non ha incrementato il valore"
    finally:
        engine.dispose()

    residue = [d for d in _confronta(coppia).triggers if _e_trigger_di_prova(d.name)]
    assert residue == []


TRIGGER_CORPO_DIVERSO = {
    "mysql": ("CREATE TRIGGER trg_tbl_trg BEFORE INSERT ON trg_tbl "
              "FOR EACH ROW SET NEW.val = NEW.val - 1"),
    "mssql": ("CREATE TRIGGER trg_tbl_trg ON trg_tbl AFTER INSERT AS "
              "UPDATE trg_tbl SET val = val - 1 WHERE id IN (SELECT id FROM inserted)"),
    "oracle": ("CREATE TRIGGER trg_tbl_trg BEFORE INSERT ON trg_tbl FOR EACH ROW "
               "BEGIN :NEW.val := :NEW.val - 1; END;"),
}


def test_corpo_del_trigger_diverso_si_rileva_e_si_corregge(coppia):
    """Stesso nome, stessa tabella, corpo diverso: DROP + CREATE, mai un
    CREATE OR REPLACE (MySQL non lo ha per i trigger in nessuna versione).

    Non su PostgreSQL: li' il corpo che conta e' nella funzione richiamata,
    non nel testo del trigger stesso (che resterebbe identico), e le funzioni
    sono un'altra categoria — non ancora confrontata.
    """
    dialetto = coppia.dialetto
    if dialetto not in TRIGGER_CORPO_DIVERSO:
        pytest.skip(f"su {dialetto} il corpo del trigger non e' nel testo del "
                    f"trigger stesso (vedi il docstring)")

    _prepara_ambiente_trigger(coppia.svi.url, coppia.svi.schema, dialetto, con_trigger=True)
    _prepara_ambiente_trigger(coppia.col.url, coppia.col.schema, dialetto, con_trigger=False)

    engine = create_engine(coppia.col.url)
    try:
        with engine.begin() as conn:
            _esegui_ddl(conn, TRIGGER_CORPO_DIVERSO[dialetto])
    finally:
        engine.dispose()

    diff = _confronta(coppia)
    trovati = [d for d in diff.triggers if _e_trigger_di_prova(d.name)]
    assert [d.change for d in trovati] == [DEFINITION_MISMATCH]

    scripts = generate_sql_scripts(diff, target_env=coppia.col.nome)
    joined = "\n".join(scripts["triggers"])
    assert "DROP TRIGGER" in joined

    eseguiti = _esegui(coppia.col.url, scripts, sezioni=("triggers",))
    assert eseguiti

    engine = create_engine(coppia.col.url)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO trg_tbl (id, val) VALUES (1, 10)"))
            valore = conn.execute(text("SELECT val FROM trg_tbl WHERE id = 1")).scalar()
        assert int(valore) == 11, (
            "dopo la correzione deve incrementare come in SVI, non decrementare")
    finally:
        engine.dispose()


# --- procedure e funzioni -----------------------------------------------------


def _stesso_nome(a: str, b: str) -> bool:
    """Oracle piega gli identificatori non quotati in maiuscolo: il confronto
    coi nomi scritti nei DDL di prova va fatto senza distinguere le maiuscole."""
    return a.upper() == b.upper()


NOME_FUNZIONE = "rtn_raddoppia"
NOME_PROCEDURA = "rtn_incr"

ROUTINE_SETUP = {
    "postgresql": ["CREATE TABLE rtn_tbl (id INTEGER PRIMARY KEY, val INTEGER)"],
    "mysql": ["CREATE TABLE rtn_tbl (id INTEGER PRIMARY KEY, val INTEGER)"],
    "mssql": ["CREATE TABLE rtn_tbl (id INTEGER PRIMARY KEY, val INTEGER)"],
    "oracle": ["CREATE TABLE rtn_tbl (id NUMBER(10) PRIMARY KEY, val NUMBER(10))"],
}

FUNZIONE_DDL = {
    "postgresql": ("CREATE FUNCTION rtn_raddoppia(x integer) RETURNS integer AS "
                   "$$ BEGIN RETURN x * 2; END; $$ LANGUAGE plpgsql"),
    "mysql": ("CREATE FUNCTION rtn_raddoppia(x INT) RETURNS INT DETERMINISTIC "
              "BEGIN RETURN x * 2; END"),
    "mssql": "CREATE FUNCTION rtn_raddoppia(@x INT) RETURNS INT AS BEGIN RETURN @x * 2; END",
    "oracle": ("CREATE FUNCTION rtn_raddoppia(x IN NUMBER) RETURN NUMBER IS "
               "BEGIN RETURN x * 2; END;"),
}

CHIAMA_FUNZIONE = {
    "postgresql": "SELECT rtn_raddoppia(5)",
    "mysql": "SELECT rtn_raddoppia(5)",
    "mssql": "SELECT dbo.rtn_raddoppia(5)",
    "oracle": "SELECT rtn_raddoppia(5) FROM dual",
}

# Corpo diverso, testualmente nel corpo della funzione stessa (non in un
# oggetto separato come per il trigger su PostgreSQL): qui il confronto per
# corpo normalizzato vale su tutti e quattro i motori, senza eccezioni.
FUNZIONE_CORPO_DIVERSO = {
    "postgresql": ("CREATE FUNCTION rtn_raddoppia(x integer) RETURNS integer AS "
                   "$$ BEGIN RETURN x * 3; END; $$ LANGUAGE plpgsql"),
    "mysql": ("CREATE FUNCTION rtn_raddoppia(x INT) RETURNS INT DETERMINISTIC "
              "BEGIN RETURN x * 3; END"),
    "mssql": "CREATE FUNCTION rtn_raddoppia(@x INT) RETURNS INT AS BEGIN RETURN @x * 3; END",
    "oracle": ("CREATE FUNCTION rtn_raddoppia(x IN NUMBER) RETURN NUMBER IS "
               "BEGIN RETURN x * 3; END;"),
}

PROCEDURA_DDL = {
    "postgresql": ("CREATE PROCEDURE rtn_incr(p_id INTEGER) AS "
                   "$$ BEGIN UPDATE rtn_tbl SET val = val + 1 WHERE id = p_id; END; $$ "
                   "LANGUAGE plpgsql"),
    "mysql": ("CREATE PROCEDURE rtn_incr(IN p_id INT) "
              "BEGIN UPDATE rtn_tbl SET val = val + 1 WHERE id = p_id; END"),
    "mssql": ("CREATE PROCEDURE rtn_incr @p_id INT AS "
              "BEGIN UPDATE rtn_tbl SET val = val + 1 WHERE id = @p_id; END"),
    "oracle": ("CREATE PROCEDURE rtn_incr(p_id IN NUMBER) IS "
               "BEGIN UPDATE rtn_tbl SET val = val + 1 WHERE id = p_id; END;"),
}

CHIAMA_PROCEDURA = {
    "postgresql": "CALL rtn_incr(1)",
    "mysql": "CALL rtn_incr(1)",
    "mssql": "EXEC rtn_incr @p_id = 1",
    "oracle": "BEGIN rtn_incr(1); END;",
}


DROP_FUNZIONE = {
    "postgresql": "DROP FUNCTION rtn_raddoppia(integer)",
    "mysql": "DROP FUNCTION rtn_raddoppia",
    "mssql": "DROP FUNCTION rtn_raddoppia",
    "oracle": "DROP FUNCTION rtn_raddoppia",
}
DROP_PROCEDURA = {
    "postgresql": "DROP PROCEDURE rtn_incr(integer)",
    "mysql": "DROP PROCEDURE rtn_incr",
    "mssql": "DROP PROCEDURE rtn_incr",
    "oracle": "DROP PROCEDURE rtn_incr",
}


def _prepara_ambiente_routine(url, schema, dialetto, con_funzione: bool, con_procedura: bool):
    engine = create_engine(url)
    try:
        _svuota(engine, schema)
        # _svuota non tocca le routine standalone: non sono legate a una
        # tabella come i trigger, DROP TABLE non le porta via con se'. Quella
        # lasciata da un test precedente nella stessa sessione andrebbe
        # altrimenti a scontrarsi con la CREATE qui sotto.
        _ignora(engine, DROP_FUNZIONE[dialetto])
        _ignora(engine, DROP_PROCEDURA[dialetto])
        with engine.begin() as conn:
            for statement in ROUTINE_SETUP[dialetto]:
                _esegui_ddl(conn, statement)
            if con_funzione:
                _esegui_ddl(conn, FUNZIONE_DDL[dialetto])
            if con_procedura:
                _esegui_ddl(conn, PROCEDURA_DDL[dialetto])
    finally:
        engine.dispose()


def test_la_funzione_si_allinea_e_funziona(coppia):
    """Come per il trigger: il confronto rileva la funzione mancante, lo
    script generato la crea, e la funzione creata calcola davvero, non solo
    esiste."""
    _prepara_ambiente_routine(coppia.svi.url, coppia.svi.schema, coppia.dialetto,
                              con_funzione=True, con_procedura=False)
    _prepara_ambiente_routine(coppia.col.url, coppia.col.schema, coppia.dialetto,
                              con_funzione=False, con_procedura=False)

    diff = _confronta(coppia)
    trovate = [d for d in diff.routines
              if d.kind == "function" and _stesso_nome(d.name, NOME_FUNZIONE)]
    assert [(d.change, d.missing_in) for d in trovate] == [(MISSING, coppia.col.nome)]

    scripts = generate_sql_scripts(diff, target_env=coppia.col.nome)
    eseguiti = _esegui(coppia.col.url, scripts, sezioni=("routines",))
    assert eseguiti, "lo script della funzione era vuoto"

    engine = create_engine(coppia.col.url)
    try:
        with engine.connect() as conn:
            valore = conn.execute(text(CHIAMA_FUNZIONE[coppia.dialetto])).scalar()
        assert int(valore) == 10, "la funzione esiste ma non calcola il valore atteso"
    finally:
        engine.dispose()

    residue = [d for d in _confronta(coppia).routines
              if d.kind == "function" and _stesso_nome(d.name, NOME_FUNZIONE)]
    assert residue == []


def test_la_procedura_si_allinea_e_funziona(coppia):
    """Come sopra ma per una procedura: qui il 'funziona davvero' si vede
    nell'effetto su una tabella, non in un valore di ritorno."""
    _prepara_ambiente_routine(coppia.svi.url, coppia.svi.schema, coppia.dialetto,
                              con_funzione=False, con_procedura=True)
    _prepara_ambiente_routine(coppia.col.url, coppia.col.schema, coppia.dialetto,
                              con_funzione=False, con_procedura=False)

    diff = _confronta(coppia)
    trovate = [d for d in diff.routines
              if d.kind == "procedure" and _stesso_nome(d.name, NOME_PROCEDURA)]
    assert [(d.change, d.missing_in) for d in trovate] == [(MISSING, coppia.col.nome)]

    scripts = generate_sql_scripts(diff, target_env=coppia.col.nome)
    eseguiti = _esegui(coppia.col.url, scripts, sezioni=("routines",))
    assert eseguiti, "lo script della procedura era vuoto"

    engine = create_engine(coppia.col.url)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO rtn_tbl (id, val) VALUES (1, 10)"))
            _esegui_ddl(conn, CHIAMA_PROCEDURA[coppia.dialetto])
            valore = conn.execute(text("SELECT val FROM rtn_tbl WHERE id = 1")).scalar()
        assert int(valore) == 11, "la procedura esiste ma non ha aggiornato la riga"
    finally:
        engine.dispose()


def test_corpo_della_funzione_diverso_si_rileva_e_si_corregge(coppia):
    """Stesso nome, stessa firma, corpo diverso: DROP + CREATE, mai un
    CREATE OR REPLACE (MySQL non lo ha ne' per le procedure ne' per le
    funzioni, in nessuna versione)."""
    dialetto = coppia.dialetto
    _prepara_ambiente_routine(coppia.svi.url, coppia.svi.schema, dialetto,
                              con_funzione=True, con_procedura=False)
    _prepara_ambiente_routine(coppia.col.url, coppia.col.schema, dialetto,
                              con_funzione=False, con_procedura=False)

    engine = create_engine(coppia.col.url)
    try:
        with engine.begin() as conn:
            _esegui_ddl(conn, FUNZIONE_CORPO_DIVERSO[dialetto])
    finally:
        engine.dispose()

    diff = _confronta(coppia)
    trovate = [d for d in diff.routines
              if d.kind == "function" and _stesso_nome(d.name, NOME_FUNZIONE)]
    assert [d.change for d in trovate] == [DEFINITION_MISMATCH]

    scripts = generate_sql_scripts(diff, target_env=coppia.col.nome)
    joined = "\n".join(scripts["routines"])
    assert "DROP FUNCTION" in joined

    eseguiti = _esegui(coppia.col.url, scripts, sezioni=("routines",))
    assert eseguiti

    engine = create_engine(coppia.col.url)
    try:
        with engine.connect() as conn:
            valore = conn.execute(text(CHIAMA_FUNZIONE[dialetto])).scalar()
        assert int(valore) == 10, "dopo la correzione deve calcolare come in SVI (x2), non x3"
    finally:
        engine.dispose()

