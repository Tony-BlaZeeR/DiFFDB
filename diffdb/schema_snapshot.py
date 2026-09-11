"""Fotografia della struttura di un database.

Riflette lo schema con SQLAlchemy e conserva gli oggetti Table riflessi: servono
a generare DDL reale (CREATE TABLE, CREATE INDEX, ADD CONSTRAINT) invece di
segnaposto. Sequenze e sinonimi si leggono dai cataloghi di sistema, perche'
SQLAlchemy non li espone in modo uniforme.
"""

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import (
    CheckConstraint,
    MetaData,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from diffdb.rules import NESSUNA, Regole
from diffdb.urls import expand  # noqa: F401  (ri-esportata: la usa anche diff_DB)

logger = logging.getLogger(__name__)

# pymssql (il driver usato per SQL Server) non implementa la lettura dei
# vincoli CHECK: Dialect.get_check_constraints() solleva NotImplementedError
# per l'intera gerarchia del dialetto MSSQL in SQLAlchemy 2.0. Non e' un
# problema di sintassi ne' di permessi, e' proprio assente — verificato
# leggendo il codice del dialetto prima di scrivere questa query, dopo che la
# CI aveva mostrato zero vincoli CHECK su un ambiente che ne aveva uno vero.
# PostgreSQL, MySQL e Oracle lo leggono gia' da soli via reflect().
MSSQL_CHECK_QUERY = (
    "SELECT t.name AS table_name, cc.name, cc.definition "
    "FROM sys.check_constraints cc "
    "JOIN sys.tables t ON cc.parent_object_id = t.object_id "
    "WHERE SCHEMA_NAME(t.schema_id) = COALESCE(:schema, SCHEMA_NAME())"
)

# Trigger: nessun dialetto li riflette via SQLAlchemy (l'Inspector non ha
# nemmeno un get_trigger_names). Dove il motore sa ricostruire il CREATE
# TRIGGER completo lo si usa (pg_get_triggerdef, DBMS_METADATA.GET_DDL,
# sys.sql_modules): il testo che ne esce e' gia' eseguibile com'e', come per
# le viste. MySQL non ha un equivalente: si ricostruisce con SHOW CREATE
# TRIGGER, un'interrogazione per trigger (vedi _fetch_mysql_triggers) — lo
# stesso compromesso gia' accettato per i CHECK su SQL Server.
#
# Su Oracle ci si ferma ai trigger su tabella (base_object_type = 'TABLE'):
# quelli su vista (INSTEAD OF) sono rari e restano fuori. Su PostgreSQL un
# nome di trigger e' unico per tabella, non per schema: due tabelle diverse
# possono avere un trigger con lo stesso nome, e qui si confondono nello
# stesso dizionario. Limite noto, non risolto: e' lo stesso compromesso della
# chiave per nome usato per viste, sequenze e sinonimi.
TRIGGER_QUERIES = {
    "postgresql": (
        "SELECT t.tgname, c.relname, pg_get_triggerdef(t.oid) "
        "FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE NOT t.tgisinternal "
        "AND n.nspname = COALESCE(:schema, current_schema())"
    ),
    "oracle": (
        "SELECT trigger_name, table_name, "
        "DBMS_METADATA.GET_DDL('TRIGGER', trigger_name, owner) "
        "FROM all_triggers WHERE owner = NVL(:schema, USER) AND base_object_type = 'TABLE'"
    ),
    "mssql": (
        "SELECT tr.name, OBJECT_NAME(tr.parent_id), sm.definition "
        "FROM sys.triggers tr "
        "JOIN sys.sql_modules sm ON sm.object_id = tr.object_id "
        "WHERE tr.parent_class = 1 "  # 1 = trigger DML su tabella/vista, non su DB/server
        "AND OBJECT_SCHEMA_NAME(tr.parent_id) = COALESCE(:schema, SCHEMA_NAME())"
    ),
    "sqlite": "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'",
}

# I sinonimi esistono solo su Oracle e SQL Server.
SYNONYM_QUERIES = {
    "oracle": (
        "SELECT synonym_name, table_owner || '.' || table_name AS target "
        "FROM all_synonyms WHERE owner = NVL(:schema, USER)"
    ),
    "mssql": "SELECT name, base_object_name FROM sys.synonyms",
}

# Valori reali delle sequenze: senza questi si ricreerebbero tutte con START WITH 1.
SEQUENCE_QUERIES = {
    "postgresql": (
        "SELECT sequencename, start_value, increment_by, min_value, max_value, cycle "
        "FROM pg_sequences WHERE schemaname = COALESCE(:schema, current_schema())"
    ),
    "oracle": (
        "SELECT sequence_name, last_number, increment_by, min_value, max_value, "
        "CASE WHEN cycle_flag = 'Y' THEN 1 ELSE 0 END "
        "FROM all_sequences WHERE sequence_owner = NVL(:schema, USER)"
    ),
    "mssql": (
        "SELECT name, CAST(start_value AS BIGINT), CAST(increment AS BIGINT), "
        "CAST(minimum_value AS BIGINT), CAST(maximum_value AS BIGINT), "
        "CAST(is_cycling AS INT) FROM sys.sequences"
    ),
}


@dataclass
class SequenceSpec:
    name: str
    start: int = 1
    increment: int = 1
    minvalue: int | None = None
    maxvalue: int | None = None
    cycle: bool = False

    def signature(self) -> str:
        return f"START {self.start} INCREMENT {self.increment} CYCLE {int(self.cycle)}"


@dataclass
class TriggerSpec:
    """Un trigger: la definizione e' gia' un CREATE TRIGGER completo ed
    eseguibile nel dialetto di provenienza. La tabella serve a parte perche'
    PostgreSQL la richiede nel DROP TRIGGER (`DROP TRIGGER nome ON tabella`),
    a differenza degli altri motori."""

    name: str
    table: str | None
    definition: str


@dataclass
class Snapshot:
    """Struttura di un ambiente in un dato momento."""

    env_name: str
    dialect: str
    schema: str | None = None
    dialect_impl: object = None  # engine.dialect: serve a compilare il DDL
    metadata: MetaData = field(default_factory=MetaData)
    views: dict[str, str] = field(default_factory=dict)        # nome -> definizione
    sequences: dict[str, SequenceSpec] = field(default_factory=dict)
    synonyms: dict[str, str] = field(default_factory=dict)     # nome -> oggetto puntato
    triggers: dict[str, TriggerSpec] = field(default_factory=dict)
    regole: Regole = field(default_factory=Regole)

    @property
    def tables(self) -> dict[str, object]:
        """Le sole tabelle che le regole includono.

        Il filtro va ripetuto qui e non solo prima della riflessione: SQLAlchemy
        riflette comunque le tabelle referenziate da una foreign key, anche se
        escluse. Averle nel metadata serve a compilare il DDL dei vincoli;
        confrontarle no.
        """
        return {t.name: t for t in self.metadata.tables.values()
                if self.regole.tabella_inclusa(t.name)}

    def table(self, name: str):
        return self.tables.get(name)

    def columns(self, table_name: str) -> dict[str, object]:
        table = self.table(table_name)
        return {} if table is None else {c.name: c for c in table.columns}

    def indexes(self, table_name: str) -> dict[str, object]:
        """Indici per firma (colonne + unicita'), non per nome: i nomi cambiano."""
        table = self.table(table_name)
        return {} if table is None else {index_signature(i): i for i in table.indexes}

    def foreign_keys(self, table_name: str) -> dict[str, object]:
        table = self.table(table_name)
        if table is None:
            return {}
        return {fk_signature(fk): fk for fk in table.foreign_key_constraints}

    def unique_constraints(self, table_name: str) -> dict[str, object]:
        table = self.table(table_name)
        if table is None:
            return {}
        return {
            unique_signature(c): c
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }

    def check_constraints(self, table_name: str) -> dict[str, object]:
        """Vincoli CHECK, per condizione normalizzata (i nomi sono spesso
        autogenerati dal motore e cambiano da un ambiente all'altro).

        Su SQLite la riflessione e' inaffidabile anche con un solo vincolo: il
        testo esce con una parentesi di troppo, e con due vincoli SQLAlchemy ne
        fonde i nomi. Meglio dichiarare la categoria assente che confrontare un
        testo che il motore stesso ha già rovinato in lettura.
        """
        if self.dialect == "sqlite":
            return {}
        table = self.table(table_name)
        if table is None:
            return {}
        return {
            check_signature(c): c
            for c in table.constraints
            if isinstance(c, CheckConstraint)
        }

    def primary_key(self, table_name: str):
        table = self.table(table_name)
        if table is None:
            return ()
        return tuple(c.name for c in table.primary_key.columns)


def take_snapshot(env_name: str, engine: Engine, schema: str | None = None,
                  regole: Regole = NESSUNA) -> Snapshot:
    snapshot = Snapshot(
        env_name=env_name,
        dialect=engine.dialect.name,
        schema=schema,
        dialect_impl=engine.dialect,
        regole=regole,
    )

    inspector = inspect(engine)

    # Le tabelle si filtrano *prima* di rifletterle: su uno schema grande la
    # riflessione e' quasi tutto il tempo del confronto, e quella che non
    # guardiamo non ha senso leggerla.
    nomi = [n for n in inspector.get_table_names(schema=schema)
            if regole.tabella_inclusa(n)]
    if nomi:
        snapshot.metadata.reflect(bind=engine, schema=schema, views=False, only=nomi)

    if engine.dialect.name == "mssql":
        _fetch_mssql_check_constraints(engine, schema, snapshot.metadata)

    if regole.categoria_inclusa("views"):
        for view in inspector.get_view_names(schema=schema):
            if not regole.vista_inclusa(view):
                continue
            try:
                snapshot.views[view] = inspector.get_view_definition(view, schema=schema) or ""
            except (NotImplementedError, SQLAlchemyError) as exc:
                logger.warning("Definizione della vista '%s' non leggibile: %s", view, exc)
                snapshot.views[view] = ""

    if regole.categoria_inclusa("sequences"):
        snapshot.sequences = {
            nome: spec for nome, spec in _fetch_sequences(engine, schema, inspector).items()
            if regole.sequenza_inclusa(nome)}
    if regole.categoria_inclusa("synonyms"):
        snapshot.synonyms = {
            nome: bersaglio for nome, bersaglio in _fetch_synonyms(engine, schema).items()
            if regole.sinonimo_incluso(nome)}
    if regole.categoria_inclusa("triggers"):
        snapshot.triggers = _fetch_triggers(engine, schema)

    logger.info(
        "Struttura di '%s' letta: %d tabelle, %d viste, %d sequenze, %d sinonimi, %d trigger.",
        env_name, len(snapshot.tables), len(snapshot.views),
        len(snapshot.sequences), len(snapshot.synonyms), len(snapshot.triggers))
    return snapshot


@dataclass
class EsitoConnessione:
    """Cosa si e' visto collegandosi. Dati grezzi: il messaggio lo compone la GUI,
    che e' l'unica a sapere in che lingua parlare all'utente."""

    dialetto: str
    versione: str
    tabelle: int
    schema: str | None = None
    schema_trovato: bool | None = None   # None: non richiesto o non verificabile


def verifica_connessione(env_name: str, conn_str: str,
                         schema: str | None = None) -> EsitoConnessione:
    """Prova a collegarsi e riferisce cosa ha trovato.

    Guarda anche se lo schema indicato esiste davvero: sbagliarlo e' l'errore
    piu' comune, e senza questo controllo si manifesta molto piu' tardi come un
    confronto che non trova nessuna tabella.
    """
    engine = crea_engine(conn_str, env_name)
    try:
        with engine.connect() as conn:
            versione = ".".join(str(p) for p in (conn.dialect.server_version_info or ()))

        inspector = inspect(engine)
        schema_trovato = None
        if schema:
            try:
                schema_trovato = schema in inspector.get_schema_names()
            except (NotImplementedError, SQLAlchemyError) as exc:
                logger.debug("Elenco degli schemi non disponibile: %s", exc)

        return EsitoConnessione(
            dialetto=engine.dialect.name,
            versione=versione or "?",
            tabelle=len(inspector.get_table_names(schema=schema)),
            schema=schema,
            schema_trovato=schema_trovato,
        )
    finally:
        engine.dispose()


# Quanto aspettare che un host risponda. Senza, si eredita il timeout di sistema
# su TCP, che puo' essere di minuti: un host sbagliato blocca tutto e non c'e'
# modo di accorgersene.
SECONDI_CONNESSIONE = 15

# Il nome del parametro di timeout cambia da driver a driver.
TIMEOUT_PER_DRIVER = {
    "psycopg2": "connect_timeout",
    "pymysql": "connect_timeout",
    "mysqldb": "connect_timeout",
    "pymssql": "login_timeout",
    "oracledb": "tcp_connect_timeout",
    "cx_oracle": "tcp_connect_timeout",
}


def connect_args_per(url, secondi: int = SECONDI_CONNESSIONE) -> dict:
    """Argomenti di connessione per il driver di questo URL.

    Il nome del parametro di timeout cambia da driver a driver, e passarne uno
    che il driver non conosce e' un errore: quindi si sceglie, non si tenta.
    """
    parametro = TIMEOUT_PER_DRIVER.get(make_url(url).get_driver_name())
    return {parametro: secondi} if parametro and secondi else {}


# Il timeout di connessione non protegge da una query che si blocca *dopo*
# essersi connessa: uno schema enorme, un lock su una tabella di sistema, una
# scansione lenta. Serve un secondo timeout, per l'interrogazione — pensato
# per non far restare bloccata una pipeline che nessuno sta guardando, non per
# tagliare corto su uno schema legittimamente grande.
#
# Ogni motore lo espone in un modo diverso, e non sempre come sembra:
#
# - pymssql ha un vero timeout per chiamata come argomento di *connessione*
#   (in secondi) - verificato dal vivo su SQL Server.
# - oracledb ha lo stesso concetto, in millisecondi, ma come *proprieta' della
#   connessione* da impostare dopo essersi connessi, non come argomento di
#   connect(): passarlo a connect_args solleva TypeError. Sbagliato al primo
#   tentativo, corretto dopo che la CI l'ha mostrato su Oracle vero.
# - PostgreSQL e MySQL non hanno ne' l'uno ne' l'altro: e' una variabile di
#   sessione (SET statement_timeout / SET SESSION max_execution_time), da
#   impostare a ogni nuova connessione *fisica* - per questo si usa l'evento
#   "connect" di SQLAlchemy, non un'istruzione a mano dopo la connessione.
#
# SQLite resta fuori: non essendo in rete, una query che "si blocca" e' quasi
# sempre un file bloccato da un altro processo, un concetto diverso (e con un
# timeout diverso, sqlite3.connect(timeout=...)) da quello che si vuole qui.
SECONDI_QUERY = 60

QUERY_TIMEOUT_CONNECT_ARG = {
    "pymssql": ("timeout", 1),   # secondi, argomento di connect()
}

QUERY_TIMEOUT_ATTRIBUTO = {
    "oracledb": ("call_timeout", 1000),   # millisecondi, proprieta' post-connessione
}

QUERY_TIMEOUT_SESSION_SQL = {
    "psycopg2": "SET statement_timeout = {ms}",
    "pymysql": "SET SESSION max_execution_time = {ms}",
}


def crea_engine(conn_str: str, env_name: str | None = None,
                secondi: int = SECONDI_CONNESSIONE,
                secondi_query: int = SECONDI_QUERY):
    """Engine con timeout di connessione, di interrogazione, e controllo
    della connessione morta."""
    url = make_url(expand(conn_str, name=env_name))
    driver = url.get_driver_name()
    connect_args = connect_args_per(url, secondi)

    if secondi_query and driver in QUERY_TIMEOUT_CONNECT_ARG:
        nome, unita = QUERY_TIMEOUT_CONNECT_ARG[driver]
        connect_args[nome] = secondi_query * unita

    # pool_pre_ping: una connessione chiusa dal server mentre era nel pool
    # verrebbe usata lo stesso, e fallirebbe con un errore incomprensibile.
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)

    if secondi_query and driver in QUERY_TIMEOUT_ATTRIBUTO:
        attributo, unita = QUERY_TIMEOUT_ATTRIBUTO[driver]
        valore = secondi_query * unita

        def _imposta_timeout_attributo(dbapi_connection, connection_record):
            # Una proprieta' Python sul wrapper del driver, non un comando SQL:
            # nessun round-trip al server, nessun commit da fare.
            setattr(dbapi_connection, attributo, valore)

        event.listen(engine, "connect", _imposta_timeout_attributo)

    comando_sessione = QUERY_TIMEOUT_SESSION_SQL.get(driver)
    if secondi_query and comando_sessione:
        istruzione = comando_sessione.format(ms=secondi_query * 1000)

        def _imposta_timeout_sessione(dbapi_connection, connection_record):
            cursore = dbapi_connection.cursor()
            try:
                cursore.execute(istruzione)
                # Senza commit il SET resta in una transazione implicita mai
                # confermata: il primo ROLLBACK che SQLAlchemy emette su
                # questa stessa connessione (al rientro nel pool, o
                # sull'autobegin del turno successivo) lo annulla in
                # silenzio, e il timeout smette di valere dalla seconda
                # query in poi. Verificato dal vivo: SHOW statement_timeout
                # tornava a 0 al secondo prestito della stessa connessione.
                dbapi_connection.commit()
            finally:
                cursore.close()

        event.listen(engine, "connect", _imposta_timeout_sessione)

    return engine


