"""Tracciabilita' degli script generati.

Lo script .sql finisce in produzione: deve dire da dove viene, e deve permettere
di scoprire che l'ambiente e' cambiato dopo che e' stato generato.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import __version__, audit  # noqa: E402
from diffdb.diff_DB import compare_environments, generate_sql_scripts  # noqa: E402
from diffdb.report import write_sql, write_sql_script  # noqa: E402
from diffdb.schema_snapshot import snapshot_connection  # noqa: E402
from diffdb.snapshot_io import fingerprint  # noqa: E402

# Due differenze, entrambe allineabili con un ADD COLUMN: servono a distinguere
# un export completo da uno parziale.
SVI = ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50) NOT NULL, "
       "email VARCHAR(120), telefono VARCHAR(20))"]
COL = ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50) NOT NULL)"]


def _crea(url, statements):
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    engine.dispose()


@pytest.fixture
def ambienti(tmp_path):
    svi, col = f"sqlite:///{tmp_path/'svi.db'}", f"sqlite:///{tmp_path/'col.db'}"
    _crea(svi, SVI)
    _crea(col, COL)
    return svi, col


@pytest.fixture
def diff(ambienti):
    return compare_environments("SVI", ambienti[0], "COL", ambienti[1])


@pytest.fixture
def script(diff, tmp_path):
    percorso = tmp_path / "allinea_col.sql"
    write_sql_script(generate_sql_scripts(diff, "COL"), str(percorso), "COL", diff)
    return percorso


# --- impronta --------------------------------------------------------------


def test_l_impronta_cambia_se_cambia_lo_schema(ambienti):
    prima = fingerprint(snapshot_connection("COL", ambienti[1]))
    _crea(ambienti[1], ["ALTER TABLE clienti ADD COLUMN telefono VARCHAR(20)"])
    dopo = fingerprint(snapshot_connection("COL", ambienti[1]))

    assert prima != dopo


def test_l_impronta_non_cambia_se_non_cambia_niente(ambienti):
    """Rifotografare lo stesso ambiente un istante dopo deve dare la stessa impronta:
    l'istante e il nome non fanno parte della struttura."""
    prima = fingerprint(snapshot_connection("COL", ambienti[1]))
    dopo = fingerprint(snapshot_connection("NOME DIVERSO", ambienti[1]))

    assert prima == dopo


# --- intestazione ----------------------------------------------------------


def test_l_intestazione_dice_da_dove_viene_lo_script(script):
    testo = script.read_text(encoding="utf-8")

    assert f"DiFFDB {__version__}" in testo
    assert "Ambiente da allineare : COL" in testo
    assert "Allineato a           : SVI" in testo
    assert "Generato da" in testo


def test_l_intestazione_e_rileggibile(script, diff):
    meta = audit.leggi_meta(script)

    assert meta["versione_diffdb"] == __version__
    assert meta["target"] == "COL"
    assert meta["sorgente"] == "SVI"
    assert meta["impronta_target"] == fingerprint(diff.snapshot_of("COL"))
    assert meta["impronta_sorgente"] == fingerprint(diff.snapshot_of("SVI"))


def test_uno_script_senza_intestazione_lo_dice_chiaramente(tmp_path):
    vecchio = tmp_path / "vecchio.sql"
    vecchio.write_text("-- Generato da DiFFDB.\nALTER TABLE x ADD y INT;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="diffdb-meta"):
        audit.leggi_meta(vecchio)


def test_un_export_parziale_lo_dichiara(diff, tmp_path):
    """Se si esporta solo una parte delle differenze, lo script deve dirlo:
    altrimenti chi lo legge lo crede completo."""
    parziale = diff.subset(diff.all[:1])
    percorso = tmp_path / "parziale.sql"

    write_sql_script(generate_sql_scripts(parziale, "COL"), str(percorso), "COL",
                     parziale, totali=len(diff.all))

    assert "Differenze incluse" in percorso.read_text(encoding="utf-8")


def test_un_export_completo_non_parla_di_selezione(script):
    assert "Differenze incluse" not in script.read_text(encoding="utf-8")


def test_l_intestazione_non_rompe_lo_script(diff, tmp_path, ambienti):
    """Le righe in piu' sono commenti: lo script deve restare eseguibile."""
    percorsi = write_sql(diff, str(tmp_path))
    testo = Path(percorsi[0]).read_text(encoding="utf-8")

    # Fuori i commenti e il controllo di transazione: qui si verifica che
    # l'intestazione non disturbi, non come si comporta il BEGIN/COMMIT (che ha
    # i suoi test in test_script_eseguibile.py).
    istruzioni = [r for r in testo.splitlines()
                  if r.strip() and not r.strip().startswith("--")
                  and r.strip().rstrip(";").upper() not in ("BEGIN", "COMMIT",
                                                            "BEGIN TRANSACTION",
                                                            "COMMIT TRANSACTION")]
    engine = create_engine(ambienti[1])
    with engine.begin() as conn:
        for istruzione in istruzioni:
            conn.execute(text(istruzione.rstrip(";")))
    engine.dispose()

    assert compare_environments("SVI", ambienti[0], "COL", ambienti[1]).all == []


# --- verify ----------------------------------------------------------------


def test_verify_passa_se_l_ambiente_non_e_cambiato(script, ambienti):
    from diffdb.cli import verifica

    assert verifica(str(script), ambienti[1], None, []) == 0


def test_verify_fallisce_se_l_ambiente_e_cambiato(script, ambienti):
    from diffdb.cli import verifica

    _crea(ambienti[1], ["ALTER TABLE clienti ADD COLUMN telefono VARCHAR(20)"])

    assert verifica(str(script), ambienti[1], None, []) == 1


def test_verify_non_stampa_la_password(script, capsys):
    from diffdb.cli import verifica

    verifica(str(script), "postgresql://app:segretissima@host:5432/db", None, [])

    assert "segretissima" not in capsys.readouterr().out
