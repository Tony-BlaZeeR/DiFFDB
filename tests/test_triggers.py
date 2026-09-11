"""Trigger: lettura, confronto, generazione e annullamento.

Nessun dialetto li riflette via SQLAlchemy (l'Inspector non ha nemmeno un
get_trigger_names): si leggono con una query diretta sul catalogo, come i
CHECK su SQL Server. SQLite pero' li supporta davvero (sqlite_master), a
differenza dei CHECK: qui il round-trip completo si verifica in locale, non
solo su CI.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import (  # noqa: E402
    DEFINITION_MISMATCH,
    MISSING,
    compare_environments,
    compare_snapshots,
    generate_rollback_scripts,
    generate_sql_scripts,
)
from diffdb.schema_snapshot import TriggerSpec, snapshot_connection  # noqa: E402
from diffdb.snapshot_io import from_dict, to_dict  # noqa: E402


def _crea(url, istruzioni):
    motore = create_engine(url)
    with motore.begin() as conn:
        for istruzione in istruzioni:
            conn.execute(text(istruzione))
    motore.dispose()


TRIGGER_INCR = (
    "CREATE TRIGGER trg_incr AFTER INSERT ON t "
    "BEGIN UPDATE t SET val = val + 1 WHERE id = NEW.id; END"
)
TRIGGER_DECR = (
    "CREATE TRIGGER trg_incr AFTER INSERT ON t "
    "BEGIN UPDATE t SET val = val - 1 WHERE id = NEW.id; END"
)


# --- lettura -----------------------------------------------------------------


def test_snapshot_legge_il_trigger_da_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])

    snapshot = snapshot_connection("SVI", url)
    assert list(snapshot.triggers) == ["trg_incr"]
    spec = snapshot.triggers["trg_incr"]
    assert spec.table == "t"
    assert "trg_incr" in spec.definition


def test_nessuna_tabella_nessun_trigger(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER PRIMARY KEY)"])
    assert snapshot_connection("SVI", url).triggers == {}


# --- confronto ----------------------------------------------------------------


def test_rileva_trigger_mancante(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert [(d.name, d.change, d.missing_in) for d in diff.triggers] == [
        ("trg_incr", MISSING, "COL")]


def test_rileva_corpo_diverso(tmp_path):
    """Stesso nome, stessa tabella, corpo diverso: prima passava inosservato."""
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_DECR])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert [(d.name, d.change) for d in diff.triggers] == [("trg_incr", DEFINITION_MISMATCH)]


def test_formattazione_diversa_non_segnalata(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, [
        "CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)",
        "CREATE TRIGGER trg_incr AFTER INSERT ON t "
        "BEGIN   UPDATE  t   SET val = val + 1   WHERE id = NEW.id;   END",
    ])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert diff.triggers == []


def test_nessuna_differenza_su_ambienti_identici(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    ddl = ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR]
    _crea(svi_url, ddl)
    _crea(col_url, ddl)

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    assert diff.triggers == []


# --- generazione dello script -------------------------------------------------


def test_script_crea_il_trigger_mancante(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    scripts = generate_sql_scripts(diff, "COL")
    joined = "\n".join(scripts["triggers"])
    assert "CREATE TRIGGER trg_incr" in joined
    assert "DROP TRIGGER" not in joined   # non esisteva: niente da togliere prima


def test_script_sostituisce_il_trigger_con_corpo_diverso(tmp_path):
    """Nessun motore reale qui usato ha un CREATE OR REPLACE TRIGGER uniforme
    (MySQL non lo ha per niente): sempre DROP + CREATE."""
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_DECR])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    scripts = generate_sql_scripts(diff, "COL")
    joined = "\n".join(scripts["triggers"])
    assert "DROP TRIGGER trg_incr" in joined
    assert "val + 1" in joined   # il corpo di SVI, non quello di COL


def test_script_generato_e_eseguibile(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    scripts = generate_sql_scripts(diff, "COL")

    engine = create_engine(col_url)
    with engine.begin() as conn:
        for istruzione in scripts["triggers"]:
            if not istruzione.strip().startswith("--"):
                conn.execute(text(istruzione))
        conn.execute(text("INSERT INTO t (id, val) VALUES (1, 10)"))
        valore = conn.execute(text("SELECT val FROM t WHERE id = 1")).scalar()
    assert valore == 11   # il trigger appena creato ha incrementato il valore


# --- annullamento --------------------------------------------------------------


def test_rollback_toglie_il_trigger_aggiunto(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)"])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    rollback = generate_rollback_scripts(diff, "COL")
    assert any("DROP TRIGGER trg_incr" in i for i in rollback["triggers"])


def test_rollback_ripristina_il_corpo_precedente(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_DECR])

    diff = compare_environments("SVI", svi_url, "COL", col_url)
    rollback = generate_rollback_scripts(diff, "COL")
    joined = "\n".join(rollback["triggers"])
    assert "DROP TRIGGER trg_incr" in joined
    assert "val - 1" in joined   # il corpo originale di COL, non quello di SVI


# --- snapshot su file ----------------------------------------------------------


def test_il_trigger_sopravvive_al_salvataggio_su_file(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])

    snapshot = snapshot_connection("SVI", url)
    payload = to_dict(snapshot)
    ricostruito = from_dict(payload, origin="prova")

    assert list(ricostruito.triggers) == ["trg_incr"]
    assert ricostruito.triggers["trg_incr"].table == "t"
    assert "trg_incr" in ricostruito.triggers["trg_incr"].definition


def test_uno_snapshot_senza_trigger_ha_il_dizionario_vuoto(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER PRIMARY KEY)"])
    ricostruito = from_dict(to_dict(snapshot_connection("SVI", url)), origin="prova")
    assert ricostruito.triggers == {}


def test_confronto_fra_due_snapshot_su_file_trova_il_trigger_mancante(tmp_path):
    svi_url, col_url = f"sqlite:///{tmp_path / 'a.db'}", f"sqlite:///{tmp_path / 'b.db'}"
    _crea(svi_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    _crea(col_url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)"])

    snap1 = from_dict(to_dict(snapshot_connection("SVI", svi_url)), origin="svi")
    snap2 = from_dict(to_dict(snapshot_connection("COL", col_url)), origin="col")

    diff = compare_snapshots(snap1, snap2)
    assert [(d.name, d.change) for d in diff.triggers] == [("trg_incr", MISSING)]


# --- fingerprint ----------------------------------------------------------------


def test_il_trigger_entra_nell_impronta(tmp_path):
    """--verify deve accorgersi se cambia solo il corpo di un trigger."""
    from diffdb.snapshot_io import impronta_di

    url = f"sqlite:///{tmp_path / 'a.db'}"
    _crea(url, ["CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER)", TRIGGER_INCR])
    con_trigger = impronta_di(to_dict(snapshot_connection("SVI", url)))

    snapshot = snapshot_connection("SVI", url)
    snapshot.triggers = {}
    senza_trigger = impronta_di(to_dict(snapshot))

    assert con_trigger != senza_trigger


def test_trigger_spec_e_un_dataclass_semplice():
    spec = TriggerSpec(name="t1", table="tab", definition="CREATE TRIGGER t1 ...")
    assert spec.name == "t1" and spec.table == "tab"
