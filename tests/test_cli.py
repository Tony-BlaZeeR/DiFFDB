"""CLI: --dry-run (non scrive nulla su disco) e --json (output macchina).

Le connessioni si passano come URL SQLAlchemy diretti ("://" nel token), cosi'
il test non tocca connections.json dell'utente: load_connections viene
comunque azzerato per sicurezza.
"""

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import cli  # noqa: E402


@pytest.fixture(autouse=True)
def niente_connessioni_utente(monkeypatch):
    """Isola i test dal file connections.json reale della macchina."""
    monkeypatch.setattr(cli, "load_connections", lambda: [])


@pytest.fixture
def ambienti(tmp_path):
    svi = f"sqlite:///{tmp_path / 'svi.db'}"
    col = f"sqlite:///{tmp_path / 'col.db'}"
    for url, ddl in (
        (svi, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50))"]),
        (col, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY)"]),
    ):
        engine = create_engine(url)
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        engine.dispose()
    return svi, col


def test_dry_run_non_scrive_niente_nella_cartella_di_output(ambienti, tmp_path, capsys):
    svi, col = ambienti
    output_dir = tmp_path / "out"

    codice = cli.main([svi, col, "--out", str(output_dir), "--dry-run"])

    assert codice == 0
    assert not output_dir.exists(), "in dry-run non deve nemmeno crearsi la cartella"
    catturato = capsys.readouterr().out
    assert "[dry-run]" in catturato
    assert "Nessuno script" in catturato


def test_senza_dry_run_scrive_gli_script(ambienti, tmp_path):
    svi, col = ambienti
    output_dir = tmp_path / "out"

    codice = cli.main([svi, col, "--out", str(output_dir)])

    assert codice == 0
    assert output_dir.exists()
    assert any(output_dir.iterdir()), "senza --dry-run gli script vanno scritti"


def test_dry_run_con_fail_on_diff_restituisce_comunque_1(ambienti, tmp_path):
    svi, col = ambienti
    output_dir = tmp_path / "out"

    codice = cli.main([svi, col, "--out", str(output_dir), "--dry-run", "--fail-on-diff"])

    assert codice == 1
    assert not output_dir.exists()


def test_dry_run_su_snapshot_non_crea_il_file(ambienti, tmp_path, capsys):
    svi, _ = ambienti
    destinazione = tmp_path / "baseline.json"

    codice = cli.main([svi, "--snapshot", str(destinazione), "--dry-run"])

    assert codice == 0
    assert not destinazione.exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_senza_dry_run_snapshot_scrive_il_file(ambienti, tmp_path):
    svi, _ = ambienti
    destinazione = tmp_path / "baseline.json"

    codice = cli.main([svi, "--snapshot", str(destinazione)])

    assert codice == 0
    assert destinazione.exists()


def test_dry_run_su_accept_non_modifica_le_regole(ambienti, tmp_path, monkeypatch):
    svi, col = ambienti
    monkeypatch.chdir(tmp_path)
    regole_path = tmp_path / "diffdb.rules.json"

    codice = cli.main([svi, col, "--dry-run", "--accept"])

    assert codice == 0
    assert not regole_path.exists(), "in dry-run le regole accettate non si scrivono"


def test_senza_dry_run_accept_scrive_le_regole(ambienti, tmp_path, monkeypatch):
    svi, col = ambienti
    monkeypatch.chdir(tmp_path)
    regole_path = tmp_path / "diffdb.rules.json"

    codice = cli.main([svi, col, "--accept"])

    assert codice == 0
    assert regole_path.exists()


# --- --json -----------------------------------------------------------------


def test_json_restituisce_le_differenze_in_formato_stabile(ambienti, tmp_path, capsys):
    svi, col = ambienti
    output_dir = tmp_path / "out"

    codice = cli.main([svi, col, "--out", str(output_dir), "--json"])

    assert codice == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["env1"] and payload["env2"]
    assert payload["count"] == len(payload["differences"]) > 0
    assert payload["already_accepted"] == 0
    prima = payload["differences"][0]
    assert set(prima) == {"kind", "name", "change", "column",
                          "missing_in", "present_in", "detail"}
    # senza --dry-run gli script si scrivono comunque, anche con --json
    assert payload["written"]
    assert output_dir.exists()


def test_json_con_dry_run_non_scrive_e_written_e_vuoto(ambienti, tmp_path, capsys):
    svi, col = ambienti
    output_dir = tmp_path / "out"

    codice = cli.main([svi, col, "--out", str(output_dir), "--json", "--dry-run"])

    assert codice == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == []
    assert not output_dir.exists()


def test_json_senza_differenze(tmp_path, capsys):
    svi = f"sqlite:///{tmp_path / 'a.db'}"
    col = f"sqlite:///{tmp_path / 'b.db'}"
    for url in (svi, col):
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        engine.dispose()

    codice = cli.main([svi, col, "--json"])

    assert codice == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["differences"] == []
    assert payload["written"] == []


def test_json_con_fail_on_diff_restituisce_1(ambienti, tmp_path):
    svi, col = ambienti
    codice = cli.main([svi, col, "--out", str(tmp_path / "out"), "--json", "--fail-on-diff"])
    assert codice == 1


def test_json_senza_fail_on_diff_restituisce_0_anche_con_differenze(ambienti, tmp_path):
    svi, col = ambienti
    codice = cli.main([svi, col, "--out", str(tmp_path / "out"), "--json"])
    assert codice == 0
