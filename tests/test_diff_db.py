"""Test del confronto e della generazione SQL, su due database SQLite veri."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.diff_DB import (  # noqa: E402
    MISSING,
    NULLABILITY_MISMATCH,
    TYPE_MISMATCH,
    compare_environments,
    generate_sql_scripts,
)

SVI_DDL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50) NOT NULL, email VARCHAR(120))",
    "CREATE TABLE ordini (id INTEGER PRIMARY KEY, cliente_id INTEGER, totale NUMERIC(10, 2))",
    "CREATE VIEW clienti_attivi AS SELECT id, nome FROM clienti WHERE email IS NOT NULL",
]

# In COL manca la tabella 'ordini', manca la colonna 'email' e 'nome' ha un tipo diverso.
COL_DDL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(30) NOT NULL)",
]


@pytest.fixture
def ambienti(tmp_path):
    svi_url = f"sqlite:///{tmp_path / 'svi.db'}"
    col_url = f"sqlite:///{tmp_path / 'col.db'}"
    for url, ddl in ((svi_url, SVI_DDL), (col_url, COL_DDL)):
        engine = create_engine(url)
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        engine.dispose()
    return svi_url, col_url


def _diff(ambienti):
    svi_url, col_url = ambienti
    return compare_environments("SVI", svi_url, "COL", col_url)


def test_rileva_tabella_mancante(ambienti):
    diff = _diff(ambienti)
    mancanti = [d for d in diff.tables if d.kind == "table" and d.change == MISSING]
    assert [(d.name, d.missing_in) for d in mancanti] == [("ordini", "COL")]


def test_rileva_colonna_mancante(ambienti):
    diff = _diff(ambienti)
    colonne = [d for d in diff.tables if d.kind == "column" and d.change == MISSING]
    assert [(d.name, d.column, d.missing_in) for d in colonne] == [("clienti", "email", "COL")]


def test_rileva_tipo_diverso(ambienti):
    """Il confronto vecchio, basato sui soli nomi, si perdeva questo caso."""
    diff = _diff(ambienti)
    tipi = [d for d in diff.tables if d.change == TYPE_MISMATCH]
    assert len(tipi) == 1
    assert tipi[0].column == "nome"
    assert "VARCHAR(50)" in tipi[0].detail and "VARCHAR(30)" in tipi[0].detail


def test_rileva_vista_mancante(ambienti):
    diff = _diff(ambienti)
    assert [(d.name, d.missing_in) for d in diff.views] == [("clienti_attivi", "COL")]


def test_nessun_sinonimo_inventato_su_sqlite(ambienti):
    """Prima si confrontavano gli schemi spacciandoli per sinonimi."""
    diff = _diff(ambienti)
    assert diff.synonyms == []


def test_sql_generato_e_eseguibile(ambienti):
    """Il test che il vecchio 'CREATE TABLE x (...);' non avrebbe mai potuto passare."""
    svi_url, col_url = ambienti
    diff = compare_environments("SVI", svi_url, "COL", col_url)
    scripts = generate_sql_scripts(diff, target_env="COL")

    statements = [s for s in scripts["tables"] + scripts["views"] if not s.startswith("--")]
    assert statements, "nessuno statement generato"
    assert "..." not in " ".join(statements), "lo script contiene ancora dei segnaposto"

    engine = create_engine(col_url)
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement.rstrip(";")))
    engine.dispose()

    # Dopo l'allineamento non manca piu' nulla in COL.
    dopo = compare_environments("SVI", svi_url, "COL", col_url)
    assert not [d for d in dopo.tables if d.change == MISSING]
    assert not dopo.views


def test_direzione_dello_script(ambienti):
    """Lo script per SVI non deve contenere gli oggetti che mancano solo a COL."""
    diff = _diff(ambienti)
    per_svi = generate_sql_scripts(diff, target_env="SVI")
    assert not any("ordini" in s for s in per_svi["tables"])


def test_ambiente_sconosciuto(ambienti):
    diff = _diff(ambienti)
    with pytest.raises(KeyError):
        generate_sql_scripts(diff, target_env="PRE")


def test_nullability(tmp_path):
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    for url, ddl in (
        (svi_url, "CREATE TABLE t (id INTEGER, nota VARCHAR(10) NOT NULL)"),
        (col_url, "CREATE TABLE t (id INTEGER, nota VARCHAR(10))"),
    ):
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(ddl))
        engine.dispose()

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert [d.change for d in diff.tables] == [NULLABILITY_MISMATCH]
