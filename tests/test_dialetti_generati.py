"""Il SQL generato per ogni dialetto, verificato senza un database.

I test di integrazione girano sui motori veri, ma tre dei quattro dialetti non
li ha ancora eseguiti nessuno. Questi test sono la rete piu' fitta che si possa
stendere senza un server: costruiscono uno scenario completo — tabella mancante
con foreign key, colonna mancante, tipo diverso, nullability, default, indice,
unique, vista, sequenza, sinonimo — e verificano la *forma* di quello che esce.

Non sostituiscono l'esecuzione vera: un `ALTER TABLE` sintatticamente perfetto
puo' comunque essere rifiutato. Ma un segnaposto non sostituito o un punto e
virgola mancante li prendono qui, invece che al primo tag.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.config.dialectConfig import SUPPORTED_DIALECTS, templates_for
from diffdb.diff_DB import compare_snapshots, generate_sql_scripts
from diffdb.snapshot_io import FORMAT_VERSION, from_dict

# Tipi equivalenti, come li scriverebbe ciascun motore.
TIPI = {
    "postgresql": {"intero": "INTEGER", "testo": "VARCHAR({n})", "decimale": "NUMERIC(10, 2)"},
    "mysql": {"intero": "INTEGER", "testo": "VARCHAR({n})", "decimale": "DECIMAL(10, 2)"},
    "mssql": {"intero": "INT", "testo": "VARCHAR({n})", "decimale": "NUMERIC(10, 2)"},
    "oracle": {"intero": "NUMBER(10)", "testo": "VARCHAR2({n})", "decimale": "NUMBER(10, 2)"},
    "sqlite": {"intero": "INTEGER", "testo": "VARCHAR({n})", "decimale": "NUMERIC(10, 2)"},
}

DIALETTI = sorted(SUPPORTED_DIALECTS)


def _colonna(nome, tipo, nullable=True, default=None, autoincrement=False):
    return {"name": nome, "type": tipo, "nullable": nullable,
            "server_default": default, "autoincrement": autoincrement}


def _snapshot(env_name, dialetto, *, completo, schema=None):
    """Due varianti dello stesso schema: 'completo' e' il riferimento."""
    t = TIPI[dialetto]
    clienti = {
        "columns": [
            _colonna("id", t["intero"], nullable=False),
            # Tipo diverso fra i due ambienti: 50 contro 30.
            _colonna("nome", t["testo"].format(n=50 if completo else 30), nullable=False),
            _colonna("attivo", t["intero"], nullable=False, default="1" if completo else "0"),
            # Nullability diversa.
            _colonna("codice", t["testo"].format(n=10), nullable=not completo),
        ] + ([_colonna("email", t["testo"].format(n=120))] if completo else []),
        "primary_key": ["id"],
        "indexes": [{"name": "ix_clienti_email", "columns": ["email"], "unique": False}]
        if completo else [],
        "unique_constraints": [{"name": "uq_clienti_codice", "columns": ["codice"]}]
        if completo else [],
        "foreign_keys": [],
    }

    tabelle = {"clienti": clienti}
    if completo:
        # Tabella mancante nell'altro ambiente, con una foreign key: e' quella
        # che mette alla prova l'ordine di creazione.
        tabelle["ordini"] = {
            "columns": [_colonna("id", t["intero"], nullable=False),
                        _colonna("cliente_id", t["intero"], nullable=False),
                        _colonna("totale", t["decimale"])],
            "primary_key": ["id"],
            "indexes": [],
            "unique_constraints": [],
            # Il bersaglio porta lo schema quando c'e': e' la forma che
            # SQLAlchemy restituisce riflettendo un ambiente con schema.
            "foreign_keys": [{
                "name": "fk_ordini_clienti", "columns": ["cliente_id"],
                "refers_to": [f"{schema}.clienti.id" if schema else "clienti.id"]}],
        }

    return from_dict({
        "format": FORMAT_VERSION,
        "env_name": env_name,
        "dialect": dialetto,
        "schema": schema,
        "tables": tabelle,
        "views": {"clienti_attivi": "SELECT id, nome FROM clienti"} if completo else {},
        "sequences": {"seq_clienti": {"start": 100, "increment": 5, "minvalue": 1,
                                      "maxvalue": 9999, "cycle": False}} if completo else {},
        "synonyms": {"cli": "app.clienti"} if completo else {},
    })


def _script(dialetto, schema=None):
    riferimento = _snapshot("SVI", dialetto, completo=True, schema=schema)
    da_allineare = _snapshot("COL", dialetto, completo=False, schema=schema)
    return generate_sql_scripts(compare_snapshots(riferimento, da_allineare), "COL")


def _istruzioni(scripts):
    """Le righe che finirebbero davvero nel database, senza i commenti."""
    return [s for blocco in scripts.values() for s in blocco if not s.startswith("--")]


