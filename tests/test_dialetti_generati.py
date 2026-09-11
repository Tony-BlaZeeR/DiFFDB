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
              "create_synonym", "begin", "commit",
              "drop_table", "drop_index", "drop_constraint", "drop_foreign_key",
              "drop_check", "drop_view", "drop_sequence", "drop_synonym"}
    assert attese <= set(templates_for(dialetto))


# --- casi trovati dalla prima esecuzione sui motori veri ---------------------


def test_la_vista_di_mysql_non_viene_avvolta_due_volte():
    """MySQL restituisce la definizione completa con le sue clausole in mezzo.

    Senza riconoscerle, il risultato era
    `CREATE VIEW x AS CREATE ALGORITHM=... VIEW ...`, che non e' SQL valido.
    """
    from diffdb.diff_DB import VIEW_HEADER

    definizione = ("CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`%` "
                   "SQL SECURITY DEFINER VIEW `clienti_attivi` AS select 1")
    assert VIEW_HEADER.match(definizione)


@pytest.mark.parametrize("definizione", [
    "CREATE VIEW v AS SELECT 1",
    "CREATE OR REPLACE VIEW v AS SELECT 1",
    "CREATE TEMPORARY VIEW v AS SELECT 1",
    "CREATE ALGORITHM=MERGE VIEW v AS SELECT 1",
    "CREATE DEFINER=`app`@`localhost` SQL SECURITY INVOKER VIEW v AS SELECT 1",
])
def test_le_intestazioni_di_vista_note_vengono_riconosciute(definizione):
    from diffdb.diff_DB import VIEW_HEADER

    assert VIEW_HEADER.match(definizione)


def test_il_corpo_di_una_select_non_e_un_intestazione():
    """PostgreSQL e Oracle restituiscono solo la SELECT: va avvolta."""
    from diffdb.diff_DB import VIEW_HEADER

    assert not VIEW_HEADER.match("SELECT id, nome FROM clienti")


def test_il_tipo_con_collation_si_confronta_generico_e_si_scrive_nativo():
    """Su SQL Server str() rende VARCHAR(120) COLLATE "...", con le virgolette,
    che in un ALTER TABLE il server rifiuta. Il confronto usa la prima forma,
    il DDL la seconda."""
    from diffdb.snapshot_io import type_from_text

    generico = 'VARCHAR(120) COLLATE "SQL_Latin1_General_CP1_CI_AS"'
    nativo = "VARCHAR(120) COLLATE SQL_Latin1_General_CP1_CI_AS"

    tipo = type_from_text(generico, nativo)

    assert str(tipo) == generico                       # per il confronto
    assert tipo.get_col_spec() == nativo               # per il DDL


def test_senza_forma_nativa_il_tipo_resta_quello_di_prima():
    """Gli snapshot gia' salvati non hanno il campo: devono continuare a valere."""
    from diffdb.snapshot_io import type_from_text

    tipo = type_from_text("VARCHAR2(50)")
    assert str(tipo) == tipo.get_col_spec() == "VARCHAR2(50)"


# --- annullamento -----------------------------------------------------------


def _annulla(dialetto, schema=None):
    from diffdb.diff_DB import generate_rollback_scripts

    riferimento = _snapshot("SVI", dialetto, completo=True, schema=schema)
    da_allineare = _snapshot("COL", dialetto, completo=False, schema=schema)
    return generate_rollback_scripts(compare_snapshots(riferimento, da_allineare), "COL")


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_l_annullamento_non_lascia_segnaposto(dialetto):
    for istruzione in _istruzioni(_annulla(dialetto)):
        residui = re.findall(r"\{[a-z_]+\}", istruzione)
        assert not residui, f"{dialetto}: {residui} in {istruzione!r}"


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_l_annullamento_finisce_le_istruzioni(dialetto):
    for istruzione in _istruzioni(_annulla(dialetto)):
        assert istruzione.rstrip().endswith(";"), f"{dialetto}: {istruzione!r}"


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_l_annullamento_toglie_la_tabella_creata(dialetto):
    istruzioni = _istruzioni(_annulla(dialetto))
    assert any(i.startswith("DROP TABLE") and "ordini" in i for i in istruzioni)


@pytest.mark.parametrize("dialetto", DIALETTI)
def test_l_annullamento_non_tocca_cio_che_esisteva_gia(dialetto):
    """Disfare l'allineamento non vuol dire svuotare l'ambiente: 'clienti'
    c'era prima e deve restare."""
    for istruzione in _istruzioni(_annulla(dialetto)):
        assert not (istruzione.startswith("DROP TABLE") and "clienti" in istruzione)


@pytest.mark.parametrize("dialetto, con_tabella", [
    ("postgresql", False),
    ("oracle", False),
    ("sqlite", False),
    ("mysql", True),      # l'indice appartiene alla tabella e va nominata
    ("mssql", True),
])
def test_il_drop_dell_indice_segue_il_dialetto(dialetto, con_tabella):
    drop = [i for i in _istruzioni(_annulla(dialetto)) if i.startswith("DROP INDEX")]
    assert drop, f"{dialetto}: nessun DROP INDEX"
    assert all((" ON " in i) is con_tabella for i in drop), drop