class Annullabile:
    """Tiene gli engine aperti per poterli chiudere da un altro thread.

    Non esiste un modo pulito di interrompere una riflessione in corso: quello
    che si puo' fare e' chiudere il pool, che chiude le connessioni sottostanti
    e fa fallire la query in attesa. Da li' in poi il thread esce da solo.
    """

    def __init__(self):
        self._engines = []
        self.annullato = False

    def registra(self, engine):
        self._engines.append(engine)
        if self.annullato:      # annullato mentre si apriva la connessione
            engine.dispose()

    def annulla(self):
        self.annullato = True
        for engine in list(self._engines):
            try:
                engine.dispose()
            except Exception as exc:          # pragma: no cover - dipende dal driver
                logger.debug("Chiusura dell'engine fallita: %s", exc)


def snapshot_connection(env_name: str, conn_str: str, schema: str | None = None,
                        regole: Regole = NESSUNA,
                        annullabile: Annullabile | None = None) -> Snapshot:
    """Fotografia di un ambiente a partire dalla sua connection string."""
    engine = crea_engine(conn_str, env_name)
    if annullabile is not None:
        annullabile.registra(engine)
    try:
        return take_snapshot(env_name, engine, schema, regole)
    finally:
        engine.dispose()


def _fetch_mssql_check_constraints(engine: Engine, schema: str | None, metadata: MetaData) -> None:
    """Aggiunge i vincoli CHECK alle tabelle gia' riflesse.

    Modifica `metadata` sul posto: aggiunge un CheckConstraint vero a ogni
    Table che SQLAlchemy ha gia' costruito, cosi' tutto il resto del codice
    (confronto, generazione del DDL, annullamento, round-trip su file) continua
    a funzionare senza saperlo — vede lo stesso genere di oggetto che ottiene
    da PostgreSQL, MySQL e Oracle via reflect() diretto.
    """
    try:
        with engine.connect() as conn:
            righe = conn.execute(text(MSSQL_CHECK_QUERY), {"schema": schema})
            for nome_tabella, nome_vincolo, definizione in righe:
                chiave = f"{schema}.{nome_tabella}" if schema else nome_tabella
                tabella = metadata.tables.get(chiave)
                if tabella is None:
                    continue   # tabella esclusa dalle regole, o non filtrata
                tabella.append_constraint(CheckConstraint(definizione, name=nome_vincolo))
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei vincoli CHECK di SQL Server fallita: %s", exc)


