"""Ambienti reali per i test di integrazione.

I test unitari girano su SQLite: veloci, ma quattro dei cinque dialetti
supportati non li tocca nessuno. Qui si parla con i motori veri.

Ogni dialetto si attiva impostando la sua variabile d'ambiente; se manca, i
test di quel dialetto vengono saltati invece di fallire. La CI le imposta tutte
(vedi .github/workflows/ci.yml), in locale se ne imposta una alla volta:

    DIFFDB_TEST_POSTGRESQL_URL=postgresql+psycopg2://postgres:pw@localhost:5432/postgres
    DIFFDB_TEST_MYSQL_URL=mysql+pymysql://root:pw@localhost:3306/mysql
    DIFFDB_TEST_MSSQL_URL=mssql+pymssql://sa:pw@localhost:1433/master
    DIFFDB_TEST_ORACLE_URL=oracle+oracledb://system:pw@localhost:1521/?service_name=FREEPDB1

L'URL punta a un database *amministrativo*: i due ambienti da confrontare
vengono creati e distrutti dai test (database separati, utenti separati su
Oracle), quindi nessun dato preesistente viene toccato.
"""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)

VARIABILI = {
    "postgresql": "DIFFDB_TEST_POSTGRESQL_URL",
    "mysql": "DIFFDB_TEST_MYSQL_URL",
    "mssql": "DIFFDB_TEST_MSSQL_URL",
    "oracle": "DIFFDB_TEST_ORACLE_URL",
}

# Prefisso riconoscibile: qualunque cosa creino i test si distingue a colpo
# d'occhio da un database vero, e la pulizia non puo' colpire altro.
PREFISSO = "diffdb_test"
PASSWORD_ORACLE = "diffdb_test_pw1"


@dataclass
class Ambiente:
    """Un ambiente da confrontare: quello che DiFFDB chiama connessione."""

    nome: str
    url: str
    schema: str | None = None


@dataclass
class Coppia:
    dialetto: str
    svi: Ambiente
    col: Ambiente


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: richiede un database vero")


# In CI saltare non e' accettabile: un job verde che non ha eseguito niente e'
# peggio di uno rosso, perche' sembra una conferma. Con questa variabile un
# dialetto non raggiungibile fa fallire invece di saltare.
RIGOROSO = "DIFFDB_TEST_STRICT"


def _manca(messaggio: str):
    """Salta in locale, fallisce in CI."""
    if os.environ.get(RIGOROSO, "").strip().lower() in ("1", "true", "si", "yes"):
        pytest.fail(f"{messaggio} ({RIGOROSO} e' attiva: qui saltare non e' ammesso)")
    pytest.skip(messaggio)


@pytest.fixture(scope="session", params=sorted(VARIABILI), ids=sorted(VARIABILI))
def coppia(request):
    """Due ambienti vuoti e isolati sul dialetto richiesto."""
    dialetto = request.param
    variabile = VARIABILI[dialetto]
    url = os.environ.get(variabile)
    if not url:
        _manca(f"{variabile} non impostata: {dialetto} non viene testato")

    admin = create_engine(url)
    try:
        _verifica_raggiungibile(admin, variabile)
        if dialetto == "oracle":
            svi, col = _crea_utenti(admin, url)
        else:
            svi, col = _crea_database(admin, url, dialetto)
        yield Coppia(dialetto, svi, col)
    finally:
        try:
            if dialetto == "oracle":
                _elimina_utenti(admin)
            else:
                _elimina_database(admin, dialetto)
        except Exception as exc:  # la pulizia non deve mai mascherare il vero errore
            logger.warning("Pulizia di %s non riuscita: %s", dialetto, exc)
        admin.dispose()


def _verifica_raggiungibile(engine, variabile):
    try:
        with engine.connect() as conn:
            prova = "SELECT 1 FROM dual" if engine.dialect.name == "oracle" else "SELECT 1"
            conn.execute(text(prova))
    except Exception as exc:
        # In locale la variabile puo' essere rimasta impostata da un'altra
        # sessione e non deve far fallire la suite; in CI invece si.
        _manca(f"{variabile} impostata ma il server non risponde: {exc}")


# --- database separati (PostgreSQL, MySQL, SQL Server) ---------------------


def _crea_database(admin, url, dialetto):
    ambienti = []
    for suffisso in ("svi", "col"):
        nome = f"{PREFISSO}_{suffisso}"
        _autocommit(admin, _drop_database(dialetto, nome))
        _autocommit(admin, f"CREATE DATABASE {nome}")
        ambienti.append(Ambiente(nome=suffisso.upper(), url=_url(url, database=nome)))
    return ambienti


def _elimina_database(admin, dialetto):
    for suffisso in ("svi", "col"):
        _autocommit(admin, _drop_database(dialetto, f"{PREFISSO}_{suffisso}"), ignora=True)


def _drop_database(dialetto, nome) -> str:
    if dialetto == "mssql":
        # Senza SINGLE_USER il DROP fallisce se e' rimasta aperta una sessione.
        return (f"IF DB_ID('{nome}') IS NOT NULL BEGIN "
                f"ALTER DATABASE {nome} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE {nome}; END")
    return f"DROP DATABASE IF EXISTS {nome}"


# --- utenti separati (Oracle: lo schema e' l'utente) -----------------------

PRIVILEGI_ORACLE = ("CREATE SESSION", "CREATE TABLE", "CREATE VIEW",
                    "CREATE SEQUENCE", "CREATE SYNONYM", "CREATE TRIGGER",
                    "CREATE PROCEDURE", "UNLIMITED TABLESPACE")


def _crea_utenti(admin, url):
    ambienti = []
    for suffisso in ("svi", "col"):
        utente = f"{PREFISSO}_{suffisso}"
        _autocommit(admin, f"DROP USER {utente} CASCADE", ignora=True)
        _autocommit(admin, f'CREATE USER {utente} IDENTIFIED BY "{PASSWORD_ORACLE}"')
        _autocommit(admin, f"GRANT {', '.join(PRIVILEGI_ORACLE)} TO {utente}")
        # Ci si connette come l'utente: il suo schema e' quello di default,
        # quindi non serve passare `schema` a DiFFDB.
        ambienti.append(Ambiente(
            nome=suffisso.upper(),
            url=_url(url, username=utente, password=PASSWORD_ORACLE),
        ))
    return ambienti


def _elimina_utenti(admin):
    for suffisso in ("svi", "col"):
        _autocommit(admin, f"DROP USER {PREFISSO}_{suffisso} CASCADE", ignora=True)


# --- utilita' --------------------------------------------------------------


def _url(base: str, **modifiche) -> str:
    """URL derivato da quello amministrativo.

    `str(URL)` sostituisce la password con '***': va chiesto esplicitamente di
    non nasconderla, altrimenti l'URL non si connette piu'.
    """
    return make_url(base).set(**modifiche).render_as_string(hide_password=False)


def _autocommit(engine, statement: str, ignora: bool = False):
    """CREATE/DROP DATABASE e CREATE USER non stanno dentro una transazione.

    Con `ignora` va assorbito anche il fallimento della connessione, non solo
    quello dell'istruzione: e' il caso della pulizia dopo un server irraggiungibile.
    """
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(statement))
    except Exception as exc:
        if not ignora:
            raise
        logger.debug("Ignorato l'errore su %r: %s", statement, exc)
