"""Lo script generato deve poter essere eseguito dall'inizio alla fine.

Due proprieta' che riguardano l'esecuzione e non il contenuto:

- le tabelle si creano **nell'ordine giusto**, perche' ogni foreign key trovi
  il suo bersaglio gia' esistente;
- lo script si apre in **transazione** dove il database sa annullare un DDL, e
  dove non lo sa dichiara che non puo'.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.config.dialectConfig import templates_for  # noqa: E402
from diffdb.diff_DB import compare_environments, generate_sql_scripts  # noqa: E402
from diffdb.report import write_sql_script  # noqa: E402
from diffdb.snapshot_io import FORMAT_VERSION, from_dict  # noqa: E402

# I nomi sono scelti perche' l'ordine alfabetico sia l'esatto contrario di
# quello giusto: 'anagrafica' punta a 'movimenti', che punta a 'zone'. In ordine
# alfabetico lo script creerebbe 'anagrafica' per prima e fallirebbe subito.
SVI = [
    "CREATE TABLE zone (id INTEGER NOT NULL PRIMARY KEY, nome VARCHAR(50))",
    "CREATE TABLE movimenti (id INTEGER NOT NULL PRIMARY KEY, zona_id INTEGER NOT NULL, "
    "FOREIGN KEY (zona_id) REFERENCES zone (id))",
    "CREATE TABLE anagrafica (id INTEGER NOT NULL PRIMARY KEY, movimento_id INTEGER NOT NULL, "
    "FOREIGN KEY (movimento_id) REFERENCES movimenti (id))",
]


def _crea(url, istruzioni):
    motore = create_engine(url)
    with motore.begin() as conn:
        for istruzione in istruzioni:
            conn.execute(text(istruzione))
    motore.dispose()


@pytest.fixture
def ambienti(tmp_path):
    """SVI ha tre tabelle concatenate da foreign key, COL e' vuoto."""
    svi, col = f"sqlite:///{tmp_path/'svi.db'}", f"sqlite:///{tmp_path/'col.db'}"
    _crea(svi, SVI)
    _crea(col, [])          # COL esiste ma e' vuoto
    return svi, col


# --- ordine di creazione ----------------------------------------------------


def test_le_tabelle_si_creano_in_ordine_di_dipendenza(ambienti):
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    istruzioni = generate_sql_scripts(diff, "COL")["tables"]

    ordine = [riga.split()[2] for riga in istruzioni if riga.startswith("CREATE TABLE")]

    assert ordine == ["zone", "movimenti", "anagrafica"], (
        f"ordine sbagliato: {ordine}")
    # L'ordine alfabetico sarebbe l'opposto: se un giorno qualcuno togliesse
    # l'ordinamento, questo test se ne accorgerebbe.
    assert ordine != sorted(ordine)


def test_lo_script_si_esegue_dall_inizio_alla_fine(ambienti):
    """La prova vera: eseguirlo davvero su un database."""
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    scripts = generate_sql_scripts(diff, "COL")

    motore = create_engine(ambienti[1])
    with motore.begin() as conn:
        for sezione in ("tables", "constraints"):
            for istruzione in scripts[sezione]:
                if not istruzione.startswith("--"):
                    conn.execute(text(istruzione.rstrip(";")))
    motore.dispose()

    assert compare_environments("SVI", ambienti[0], "COL", ambienti[1]).all == []


def test_un_ciclo_di_foreign_key_viene_dichiarato(tmp_path):
    """Con un ciclo nessun ordine funziona: va detto, non nascosto."""
    def snapshot(env_name, con_tabelle):
        return from_dict({
            "format": FORMAT_VERSION, "env_name": env_name, "dialect": "postgresql",
            "schema": None, "tables": con_tabelle,
            "views": {}, "sequences": {}, "synonyms": {},
        })

    colonne = [{"name": "id", "type": "INTEGER", "nullable": False, "server_default": None},
               {"name": "altro", "type": "INTEGER", "nullable": True, "server_default": None}]
    sorgente = snapshot("SVI", {
        "a": {"columns": colonne, "primary_key": ["id"], "indexes": [],
              "unique_constraints": [],
              "foreign_keys": [{"name": "fk_a", "columns": ["altro"], "refers_to": ["b.id"]}]},
        "b": {"columns": colonne, "primary_key": ["id"], "indexes": [],
              "unique_constraints": [],
              "foreign_keys": [{"name": "fk_b", "columns": ["altro"], "refers_to": ["a.id"]}]},
    })
    vuoto = snapshot("COL", {})

    from diffdb.diff_DB import compare_snapshots

    istruzioni = generate_sql_scripts(compare_snapshots(sorgente, vuoto), "COL")["tables"]

    assert any("ciclo di foreign key" in riga for riga in istruzioni)
    # Le tabelle vengono comunque emesse: meta' script e' meglio di niente.
    assert sum(1 for r in istruzioni if r.startswith("CREATE TABLE")) == 2


# --- transazione ------------------------------------------------------------


@pytest.mark.parametrize("dialetto, transazionale", [
    ("postgresql", True),
    ("mssql", True),
    ("sqlite", True),
    ("mysql", False),    # commit implicito a ogni DDL
    ("oracle", False),
])
def test_ogni_dialetto_dichiara_se_sa_annullare(dialetto, transazionale):
    templates = templates_for(dialetto)
    assert bool(templates["begin"]) is transazionale
    assert bool(templates["commit"]) is transazionale


def test_lo_script_apre_e_chiude_la_transazione(ambienti, tmp_path):
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    percorso = tmp_path / "allinea.sql"
    write_sql_script(generate_sql_scripts(diff, "COL"), str(percorso), "COL", diff)

    testo = percorso.read_text(encoding="utf-8")
    assert "BEGIN;" in testo
    assert testo.rstrip().endswith("COMMIT;")
    # L'apertura sta dopo l'intestazione e prima della prima istruzione.
    assert testo.index("BEGIN;") < testo.index("CREATE TABLE")


def test_dove_non_si_puo_annullare_lo_script_lo_dice(tmp_path):
    """Su Oracle e MySQL una transazione finta sarebbe peggio di nessuna."""
    prod = from_dict({
        "format": FORMAT_VERSION, "env_name": "PROD", "dialect": "oracle", "schema": None,
        "tables": {}, "views": {}, "sequences": {}, "synonyms": {},
    })
    svi = from_dict({
        "format": FORMAT_VERSION, "env_name": "SVI", "dialect": "oracle", "schema": None,
        "tables": {"clienti": {
            "columns": [{"name": "id", "type": "NUMBER(10)", "nullable": False,
                         "server_default": None}],
            "primary_key": ["id"], "indexes": [], "unique_constraints": [],
            "foreign_keys": []}},
        "views": {}, "sequences": {}, "synonyms": {},
    })

    from diffdb.diff_DB import compare_snapshots

    diff = compare_snapshots(svi, prod)
    percorso = tmp_path / "allinea_prod.sql"
    write_sql_script(generate_sql_scripts(diff, "PROD"), str(percorso), "PROD", diff)

    testo = percorso.read_text(encoding="utf-8")
    assert "BEGIN" not in testo
    assert "commit da sola" in testo