def _fetch_sequences(engine, schema, inspector) -> dict[str, SequenceSpec]:
    """Sequenze con i valori reali; se il catalogo non risponde, almeno i nomi."""
    query = SEQUENCE_QUERIES.get(engine.dialect.name)
    if query:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query), {"schema": schema})
                return {
                    row[0]: SequenceSpec(
                        name=row[0],
                        start=int(row[1] or 1),
                        increment=int(row[2] or 1),
                        minvalue=None if row[3] is None else int(row[3]),
                        maxvalue=None if row[4] is None else int(row[4]),
                        cycle=bool(row[5]),
                    )
                    for row in rows
                }
        except SQLAlchemyError as exc:
            logger.warning("Lettura dei valori delle sequenze fallita: %s", exc)

    try:
        return {n: SequenceSpec(name=n) for n in inspector.get_sequence_names(schema=schema)}
    except (NotImplementedError, SQLAlchemyError) as exc:
        logger.info("Sequenze non supportate su %s: %s", engine.dialect.name, exc)
        return {}


def _fetch_synonyms(engine: Engine, schema: str | None) -> dict[str, str]:
    query = SYNONYM_QUERIES.get(engine.dialect.name)
    if query is None:
        return {}

    try:
        with engine.connect() as conn:
            params = {"schema": schema} if ":schema" in query else {}
            return {row[0]: row[1] for row in conn.execute(text(query), params)}
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei sinonimi fallita: %s", exc)
        return {}


