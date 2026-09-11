"""Vincoli CHECK: firma, lettura, e il caso SQLite.

Sono il quarto tipo di vincolo che DiFFDB confronta, dopo indici, foreign key e
unique. La parte delicata non e' generare l'ALTER TABLE — quello lo fa
SQLAlchemy come per gli altri — ma la firma: i nomi dei CHECK sono spesso
autogenerati dal motore e cambiano da un ambiente all'altro, quindi il
confronto deve basarsi sulla condizione, normalizzata.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import compare_snapshots, generate_sql_scripts  # noqa: E402
from diffdb.schema_snapshot import (  # noqa: E402
    check_signature,
    normalize_sql,
    snapshot_connection,
)
from diffdb.snapshot_io import FORMAT_VERSION, from_dict  # noqa: E402


def _crea(url, istruzioni):
    motore = create_engine(url)
    with motore.begin() as conn:
        for istruzione in istruzioni:
            conn.execute(text(istruzione))
    motore.dispose()


# --- normalizzazione ---------------------------------------------------------


@pytest.mark.parametrize("primo, secondo", [
    ("saldo >= 0", "SALDO  >=   0"),                  # maiuscole e spazi
    ("(saldo >= 0)", "saldo >= 0"),                    # parentesi esterne
    ("saldo >= 0;", "saldo >= 0"),                     # punto e virgola finale
    ("  saldo >= 0  ", "saldo >= 0"),                  # spazi ai bordi
])
def test_condizioni_equivalenti_normalizzano_uguali(primo, secondo):
    assert normalize_sql(primo) == normalize_sql(secondo)


def test_condizioni_diverse_normalizzano_diverse():
    assert normalize_sql("saldo >= 0") != normalize_sql("saldo > 0")


def test_normalize_sql_su_stringa_vuota_o_assente():
    assert normalize_sql("") == ""
    assert normalize_sql(None) == ""


def test_check_signature_usa_la_condizione_non_il_nome():
    """Il nome di un CHECK e' spesso autogenerato dal motore (es.
    'clienti_saldo_check' su PostgreSQL): due vincoli con nomi diversi ma
    la stessa condizione sono la stessa differenza."""
    from sqlalchemy import CheckConstraint

    a = CheckConstraint("saldo >= 0", name="ck_saldo")
    b = CheckConstraint("saldo >= 0", name="clienti_saldo_check")
    assert check_signature(a) == check_signature(b)


def test_check_signature_accetta_anche_il_solo_testo():
    """Serve anche fuori da un oggetto CheckConstraint, es. per confrontare
    una condizione salvata come stringa."""
    assert check_signature("saldo >= 0") == check_signature("SALDO >= 0")


# --- lettura: PostgreSQL legge bene, SQLite no -------------------------------


@pytest.fixture
def clienti_con_check(tmp_path):
    """Una tabella con due CHECK, sqlite e postgresql fianco a fianco."""
    ddl = ("CREATE TABLE clienti ("
           " id INTEGER NOT NULL PRIMARY KEY,"
           " saldo NUMERIC(10,2),"
           " stato VARCHAR(10),"
           " CONSTRAINT ck_saldo CHECK (saldo >= 0),"
           " CONSTRAINT ck_stato CHECK (stato IN ('A', 'B')))")
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    _crea(url, [ddl])
    return url


def test_sqlite_non_riflette_i_check(clienti_con_check):
    """Anche con un solo vincolo la riflessione su SQLite esce rovinata (una
    parentesi di troppo, o due nomi fusi in uno): meglio dichiarare la
    categoria assente che confrontare un testo gia' rotto in lettura."""
    snap = snapshot_connection("SVI", clienti_con_check)
    assert snap.check_constraints("clienti") == {}


def test_una_tabella_senza_check_da_comunque_un_dizionario_vuoto(tmp_path):
    url = f"sqlite:///{tmp_path / 'vuoto.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER)"])
    snap = snapshot_connection("SVI", url)
    assert snap.check_constraints("t") == {}


def test_una_tabella_inesistente_non_solleva(tmp_path):
    url = f"sqlite:///{tmp_path / 'x.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER)"])
    snap = snapshot_connection("SVI", url)
    assert snap.check_constraints("non_esiste") == {}


# --- il confronto non genera falsi positivi da SQLite ------------------------


def test_due_ambienti_sqlite_con_gli_stessi_check_non_sono_diversi(tmp_path):
    """Punto pratico: se la lettura fosse quella (rotta) di SQLAlchemy, due
    ambienti identici risulterebbero diversi solo per come SQLite la formatta.
    Disattivando la lettura, la categoria semplicemente non genera differenze."""
    ddl = ["CREATE TABLE clienti (id INTEGER NOT NULL PRIMARY KEY, saldo NUMERIC(10,2),"
           " CONSTRAINT ck_saldo CHECK (saldo >= 0))"]
    svi = f"sqlite:///{tmp_path / 'svi.db'}"
    col = f"sqlite:///{tmp_path / 'col.db'}"
    _crea(svi, ddl)
    _crea(col, ddl)

    from diffdb.diff_DB import compare_environments

    diff = compare_environments("SVI", svi, "COL", col)
    assert [d for d in diff.all if d.kind == "check"] == []


# --- round-trip su file (snapshot_io) ----------------------------------------


def _snapshot_postgres(con_check: bool):
    """Uno snapshot sintetico su dialetto PostgreSQL: check_constraints()
    legge per davvero solo su un dialetto diverso da sqlite."""
    return from_dict({
        "format": FORMAT_VERSION, "env_name": "SVI", "dialect": "postgresql", "schema": None,
        "tables": {"clienti": {
            "columns": [{"name": "id", "type": "INTEGER", "nullable": False,
                        "server_default": None},
                       {"name": "saldo", "type": "NUMERIC(10, 2)", "nullable": True,
                        "server_default": None}],
            "primary_key": ["id"], "indexes": [], "unique_constraints": [],
            "foreign_keys": [],
            "check_constraints": [{"name": "ck_saldo", "sqltext": "saldo >= 0"}]
            if con_check else [],
        }},
        "views": {}, "sequences": {}, "synonyms": {},
    })


def test_il_check_sopravvive_al_salvataggio_su_file():
    snap = _snapshot_postgres(con_check=True)
    assert list(snap.check_constraints("clienti")) == [check_signature("saldo >= 0")]


def test_uno_snapshot_senza_check_ha_il_dizionario_vuoto():
    snap = _snapshot_postgres(con_check=False)
    assert snap.check_constraints("clienti") == {}


def test_il_confronto_fra_due_snapshot_su_file_trova_il_check_mancante():
    con = _snapshot_postgres(con_check=True)
    senza = _snapshot_postgres(con_check=False)
    # I due ambienti devono avere nomi diversi per essere confrontabili.
    senza.env_name = "COL"

    diff = compare_snapshots(con, senza)
    trovati = [d for d in diff.all if d.kind == "check"]
    assert len(trovati) == 1
    assert trovati[0].missing_in == "COL"


def test_lo_script_generato_contiene_l_add_constraint():
    con = _snapshot_postgres(con_check=True)
    senza = _snapshot_postgres(con_check=False)
    senza.env_name = "COL"

    scripts = generate_sql_scripts(compare_snapshots(con, senza), "COL")
    istruzioni = [i for blocco in scripts.values() for i in blocco if not i.startswith("--")]
    assert any("ADD CONSTRAINT" in i and "CHECK" in i and "saldo" in i for i in istruzioni)