def test_l_annullamento_avvisa_prima_di_perdere_dati():
    """Togliere una colonna aggiunta cancella quello che ci e' stato scritto."""
    avvisi = [i for blocco in _annulla("postgresql").values() for i in blocco
              if i.startswith("--")]
    assert any("cancella i dati" in i for i in avvisi)


def test_l_annullamento_rimette_il_tipo_precedente():
    """Il tipo di prima lo sappiamo: e' quello letto dall'ambiente allineato."""
    modifiche = [i for i in _istruzioni(_annulla("postgresql")) if "nome" in i]
    assert modifiche and all("VARCHAR(30)" in i for i in modifiche), modifiche


# --- vincoli CHECK -----------------------------------------------------------
#
# Scenario a parte (non nel _snapshot() condiviso sopra): un solo vincolo su
# una tabella condivisa da entrambi gli ambienti, cosi' il confronto lo vede
# come "check mancante" e non come parte di una tabella intera mancante.


def _snapshot_check(dialetto, *, con_vincolo, schema=None):
    t = TIPI[dialetto]
    clienti = {
        "columns": [_colonna("id", t["intero"], nullable=False),
                    _colonna("saldo", t["decimale"])],
        "primary_key": ["id"],
        "indexes": [], "unique_constraints": [], "foreign_keys": [],
        "check_constraints": [{"name": "ck_saldo", "sqltext": "saldo >= 0"}]
        if con_vincolo else [],
    }
    return from_dict({
        "format": FORMAT_VERSION, "env_name": "SVI" if con_vincolo else "COL",
        "dialect": dialetto, "schema": schema,
        "tables": {"clienti": clienti}, "views": {}, "sequences": {}, "synonyms": {},
    })


def _script_check(dialetto, schema=None):
    riferimento = _snapshot_check(dialetto, con_vincolo=True, schema=schema)
    da_allineare = _snapshot_check(dialetto, con_vincolo=False, schema=schema)
    return generate_sql_scripts(compare_snapshots(riferimento, da_allineare), "COL")


def _annulla_check(dialetto, schema=None):
    from diffdb.diff_DB import generate_rollback_scripts

    riferimento = _snapshot_check(dialetto, con_vincolo=True, schema=schema)
    da_allineare = _snapshot_check(dialetto, con_vincolo=False, schema=schema)
    return generate_rollback_scripts(compare_snapshots(riferimento, da_allineare), "COL")


@pytest.mark.parametrize("dialetto", [d for d in DIALETTI if d != "sqlite"])
def test_il_check_mancante_genera_add_constraint(dialetto):
    """Sui dialetti che sanno aggiungere vincoli, l'ALTER e' quello standard:
    SQLAlchemy lo compila uguale per tutti e quattro."""
    istruzioni = _istruzioni(_script_check(dialetto))
    assert any(i.startswith("ALTER TABLE") and "ck_saldo" in i and "CHECK" in i
               for i in istruzioni), istruzioni


def test_sqlite_non_confronta_i_check_quindi_non_genera_niente():
    """Su SQLite Snapshot.check_constraints() torna sempre vuoto (la
    riflessione e' inaffidabile): il confronto non vede nemmeno la differenza,
    quindi non c'e' un ALTER da generare ne' un avviso da scrivere — a
    differenza di unique e FK, dove il vincolo si vede ma non si puo' aggiungere."""
    assert _script_check("sqlite")["constraints"] == []


@pytest.mark.parametrize("dialetto", [d for d in DIALETTI if d != "sqlite"])
def test_l_annullamento_toglie_il_check_aggiunto(dialetto):
    istruzioni = _istruzioni(_annulla_check(dialetto))
    assert any("ck_saldo" in i for i in istruzioni), istruzioni


def test_mysql_toglie_il_check_con_drop_check_non_drop_constraint():
    """Su MySQL DROP CONSTRAINT e' riservato all'unicita' (via DROP INDEX): i
    CHECK si tolgono con la sintassi propria, DROP CHECK."""
    istruzioni = _istruzioni(_annulla_check("mysql"))
    drop = next(i for i in istruzioni if "ck_saldo" in i)
    assert drop.startswith("ALTER TABLE clienti DROP CHECK"), drop


@pytest.mark.parametrize("dialetto", ["postgresql", "oracle", "mssql"])
def test_gli_altri_dialetti_usano_drop_constraint_per_il_check(dialetto):
    istruzioni = _istruzioni(_annulla_check(dialetto))
    drop = next(i for i in istruzioni if "ck_saldo" in i)
    assert drop.startswith("ALTER TABLE clienti DROP CONSTRAINT"), drop


def test_con_uno_schema_il_drop_del_check_e_qualificato():
    istruzioni = _istruzioni(_annulla_check("postgresql", schema="APP"))
    drop = next(i for i in istruzioni if "ck_saldo" in i)
    assert "APP" in drop.split()[2], drop