# --- forma delle istruzioni -------------------------------------------------


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_nessun_segnaposto_resta_da_sostituire(dialetto):
    """Un template con un {campo} che nessuno riempie produce SQL rotto, e nel
    file sembra a posto finche' non lo esegui."""
    for istruzione in _istruzioni(_script(dialetto)):
        residui = re.findall(r"\{[a-z_]+\}", istruzione)
        assert not residui, f"{dialetto}: segnaposto non sostituiti {residui} in {istruzione!r}"


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_ogni_istruzione_finisce_con_il_punto_e_virgola(dialetto):
    for istruzione in _istruzioni(_script(dialetto)):
        assert istruzione.rstrip().endswith(";"), f"{dialetto}: {istruzione!r}"


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_lo_scenario_produce_qualcosa_su_ogni_dialetto(dialetto):
    """Se un dialetto smettesse di generare niente, gli altri test passerebbero
    a vuoto senza accorgersene."""
    assert len(_istruzioni(_script(dialetto))) >= 3


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_le_tabelle_precedono_i_vincoli_che_le_usano(dialetto):
    scripts = _script(dialetto)
    creazioni = [s for s in scripts["tables"] if s.startswith("CREATE TABLE")]
    if creazioni:
        # Gli indici e i vincoli stanno in una sezione che viene scritta dopo.
        assert list(scripts).index("tables") < list(scripts).index("constraints")


# --- particolarita' di ogni dialetto ----------------------------------------


def _modify(dialetto):
    return [s for s in _script(dialetto)["tables"] if "nome" in s and not s.startswith("--")]


def test_oracle_non_scrive_add_column():
    """Su Oracle e' 'ALTER TABLE t ADD c tipo', senza la parola COLUMN."""
    aggiunte = [s for s in _script("oracle")["tables"] if "email" in s]
    assert aggiunte and all("ADD COLUMN" not in s for s in aggiunte)


@pytest.mark.parametrize("dialetto", ["mysql", "mssql"])
def test_dove_la_colonna_si_riscrive_il_not_null_si_ripete(dialetto):
    """MySQL e SQL Server riscrivono la colonna da capo: quello che non si
    ripete va perso."""
    assert all("NOT NULL" in s for s in _modify(dialetto))


def test_postgresql_non_mette_il_not_null_nel_cambio_di_tipo():
    """ALTER COLUMN ... TYPE non accetta la clausola."""
    assert all("NOT NULL" not in s for s in _modify("postgresql"))


def test_oracle_non_ripete_un_not_null_che_non_cambia():
    """Ripeterlo solleva ORA-01442."""
    assert all("NOT NULL" not in s for s in _modify("oracle"))


@pytest.mark.parametrize("dialetto", ["postgresql", "oracle", "mssql"])
def test_le_sequenze_si_creano_dove_esistono(dialetto):
    sequenze = _script(dialetto)["sequences"]
    assert any(s.startswith("CREATE SEQUENCE") for s in sequenze)
    # I valori veri, non START WITH 1.
    assert any("100" in s and "5" in s for s in sequenze)


def test_mysql_dichiara_che_non_ha_le_sequenze():
    sequenze = _script("mysql")["sequences"]
    assert sequenze and all(s.startswith("--") for s in sequenze)


@pytest.mark.parametrize("dialetto", ["oracle", "mssql"])
def test_i_sinonimi_si_creano_dove_esistono(dialetto):
    assert any(s.startswith("CREATE SYNONYM") for s in _script(dialetto)["synonyms"])


@pytest.mark.parametrize("dialetto", ["postgresql", "mysql"])
def test_dove_i_sinonimi_non_esistono_lo_script_lo_dice(dialetto):
    sinonimi = _script(dialetto)["synonyms"]
    assert sinonimi and all(s.startswith("--") for s in sinonimi)


def test_sqlite_dichiara_di_non_saper_aggiungere_vincoli():
    """SQLite non ha ALTER TABLE ADD CONSTRAINT: va detto, non generato."""
    vincoli = _script("sqlite")["constraints"]
    assert any("non sa aggiungere vincoli" in s for s in vincoli)


# --- schema -----------------------------------------------------------------


@pytest.mark.parametrize("dialetto", ["postgresql", "oracle", "mssql"])
def test_con_uno_schema_gli_alter_sono_qualificati(dialetto):
    """Senza qualificazione l'ALTER finisce sulla tabella omonima dello schema
    di default dell'utente connesso."""
    alter = [s for s in _script(dialetto, schema="APP")["tables"]
             if s.startswith("ALTER TABLE")]
    assert alter
    for istruzione in alter:
        bersaglio = istruzione.split()[2]
        assert "APP" in bersaglio, f"{dialetto}: {istruzione!r}"


# --- coerenza delle capacita' dichiarate ------------------------------------


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_ogni_dialetto_dichiara_tutte_le_capacita(dialetto):
    """Una capacita' mancante diventa un KeyError al momento peggiore: mentre
    si genera lo script per un ambiente di produzione."""
    attese = {"add", "modify", "drop", "set_default", "drop_default", "modify_nullability",
              "alter_add_constraint", "view_or_replace", "sequences", "alter_sequence",
              "create_synonym", "begin", "commit"}
    assert attese <= set(templates_for(dialetto))
