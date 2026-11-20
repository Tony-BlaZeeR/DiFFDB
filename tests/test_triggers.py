"""Trigger: lettura, confronto, generazione e annullamento.

Nessun dialetto li riflette via SQLAlchemy (l'Inspector non ha nemmeno un
get_trigger_names): si leggono con una query diretta sul catalogo, come i
CHECK su SQL Server. SQLite pero' li supporta davvero (sqlite_master), a
differenza dei CHECK: qui il round-trip completo si verifica in locale, non
solo su CI.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import (  # noqa: E402
    DEFINITION_MISMATCH,
    MISSING,
    STATE_MISMATCH,
    compare_environments,
    compare_snapshots,
    generate_rollback_scripts,
    generate_sql_scripts,
)
from diffdb.schema_snapshot import (  # noqa: E402
    Snapshot,
    TriggerSpec,
    _stato_trigger,
    snapshot_connection,
)
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


# --- lo stato: attivo o disattivato -------------------------------------------
#
# Un trigger disattivato ha lo stesso CREATE di uno attivo, ma non scatta: due
# ambienti cosi' si comportano in modo diverso pur avendo lo stesso codice, e
# il confronto non guardava lo stato affatto. SQLite non sa disattivare un
# trigger, percio' qui gli stati si costruiscono a mano: dal vivo si verifica
# la traduzione dei valori che ogni catalogo restituisce (_stato_trigger).

def _snapshot_con_trigger(nome_ambiente: str, stato: str | None,
                          dialetto: str = "postgresql") -> Snapshot:
    snapshot = Snapshot(env_name=nome_ambiente, dialect=dialetto,
                        dialect_impl=postgresql.dialect())
    snapshot.triggers = {"trg_incr": TriggerSpec(
        name="trg_incr", table="t", definition=TRIGGER_INCR, stato=stato)}
    return snapshot


@pytest.mark.parametrize("dialetto,valore,atteso", [
    ("postgresql", "O", "attivo"),
    ("postgresql", "D", "disattivato"),
    ("postgresql", "R", "attivo solo in replica"),
    ("oracle", "ENABLED", "attivo"),
    ("oracle", "DISABLED", "disattivato"),
    ("mssql", 0, "attivo"),
    ("mssql", 1, "disattivato"),
    ("mssql", False, "attivo"),
    ("mssql", True, "disattivato"),
    ("sqlite", None, None),
    ("mysql", None, None),
])
def test_ogni_catalogo_scrive_lo_stato_a_modo_suo(dialetto, valore, atteso):
    """La traduzione dei valori nativi: tgenabled e' una lettera, status una
    parola, is_disabled un bit - e con il senso rovesciato."""
    assert _stato_trigger(dialetto, valore) == atteso


def test_uno_stato_mai_visto_non_viene_zittito():
    """Meglio un dato grezzo nel report che il silenzio su una differenza."""
    assert "non riconosciuto" in _stato_trigger("postgresql", "Z")


def test_rileva_un_trigger_disattivato():
    diff = compare_snapshots(_snapshot_con_trigger("SVI", "attivo"),
                             _snapshot_con_trigger("COL", "disattivato"))
    assert [(d.name, d.change) for d in diff.triggers] == [("trg_incr", STATE_MISMATCH)]
    assert "disattivato" in diff.triggers[0].detail


def test_stessi_stati_nessuna_differenza():
    diff = compare_snapshots(_snapshot_con_trigger("SVI", "attivo"),
                             _snapshot_con_trigger("COL", "attivo"))
    assert diff.triggers == []


@pytest.mark.parametrize("uno,due", [
    ("attivo", None),
    (None, "disattivato"),
    (None, None),
])
def test_uno_stato_che_non_si_conosce_non_si_confronta(uno, due):
    """None non vuol dire "attivo", vuol dire "non si sa": su MySQL e SQLite un
    trigger non si disattiva, e negli snapshot salvati prima lo stato non
    c'era. Confrontarlo con uno stato vero darebbe un verdetto casuale."""
    diff = compare_snapshots(_snapshot_con_trigger("SVI", uno),
                             _snapshot_con_trigger("COL", due))
    assert diff.triggers == []


@pytest.mark.parametrize("stato_sorgente,atteso", [
    ("attivo", "ENABLE TRIGGER"),
    ("disattivato", "DISABLE TRIGGER"),
])
def test_lo_script_allinea_lo_stato(stato_sorgente, atteso):
    opposto = "disattivato" if stato_sorgente == "attivo" else "attivo"
    diff = compare_snapshots(_snapshot_con_trigger("SVI", stato_sorgente),
                             _snapshot_con_trigger("COL", opposto))

    righe = generate_sql_scripts(diff, "COL")["triggers"]
    assert any(atteso in r and "trg_incr" in r for r in righe)


def test_lo_script_di_annullamento_rimette_lo_stato_di_prima():
    diff = compare_snapshots(_snapshot_con_trigger("SVI", "attivo"),
                             _snapshot_con_trigger("COL", "disattivato"))
    righe = generate_rollback_scripts(diff, "COL")["triggers"]
    assert any("DISABLE TRIGGER" in r for r in righe)


def test_uno_stato_senza_istruzione_viene_dichiarato():
    """PostgreSQL ha anche "solo in replica" e "sempre": sono rari e ognuno ha
    la sua sintassi di ENABLE. Si dichiara invece di indovinare."""
    diff = compare_snapshots(_snapshot_con_trigger("SVI", "attivo solo in replica"),
                             _snapshot_con_trigger("COL", "attivo"))
    righe = generate_sql_scripts(diff, "COL")["triggers"]
    assert any("va allineato a mano" in r for r in righe)


def test_lo_stato_sopravvive_al_salvataggio_su_file():
    snapshot = _snapshot_con_trigger("SVI", "disattivato")
    ricostruito = from_dict(to_dict(snapshot), origin="prova")
    assert ricostruito.triggers["trg_incr"].stato == "disattivato"


def test_uno_snapshot_in_formato_vecchio_non_ha_stato():
    """Negli snapshot salvati prima lo stato non c'e': vale "non si sa", e il
    confronto con uno letto dal vivo non lo inventa."""
    vecchio = from_dict({
        "format": 1, "dialect": "postgresql", "env_name": "VECCHIO",
        "triggers": {"trg_incr": {"table": "t", "definition": TRIGGER_INCR}},
    })
    assert vecchio.triggers["trg_incr"].stato is None

    diff = compare_snapshots(_snapshot_con_trigger("SVI", "disattivato"), vecchio)
    assert diff.triggers == []
