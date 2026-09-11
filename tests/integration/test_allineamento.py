"""Il contratto di DiFFDB, verificato sui motori veri.

    confronta -> genera lo script -> lo esegue -> riconfronta -> nessuna differenza

E' lo stesso contratto dei test su SQLite, ma qui a rispondere sono PostgreSQL,
MySQL, SQL Server e Oracle: e' l'unico modo per sapere che il DDL che generiamo
per Oracle e' davvero accettato da Oracle, invece di limitarci a sperarlo.

Ogni dialetto viene saltato se la sua variabile d'ambiente non e' impostata
(vedi conftest.py), quindi la suite si puo' lanciare anche su un dialetto solo.
"""

import time

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from diffdb import snapshot_io
from diffdb.diff_DB import MISSING, TYPE_MISMATCH, compare_environments, generate_sql_scripts
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
SEZIONI_ALLINEAMENTO = ("sequences", "tables", "constraints", "views", "synonyms")
SEZIONI_ANNULLAMENTO = ("synonyms", "views", "constraints", "tables", "sequences")


def _esegui(url, scripts, sezioni=SEZIONI_ALLINEAMENTO):
    """Esegue lo script come lo eseguirebbe un DBA: nell'ordine del file."""
    eseguiti = []
    engine = create_engine(url)
    try:
        for sezione in sezioni:
            for blocco in scripts.get(sezione, []):
                for statement in _istruzioni(blocco):
                    with engine.begin() as conn:
                        conn.execute(text(statement))
                    eseguiti.append(statement)
    finally:
        engine.dispose()
    return eseguiti


def _istruzioni(blocco: str):
    """Le istruzioni eseguibili di un blocco.

    Un blocco puo' contenerne piu' d'una (DROP VIEW + CREATE VIEW) ed essere
    interamente un commento: DiFFDB usa i commenti per gli avvisi al posto del
    SQL rischioso, e quelli non si eseguono. Il punto e virgola finale va tolto:
    Oracle non lo accetta quando l'istruzione arriva dal driver.
    """
    for pezzo in blocco.split(";"):
        righe = [r for r in pezzo.splitlines() if not r.strip().startswith("--")]
        istruzione = "\n".join(righe).strip()
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

