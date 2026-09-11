"""Test del confronto e della generazione SQL, su due database SQLite veri."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import (  # noqa: E402
    DEFAULT_MISMATCH,
    DEFINITION_MISMATCH,
    MISSING,
    NULLABILITY_MISMATCH,
    TYPE_MISMATCH,
    compare_environments,
    generate_sql_scripts,
)

# Nota: l'UNIQUE va dichiarato a livello di tabella. SQLAlchemy non riflette
# l'UNIQUE scritto inline sulla colonna quando il database e' SQLite.
SVI_DDL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50) NOT NULL, "
    "email VARCHAR(120), partita_iva VARCHAR(11), UNIQUE (partita_iva))",
    "CREATE TABLE ordini (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, "
    "totale NUMERIC(10, 2), FOREIGN KEY (cliente_id) REFERENCES clienti (id))",
    "CREATE INDEX ix_clienti_email ON clienti (email)",
    "CREATE VIEW clienti_attivi AS SELECT id, nome FROM clienti WHERE email IS NOT NULL",
]

# In COL: manca la tabella 'ordini' (con la sua FK), manca la colonna 'email' e
# il suo indice, 'nome' ha un tipo diverso, manca l'unique su partita_iva.
COL_DDL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(30) NOT NULL, "
    "partita_iva VARCHAR(11))",
]


def _crea(url, statements):
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    engine.dispose()


@pytest.fixture
def ambienti(tmp_path):
    svi_url = f"sqlite:///{tmp_path / 'svi.db'}"
    col_url = f"sqlite:///{tmp_path / 'col.db'}"
    _crea(svi_url, SVI_DDL)
    _crea(col_url, COL_DDL)
    return svi_url, col_url


@pytest.fixture
def diff(ambienti):
    svi_url, col_url = ambienti
    return compare_environments("SVI", svi_url, "COL", col_url)


def test_rileva_tabella_mancante(diff):
    mancanti = [d for d in diff.tables if d.kind == "table" and d.change == MISSING]
    assert [(d.name, d.missing_in) for d in mancanti] == [("ordini", "COL")]


def test_rileva_colonna_mancante(diff):
    colonne = [d for d in diff.tables if d.kind == "column" and d.change == MISSING]
    assert [(d.name, d.column, d.missing_in) for d in colonne] == [("clienti", "email", "COL")]


def test_rileva_tipo_diverso(diff):
    """Il confronto vecchio, basato sui soli nomi, si perdeva questo caso."""
    tipi = [d for d in diff.tables if d.change == TYPE_MISMATCH]
    assert len(tipi) == 1
    assert tipi[0].column == "nome"
    assert "VARCHAR(50)" in tipi[0].detail and "VARCHAR(30)" in tipi[0].detail


def test_rileva_indice_mancante(diff):
    indici = [d for d in diff.constraints if d.kind == "index"]
    assert [(d.name, d.detail, d.missing_in) for d in indici] == [("clienti", "(email)", "COL")]


def test_rileva_unique_mancante(diff):
    unici = [d for d in diff.constraints if d.kind == "unique"]
    assert [(d.name, d.missing_in) for d in unici] == [("clienti", "COL")]


def test_rileva_vista_mancante(diff):
    assert [(d.name, d.missing_in) for d in diff.views] == [("clienti_attivi", "COL")]


def test_nessun_sinonimo_inventato_su_sqlite(diff):
    """Prima si confrontavano gli schemi spacciandoli per sinonimi."""
    assert diff.synonyms == []


def test_sql_generato_e_eseguibile(ambienti):
    """Il test che il vecchio 'CREATE TABLE x (...);' non avrebbe mai potuto passare."""
    svi_url, col_url = ambienti
    diff = compare_environments("SVI", svi_url, "COL", col_url)
    scripts = generate_sql_scripts(diff, target_env="COL")

    statements = [
        s for s in scripts["tables"] + scripts["constraints"] + scripts["views"]
        if not s.startswith("--")
    ]
    assert statements, "nessuno statement generato"
    assert "..." not in " ".join(statements), "lo script contiene ancora dei segnaposto"

    engine = create_engine(col_url)
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement.rstrip(";")))
    engine.dispose()

    # Dopo l'allineamento non manca piu' niente in COL: tabella, colonna, indice, vista.
    dopo = compare_environments("SVI", svi_url, "COL", col_url)
    assert not [d for d in dopo.tables if d.change == MISSING]
    assert not [d for d in dopo.constraints if d.change == MISSING and d.kind == "index"]
    assert not dopo.views


def test_create_table_include_la_foreign_key(diff):
    """La FK di 'ordini' deve finire dentro il CREATE TABLE, non sparire."""
    scripts = generate_sql_scripts(diff, target_env="COL")
    create = next(s for s in scripts["tables"] if s.startswith("CREATE TABLE"))
    assert "FOREIGN KEY" in create and "REFERENCES clienti" in create


def test_direzione_dello_script(diff):
    """Lo script per SVI non deve contenere gli oggetti che mancano solo a COL."""
    per_svi = generate_sql_scripts(diff, target_env="SVI")
    assert not any("ordini" in s for s in per_svi["tables"])


def test_ambiente_sconosciuto(diff):
    with pytest.raises(KeyError):
        generate_sql_scripts(diff, target_env="PRE")


def test_nullability(tmp_path):
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER, nota VARCHAR(10) NOT NULL)"])
    _crea(col_url, ["CREATE TABLE t (id INTEGER, nota VARCHAR(10))"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert [d.change for d in diff.tables] == [NULLABILITY_MISMATCH]

    # Un NOT NULL su una tabella gia' popolata puo' fallire: si segnala, non si esegue.
    scripts = generate_sql_scripts(diff, target_env="COL")
    assert all(s.startswith("--") for s in scripts["tables"])


def test_default_di_colonna_diverso(tmp_path):
    """Punto 2: prima confrontavo solo tipo e nullability, non il default."""
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE ordini (id INTEGER, stato VARCHAR(10) DEFAULT 'nuovo')"])
    _crea(col_url, ["CREATE TABLE ordini (id INTEGER, stato VARCHAR(10) DEFAULT 'aperto')"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    default = [d for d in diff.tables if d.change == DEFAULT_MISMATCH]
    assert len(default) == 1
    assert default[0].column == "stato"
    assert "nuovo" in default[0].detail and "aperto" in default[0].detail


def test_default_uguale_non_segnalato(tmp_path):
    """Lo stesso default non deve produrre una differenza fantasma."""
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    ddl = "CREATE TABLE t (id INTEGER, n INTEGER DEFAULT 0)"
    _crea(svi_url, [ddl])
    _crea(col_url, [ddl])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert not [d for d in diff.tables if d.change == DEFAULT_MISMATCH]


def test_corpo_vista_diverso(tmp_path):
    """Punto 1: due viste con lo stesso nome ma SQL diverso prima passavano inosservate."""
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER, s VARCHAR(5))",
                    "CREATE VIEW v AS SELECT id FROM t WHERE s = 'ok'"])
    _crea(col_url, ["CREATE TABLE t (id INTEGER, s VARCHAR(5))",
                    "CREATE VIEW v AS SELECT id FROM t WHERE s = 'ko'"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    viste = [d for d in diff.views if d.change == DEFINITION_MISMATCH]
    assert len(viste) == 1 and viste[0].name == "v"

    # Su SQLite (niente OR REPLACE) l'allineamento e' DROP + CREATE.
    scripts = generate_sql_scripts(diff, "COL")
    joined = "\n".join(scripts["views"])
    assert "DROP VIEW" in joined and "CREATE VIEW" in joined and "'ok'" in joined


def test_vista_solo_diversa_nella_formattazione_non_segnalata(tmp_path):
    """Spazi e maiuscole non devono generare falsi positivi."""
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER)", "CREATE VIEW v AS SELECT id FROM t"])
    _crea(col_url, ["CREATE TABLE t (id INTEGER)", "CREATE VIEW v AS  SELECT  id  FROM t"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert not [d for d in diff.views if d.change == DEFINITION_MISMATCH]


def test_chiave_primaria_diversa(tmp_path):
    svi_url = f"sqlite:///{tmp_path / 'a.db'}"
    col_url = f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (a INTEGER, b INTEGER, PRIMARY KEY (a))"])
    _crea(col_url, ["CREATE TABLE t (a INTEGER, b INTEGER, PRIMARY KEY (a, b))"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    pk = [d for d in diff.constraints if d.kind == "primary_key"]
    assert len(pk) == 1 and pk[0].change == DEFINITION_MISMATCH
    assert "(a)" in pk[0].detail and "(a,b)" in pk[0].detail

    # Cambiare una PK e' distruttivo: si segnala e basta.
    scripts = generate_sql_scripts(diff, target_env="COL")
    assert all(s.startswith("--") for s in scripts["constraints"])