def _leggi_clob(valore) -> str:
    """DBMS_METADATA.GET_DDL torna un CLOB: a seconda della dimensione e della
    configurazione del driver puo' arrivare come str o come oggetto LOB da
    leggere esplicitamente. Non verificabile in locale (nessuna istanza
    Oracle): gestisce entrambi i casi invece di assumere quale capiti."""
    return valore.read() if hasattr(valore, "read") else (valore or "")


def _fetch_triggers(engine: Engine, schema: str | None) -> dict[str, TriggerSpec]:
    """Trigger completi. Il testo catturato e' gia' un CREATE TRIGGER
    eseguibile nel dialetto di provenienza: la generazione dello script lo
    riusa com'e', come per le viste."""
    dialetto = engine.dialect.name
    if dialetto == "mysql":
        return _fetch_mysql_triggers(engine, schema)

    query = TRIGGER_QUERIES.get(dialetto)
    if query is None:
        return {}

    try:
        with engine.connect() as conn:
            params = {"schema": schema} if ":schema" in query else {}
            righe = conn.execute(text(query), params).fetchall()
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei trigger fallita: %s", exc)
        return {}

    return {
        nome: TriggerSpec(name=nome, table=tabella, definition=_leggi_clob(definizione))
        for nome, tabella, definizione in righe
    }


