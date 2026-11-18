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

from diffdb.schema_snapshot import (  # noqa: E402
    controlla_driver_disponibile,
    crea_engine,
    normalizza_driver,
)


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


# --- driver assente: l'utente deve capire cosa fare -------------------------
#
# Su macOS SQL Server non e' nel pacchetto (il wheel di pymssql spedisce
# OpenSSL x86_64 e rompeva ssl, psycopg2 e oracledb): senza un messaggio
# esplicito l'utente vedrebbe solo "No module named 'pymssql'".

def test_driver_presente_non_solleva():
    controlla_driver_disponibile(make_url("postgresql+psycopg2://u:p@h/db"))


def test_driver_nostro_mancante_spiega_come_installarlo(monkeypatch):
    monkeypatch.setattr(
        "diffdb.schema_snapshot.importlib.util.find_spec", lambda nome: None
    )
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError) as errore:
        controlla_driver_disponibile(make_url("oracle+oracledb://u:p@h:1521/x"))

    messaggio = str(errore.value)
    assert "oracledb" in messaggio
    assert "diffdb[oracle]" in messaggio


def test_su_macos_sql_server_dice_che_non_c_e(monkeypatch):
    monkeypatch.setattr(
        "diffdb.schema_snapshot.importlib.util.find_spec", lambda nome: None
    )
    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(RuntimeError) as errore:
        controlla_driver_disponibile(make_url("mssql+pymssql://u:p@h/db"))

    assert "macOS" in str(errore.value)


def test_i_driver_non_nostri_non_sono_controllati(monkeypatch):
    """pyodbc e pysqlite li installa l'utente: non dobbiamo bocciarli noi,
    e 'pysqlite' non e' nemmeno il nome di un modulo importabile."""
    monkeypatch.setattr(
        "diffdb.schema_snapshot.importlib.util.find_spec", lambda nome: None
    )
    controlla_driver_disponibile(make_url("mssql+pyodbc://u:p@h/db"))
    controlla_driver_disponibile(make_url("sqlite:///x.db"))
