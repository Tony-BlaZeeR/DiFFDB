"""Connessioni: formato JSON, migrazione dal vecchio testo, e la CLI."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import cli, connections  # noqa: E402
from diffdb.connections import (  # noqa: E402
    Connection,
    load_connections,
    parse_text,
    save_connections,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    return tmp_path


def test_salva_e_rilegge_lo_schema(home):
    save_connections([Connection("SVI", "sqlite:///a.db", schema="APP")])
    (letta,) = load_connections()
    assert (letta.name, letta.conn_string, letta.schema) == ("SVI", "sqlite:///a.db", "APP")


def test_migrazione_dal_vecchio_formato_testo(home):
    (home / "connections.txt").write_text(
        "db1,postgresql+psycopg2://u:p@localhost:5432/db1\n", encoding="utf-8")

    (letta,) = load_connections()
    assert letta.name == "db1"
    assert (home / "connections.json").exists(), "la migrazione deve scrivere il nuovo file"


def test_conn_string_con_virgola(home):
    """SQL Server usa 'host,porta': lo split ingenuo su ',' faceva crashare l'app."""
    (connessione,) = parse_text(
        ["prod,mssql+pyodbc://user:pwd@srv.local,1433/db?driver=SQL+Server"])
    assert connessione.name == "prod"
    assert connessione.conn_string.endswith("srv.local,1433/db?driver=SQL+Server")


def test_json_illeggibile_non_fa_crashare(home):
    (home / "connections.json").write_text("{ questo non e' json", encoding="utf-8")
    assert load_connections() == []


def test_cli_risolve_un_url_diretto(home):
    connessione = cli.resolve("sqlite:///a.db", None, [])
    assert connessione.conn_string == "sqlite:///a.db"


def test_cli_su_connessione_inesistente(home):
    with pytest.raises(SystemExit):
        cli.resolve("PROD", None, [])


def test_cli_confronto_senza_differenze(home, tmp_path, capsys):
    from sqlalchemy import create_engine, text

    for nome in ("a", "b"):
        engine = create_engine(f"sqlite:///{tmp_path / nome}.db")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER)"))
        engine.dispose()

    connections.save_connections([
        Connection("SVI", f"sqlite:///{tmp_path / 'a'}.db"),
        Connection("COL", f"sqlite:///{tmp_path / 'b'}.db"),
    ])

    assert cli.main(["SVI", "COL", "--fail-on-diff"]) == 0
    assert "Nessuna differenza" in capsys.readouterr().out


def test_cli_fail_on_diff_esce_con_uno(home, tmp_path, capsys):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'a'}.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
        conn.execute(text("CREATE TABLE solo_in_svi (id INTEGER)"))
    engine.dispose()

    engine = create_engine(f"sqlite:///{tmp_path / 'b'}.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
    engine.dispose()

    connections.save_connections([
        Connection("SVI", f"sqlite:///{tmp_path / 'a'}.db"),
        Connection("COL", f"sqlite:///{tmp_path / 'b'}.db"),
    ])

    uscita = cli.main(["SVI", "COL", "--out", str(tmp_path / "out"), "--fail-on-diff"])
    assert uscita == 1, "in pipeline deve fallire quando gli ambienti divergono"
    assert "solo_in_svi" in capsys.readouterr().out
    assert (tmp_path / "out" / "differenze_ambienti.xlsx").exists()