def _fetch_mysql_triggers(engine: Engine, schema: str | None) -> dict[str, TriggerSpec]:
    """MySQL non ha un equivalente di pg_get_triggerdef: SHOW CREATE TRIGGER
    da' il testo completo, ma un'interrogazione per trigger, non una sola per
    tutto lo schema (lo stesso compromesso gia' accettato per i CHECK di SQL
    Server)."""
    quote = engine.dialect.identifier_preparer.quote
    try:
        with engine.connect() as conn:
            nomi = conn.execute(text(
                "SELECT trigger_name, event_object_table FROM information_schema.triggers "
                "WHERE trigger_schema = COALESCE(:schema, DATABASE())"
            ), {"schema": schema}).fetchall()

            triggers = {}
            for nome, tabella in nomi:
                # SHOW CREATE non accetta parametri bind: il nome viene dal
                # catalogo del motore stesso, ma si quota comunque per correttezza.
                riga = conn.execute(text(f"SHOW CREATE TRIGGER {quote(nome)}")).fetchone()
                triggers[nome] = TriggerSpec(name=nome, table=tabella, definition=riga[2])
            return triggers
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei trigger fallita: %s", exc)
        return {}


def type_signature(column) -> str:
    """Firma del tipo, confrontabile fra ambienti (VARCHAR(50), INTEGER, ...)."""
    return str(column.type).upper()


