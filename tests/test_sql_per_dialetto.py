"""Come viene reso lo stesso ALTER sui vari dialetti.

Non serve un database: gli snapshot si costruiscono a mano e il DDL si compila
sul dialetto scelto. I test di integrazione (tests/integration) verificano poi
che quello che qui e' solo testo venga davvero accettato dai motori veri.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import compare_snapshots, generate_sql_scripts  # noqa: E402
from diffdb.snapshot_io import FORMAT_VERSION, from_dict  # noqa: E402


def _snapshot(env_name, dialect, *, tipo, nullable, schema=None):
    """Snapshot di una sola tabella con una sola colonna interessante."""
    return from_dict({
        "format": FORMAT_VERSION,
        "env_name": env_name,
        "dialect": dialect,
        "schema": schema,
        "tables": {
            "clienti": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "server_default": None},
                    {"name": "nome", "type": tipo, "nullable": nullable, "server_default": None},
                ],
                "primary_key": ["id"],
                "indexes": [], "unique_constraints": [], "foreign_keys": [],
            }
        },
        "views": {}, "sequences": {}, "synonyms": {},
    })


def _modify(dialect, *, tipo_atteso="VARCHAR(50)", tipo_attuale="VARCHAR(30)",
            nullable_atteso=False, nullable_attuale=False):
    source = _snapshot("SVI", dialect, tipo=tipo_atteso, nullable=nullable_atteso)
    target = _snapshot("COL", dialect, tipo=tipo_attuale, nullable=nullable_attuale)
    scripts = generate_sql_scripts(compare_snapshots(source, target), "COL")
    return [s for s in scripts["tables"] if not s.startswith("--")]


@pytest.mark.parametrize("dialect, atteso", [
    # PostgreSQL non tocca la nullability e non accetta la clausola.
    ("postgresql", "ALTER TABLE clienti ALTER COLUMN nome TYPE VARCHAR(50);"),
    # MySQL e SQL Server riscrivono la colonna: senza NOT NULL la perderebbero.
    ("mysql", "ALTER TABLE clienti MODIFY COLUMN nome VARCHAR(50) NOT NULL;"),
    ("mssql", "ALTER TABLE clienti ALTER COLUMN nome VARCHAR(50) NOT NULL;"),
    # Oracle conserva gli attributi: ripetere NOT NULL darebbe ORA-01442.
    ("oracle", "ALTER TABLE clienti MODIFY nome VARCHAR(50 CHAR);"),
])
def test_il_cambio_di_tipo_non_perde_il_not_null(dialect, atteso):
    assert _modify(dialect) == [atteso]


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "mssql", "oracle"])
def test_una_colonna_nullable_resta_nullable(dialect):
    """Nessun dialetto deve inventare un NOT NULL che non c'era."""
    generato = _modify(dialect, nullable_atteso=True, nullable_attuale=True)
    assert not any("NOT NULL" in s for s in generato)


def test_oracle_riafferma_il_not_null_solo_quando_cambia():
    """Da nullable a NOT NULL la clausola serve, ed e' l'unico caso in cui Oracle la vuole."""
    generato = _modify("oracle", nullable_atteso=False, nullable_attuale=True)
    assert generato == ["ALTER TABLE clienti MODIFY nome VARCHAR(50 CHAR) NOT NULL;"]


def test_oracle_riafferma_null_quando_la_colonna_diventa_nullable():
    generato = _modify("oracle", nullable_atteso=True, nullable_attuale=False)
    assert generato == ["ALTER TABLE clienti MODIFY nome VARCHAR(50 CHAR) NULL;"]


# --- schema ----------------------------------------------------------------


def test_l_alter_e_qualificato_con_lo_schema_del_target():
    """Senza schema nel nome, l'ALTER finirebbe sulla tabella omonima dello
    schema di default dell'utente connesso: il caso Oracle del README."""
    source = _snapshot("SVI", "oracle", tipo="VARCHAR2(50)", nullable=False, schema="APP")
    target = _snapshot("COL", "oracle", tipo="VARCHAR2(30)", nullable=False, schema="APP")

    generato = generate_sql_scripts(compare_snapshots(source, target), "COL")["tables"]

    assert generato == ["ALTER TABLE \"APP\".clienti MODIFY nome VARCHAR2(50);"]


def test_senza_schema_il_nome_resta_nudo():
    source = _snapshot("SVI", "postgresql", tipo="VARCHAR(50)", nullable=False)
    target = _snapshot("COL", "postgresql", tipo="VARCHAR(30)", nullable=False)

    generato = generate_sql_scripts(compare_snapshots(source, target), "COL")["tables"]

    assert generato == ["ALTER TABLE clienti ALTER COLUMN nome TYPE VARCHAR(50);"]
