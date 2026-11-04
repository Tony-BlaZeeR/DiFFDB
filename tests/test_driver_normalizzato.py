"""Il driver va messo da solo quando l'utente lo omette.

Senza '+driver' SQLAlchemy sceglie i suoi default (cx_oracle, mysqldb, pyodbc)
che DiFFDB non impacchetta: la connessione fallirebbe con "modulo mancante".
Qui si verifica che la stringa venga normalizzata sul driver distribuito.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.schema_snapshot import crea_engine, normalizza_driver  # noqa: E402


@pytest.mark.parametrize("ingresso,atteso", [
    # Senza driver: si mette quello impacchettato.
    ("oracle://u:p@h:1521/?service_name=X", "oracle+oracledb"),
    ("mysql://u:p@h/db", "mysql+pymysql"),
    ("mssql://u:p@h:1433/db", "mssql+pymssql"),
    ("postgresql://u:p@h/db", "postgresql+psycopg2"),
    # Sinonimi dello stesso backend: si rimpiazzano.
    ("oracle+cx_oracle://u:p@h:1521/svc", "oracle+oracledb"),
    ("mysql+mysqldb://u:p@h/db", "mysql+pymysql"),
    ("mysql+mysqlclient://u:p@h/db", "mysql+pymysql"),
    # Scelte esplicite valide: si rispettano.
    ("oracle+oracledb://u:p@h:1521/svc", "oracle+oracledb"),
    ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2"),
    # pyodbc ha una forma di URL diversa: non lo si tocca.
    ("mssql+pyodbc://u:p@h/db?driver=SQL+Server", "mssql+pyodbc"),
    # sqlite non ha driver da normalizzare.
    ("sqlite:///x.db", "sqlite"),
])
def test_normalizza_driver(ingresso, atteso):
    assert normalizza_driver(make_url(ingresso)).drivername == atteso


def test_la_query_e_i_campi_restano_intatti():
    url = normalizza_driver(make_url("oracle://app:pw@host:1521/?service_name=ORCL"))
    assert url.username == "app"
    assert url.host == "host"
    assert url.port == 1521
    assert url.query.get("service_name") == "ORCL"


@pytest.mark.parametrize("ingresso,driver", [
    ("oracle://u:p@h:1521/?service_name=X", "oracledb"),
    ("mysql://u:p@h/db", "pymysql"),
    ("mssql://u:p@h:1433/db", "pymssql"),
])
def test_crea_engine_usa_il_driver_impacchettato(ingresso, driver):
    # create_engine e' lazy: costruisce senza collegarsi al database.
    engine = crea_engine(ingresso)
    try:
        assert engine.url.get_driver_name() == driver
    finally:
        engine.dispose()