def index_signature(index) -> str:
    columns = ",".join(c.name for c in index.columns)
    return f"{'UNIQUE ' if index.unique else ''}({columns})"


def fk_signature(fk) -> str:
    """Identifica una FK dalle colonne, non dal nome: i nomi autogenerati cambiano."""
    columns = ",".join(c.name for c in fk.columns)
    targets = ",".join(e.target_fullname for e in fk.elements)
    return f"({columns}) -> ({targets})"


def unique_signature(constraint) -> str:
    return "(" + ",".join(c.name for c in constraint.columns) + ")"


_WS = re.compile(r"\s+")


def normalize_sql(sql) -> str:
    """Normalizza per il confronto: spazi collassati, minuscolo, parentesi e
    apici esterni rimossi. I database riformattano viste, default e check
    (SQL Server incapsula i default in doppie parentesi), quindi il confronto
    testuale grezzo darebbe falsi positivi."""
    sql = str(sql) if sql is not None else ""
    if not sql:
        return ""
    normalized = _WS.sub(" ", sql).strip().lower().rstrip(";").strip()
    while len(normalized) >= 2 and normalized[0] in "('" and normalized[-1] in ")'":
        inner = normalized[1:-1].strip()
        if not inner:
            break
        normalized = inner
    return normalized


def check_signature(constraint) -> str:
    """La condizione normalizzata, non il nome: i nomi dei CHECK sono spesso
    autogenerati dal motore (es. 'clienti_saldo_check' su PostgreSQL) e
    cambiano da un ambiente all'altro anche quando il vincolo e' lo stesso."""
    return normalize_sql(getattr(constraint, "sqltext", constraint))
