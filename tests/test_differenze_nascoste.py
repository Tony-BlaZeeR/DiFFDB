"""Differenze vere su cui il confronto taceva.

Guasti della stessa forma, trovati con un esame del motore: il confronto
ometteva un dato che il catalogo aveva gia' fornito - dentro la firma di un
oggetto, o del tutto - percio' due oggetti diversi risultavano identici. Per
uno strumento di diff e' il guasto peggiore, piu' grave di un falso allarme:
chi legge "nessuna differenza" si fida e non controlla.

Ogni gruppo di test verifica tre cose, e la seconda e la terza contano quanto
la prima:

- la differenza ora si vede;
- due oggetti identici NON vengono segnalati (altrimenti basterebbe una
  funzione che risponde sempre "diverso");
- un confronto fatto su snapshot salvati da' lo stesso esito di uno fatto dal
  vivo, e uno snapshot in formato vecchio non fa inventare differenze che
  vengono dal file e non dai database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    desc,
    text,
)
from sqlalchemy.dialects import mysql, oracle, postgresql
from sqlalchemy.dialects.mysql import base as mysql_base
from sqlalchemy.dialects.oracle import base as oracle_base

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import (  # noqa: E402
    COMMENT_MISMATCH,
    compare_snapshots,
    generate_rollback_scripts,
    generate_sql_scripts,
)
from diffdb.schema_snapshot import (  # noqa: E402
    SequenceSpec,
    Snapshot,
    fk_signature,
    index_signature,
    take_snapshot,
    type_signature,
)
from diffdb.snapshot_io import from_dict, load, save  # noqa: E402

# I tipi come li costruisce la riflessione, non come li importerebbe un umano:
# `oracle.VARCHAR2` esiste ma la riflessione mappa VARCHAR2 sul VARCHAR
# generico, e un test scritto sulla classe sbagliata non dimostra niente.
NUMBER = oracle_base.OracleDialect.ischema_names["NUMBER"]
ENUM = mysql_base.MySQLDialect.ischema_names["enum"]
MYSQL_INT = mysql_base.MySQLDialect.ischema_names["int"]


def _con_colonna(nome_ambiente: str, dialetto: str, impl, tipo) -> Snapshot:
    snapshot = Snapshot(env_name=nome_ambiente, dialect=dialetto,
                        dialect_impl=impl, metadata=MetaData())
    Table("t", snapshot.metadata,
          Column("id", Integer, primary_key=True),
          Column("c", tipo))
    return snapshot


def _differenze_colonna(tipo1, tipo2, dialetto="oracle", impl=None) -> list:
    impl = impl if impl is not None else oracle.dialect()
    a = _con_colonna("SVI", dialetto, impl, tipo1)
    b = _con_colonna("PRE", dialetto, impl, tipo2)
    return [d for d in compare_snapshots(a, b).all if d.column == "c"]


# ---------------------------------------------------------------------------
# 1 e 2. I parametri dei tipi che appartengono a un dialetto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tipo1,tipo2,come", [
    (NUMBER(10, 2), NUMBER(38, 0), "precisione e scala diverse"),
    (NUMBER(10, 2), NUMBER(10, 4), "solo la scala diversa"),
    (NUMBER(5), NUMBER(22), "solo la precisione diversa"),
])
def test_oracle_number_le_differenze_di_precisione_si_vedono(tipo1, tipo2, come):
    """Il caso piu' grave trovato: `str()` rende `NUMBER(10,2)` come `NUMBER`,
    percio' su Oracle - dove NUMBER e' *il* tipo numerico - una colonna
    allargata o con meno decimali non risultava diversa affatto."""
    assert _differenze_colonna(tipo1, tipo2), come


def test_oracle_number_identico_non_viene_segnalato():
    """L'altra meta': la firma piu' ricca non deve generare falsi allarmi."""
    assert not _differenze_colonna(NUMBER(10, 2), NUMBER(10, 2))


@pytest.mark.parametrize("tipo1,tipo2,come", [
    (ENUM("a", "b"), ENUM("x", "y"), "etichette diverse"),
    (ENUM("attivo"), ENUM("ATTIVO"), "etichette che differiscono per le maiuscole"),
    (ENUM("a"), ENUM("a", "b"), "un valore ammesso in piu'"),
    (MYSQL_INT(unsigned=True), MYSQL_INT(), "UNSIGNED contro con segno"),
])
def test_mysql_le_differenze_nei_tipi_si_vedono(tipo1, tipo2, come):
    """Stessa radice su MySQL. Il caso delle maiuscole merita attenzione a
    parte: la firma viene messa in maiuscolo per non dipendere da come il
    dialetto scrive `varchar`, ma le etichette di un ENUM stanno fra apici e
    contano, esattamente come le stringhe in `normalize_sql`."""
    assert _differenze_colonna(tipo1, tipo2, "mysql", mysql.dialect()), come


def test_mysql_enum_identico_non_viene_segnalato():
    assert not _differenze_colonna(ENUM("a", "b"), ENUM("a", "b"),
                                   "mysql", mysql.dialect())


def test_fra_dialetti_diversi_resta_la_forma_generica():
    """Le forme native non sono confrontabili fra motori diversi
    (`VARCHAR(50)` contro `VARCHAR2(50 CHAR)`): una differenza su *ogni*
    colonna sarebbe peggio del difetto che si sta correggendo. Con dialetti
    diversi si torna alla forma generica."""
    a = _con_colonna("ORA", "oracle", oracle.dialect(), NUMBER(10, 2))
    b = _con_colonna("PG", "postgresql", None, NUMBER(10, 2))
    assert not [d for d in compare_snapshots(a, b).all if d.column == "c"]


def test_senza_dialetto_la_firma_e_quella_di_prima():
    """Il comportamento storico resta disponibile e invariato."""
    class Finta:
        type = NUMBER(10, 2)

    assert type_signature(Finta()) == "NUMBER"


# ---------------------------------------------------------------------------
# 3 e 4. Azioni delle chiavi esterne, ordinamento e condizione degli indici
# ---------------------------------------------------------------------------

def _con_vincoli(nome_ambiente: str, ondelete=None, onupdate=None,
                 discendente=False, dove=None) -> Snapshot:
    snapshot = Snapshot(env_name=nome_ambiente, dialect="postgresql",
                        metadata=MetaData())
    Table("reparti", snapshot.metadata, Column("id", Integer, primary_key=True))
    tabella = Table(
        "imp", snapshot.metadata,
        Column("id", Integer, primary_key=True),
        Column("a", Integer),
        Column("stato", String(10)),
        Column("r", Integer),
        ForeignKeyConstraint(["r"], ["reparti.id"], name="fk_r",
                            ondelete=ondelete, onupdate=onupdate),
    )
    Index("ix_a", desc(tabella.c.a) if discendente else tabella.c.a,
          **({"postgresql_where": text(dove)} if dove else {}))
    return snapshot


def _differenze_vincoli(uno: Snapshot, due: Snapshot) -> list:
    return [d for d in compare_snapshots(uno, due).all
            if d.kind in ("foreign_key", "index")]


@pytest.mark.parametrize("primo,secondo,come", [
    ({"ondelete": "CASCADE"}, {"ondelete": "RESTRICT"}, "ON DELETE diverso"),
    ({"ondelete": "CASCADE"}, {}, "ON DELETE contro nessuna azione"),
    ({"onupdate": "CASCADE"}, {}, "ON UPDATE contro nessuna azione"),
    ({"discendente": True}, {}, "indice DESC contro ASC"),
    ({"dove": "stato = 'x'"}, {}, "indice parziale contro indice pieno"),
    ({"dove": "stato = 'x'"}, {"dove": "stato = 'y'"}, "condizioni diverse"),
])
def test_gli_attributi_dei_vincoli_si_confrontano(primo, secondo, come):
    """`ON DELETE CASCADE` contro `RESTRICT` cambia cosa succede ai dati, e non
    veniva segnalato. Un indice parziale fa un lavoro diverso da uno pieno
    sulle stesse colonne, e nemmeno quello."""
    assert _differenze_vincoli(_con_vincoli("SVI", **primo),
                               _con_vincoli("PRE", **secondo)), come


def test_vincoli_identici_non_vengono_segnalati():
    assert not _differenze_vincoli(_con_vincoli("SVI", ondelete="CASCADE"),
                                   _con_vincoli("PRE", ondelete="CASCADE"))


def test_l_identita_non_comprende_gli_attributi():
    """Guardiano di progetto, non di comportamento.

    Queste firme sono anche la chiave con cui la generazione degli script
    ritrova l'oggetto da ricreare (`diff_DB` le ricalcola e le confronta con
    il dettaglio della differenza). Se un giorno qualcuno ci infilasse dentro
    le azioni o la condizione, quella ricerca smetterebbe di trovare
    l'oggetto **in silenzio**: nessun test di comportamento se ne
    accorgerebbe. Per questo gli attributi si confrontano a parte.
    """
    tabella = _con_vincoli("SVI", ondelete="CASCADE", discendente=True,
                           dove="stato = 'x'").table("imp")

    firma_fk = fk_signature(next(iter(tabella.foreign_key_constraints)))
    firma_indice = index_signature(next(iter(tabella.indexes)))

    assert firma_fk == "(r) -> (reparti.id)"
    assert "CASCADE" not in firma_fk
    assert firma_indice == "(a)"
    assert "DESC" not in firma_indice and "WHERE" not in firma_indice


# ---------------------------------------------------------------------------
# 5 e 6. Sequenze
# ---------------------------------------------------------------------------

def _con_sequenza(nome_ambiente: str, spec: SequenceSpec) -> Snapshot:
    snapshot = Snapshot(env_name=nome_ambiente, dialect="postgresql",
                        metadata=MetaData())
    snapshot.sequences = {"s": spec}
    return snapshot


def _differenze_sequenza(spec1: SequenceSpec, spec2: SequenceSpec) -> list:
    return compare_snapshots(_con_sequenza("SVI", spec1),
                             _con_sequenza("PRE", spec2)).all


@pytest.mark.parametrize("primo,secondo,come", [
    ({"maxvalue": 1000}, {"maxvalue": 9999999999}, "tetto diverso"),
    ({"minvalue": -100}, {"minvalue": 0}, "pavimento diverso"),
    ({"maxvalue": 1000}, {}, "tetto contro nessun tetto"),
])
def test_minvalue_e_maxvalue_si_confrontano(primo, secondo, come):
    """Erano gia' letti dal catalogo e messi nello snapshot, ma restavano
    fuori dalla firma: dati raccolti e poi buttati via."""
    assert _differenze_sequenza(SequenceSpec("s", **primo),
                                SequenceSpec("s", **secondo)), come


def test_sequenze_identiche_non_vengono_segnalate():
    valori = {"start": 5, "increment": 2, "minvalue": 1, "maxvalue": 99}
    assert not _differenze_sequenza(SequenceSpec("s", **valori),
                                    SequenceSpec("s", **valori))


def test_i_valori_non_letti_vengono_dichiarati_non_confrontati():
    """Quando il catalogo non risponde si conoscono solo i nomi, e i valori
    restano i predefiniti della dataclass. Confrontarli come se fossero veri
    dava un verdetto casuale: una differenza che nessuno aveva verificato, o
    il silenzio su una differenza che non si era in grado di vedere."""
    differenze = _differenze_sequenza(SequenceSpec("s", start=500, increment=10),
                                      SequenceSpec("s", valori_letti=False))

    assert len(differenze) == 1
    assert "non confrontati" in differenze[0].detail
    assert "PRE" in differenze[0].detail


def test_i_valori_predefiniti_non_tacciono_piu_per_caso():
    """Il caso peggiore del ripiego: una sequenza vera con START 1 INCREMENT 1
    combaciava per caso con i predefiniti, e il confronto taceva pur non
    avendo letto niente."""
    assert _differenze_sequenza(SequenceSpec("s", start=1, increment=1),
                                SequenceSpec("s", valori_letti=False))


# ---------------------------------------------------------------------------
# Snapshot su file: stesso esito del vivo, e nessuna differenza dal formato
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("costruisci", [
    lambda: _con_colonna("SVI", "oracle", oracle.dialect(), NUMBER(10, 2)),
    lambda: _con_colonna("SVI", "mysql", mysql.dialect(), ENUM("a", "b")),
    lambda: _con_vincoli("SVI", ondelete="CASCADE"),
    lambda: _con_vincoli("SVI", discendente=True),
    lambda: _con_vincoli("SVI", dove="stato = 'x'"),
    lambda: _con_sequenza("SVI", SequenceSpec("s", maxvalue=1000)),
    lambda: _con_sequenza("SVI", SequenceSpec("s", valori_letti=False)),
    lambda: _con_commenti("SVI", tabella="anagrafica", colonna="stato"),
])
def test_salvare_e_rileggere_non_cambia_il_confronto(tmp_path, costruisci):
    """Un confronto su snapshot salvati deve dare lo stesso esito di uno fatto
    dal vivo. Senza questo, ogni dato aggiunto alla firma diventa una
    differenza fantasma appena si lavora su file.

    Il confronto e' col vivo contro se stesso, non con la lista vuota: una
    sequenza di cui non si sono letti i valori dichiara "non confrontati" in
    entrambi i casi, e questo e' l'esito giusto, non una differenza fantasma.
    """
    vivo = costruisci()
    riletto = load(save(vivo, tmp_path / "s.json"))

    atteso = [(d.kind, d.name, d.column, d.change)
              for d in compare_snapshots(vivo, vivo).all]
    ottenuto = [(d.kind, d.name, d.column, d.change)
                for d in compare_snapshots(vivo, riletto).all]

    assert ottenuto == atteso


def test_uno_snapshot_in_formato_vecchio_non_inventa_differenze():
    """Gli snapshot salvati prima non contengono azioni referenziali ne'
    dettagli degli indici. Confrontarli con uno letto dal vivo darebbe
    "ON DELETE CASCADE" da una parte e "nessuna azione" dall'altra: una
    differenza prodotta dal formato del file, non dai database. In quel caso
    non si confrontano, e il log lo dice."""
    vivo = _con_vincoli("SVI", ondelete="CASCADE", discendente=True)
    vecchio = from_dict({
        "format": 1,
        "dialect": "postgresql",
        "env_name": "VECCHIO",
        "tables": {
            "reparti": {"columns": [{"name": "id", "type": "INTEGER",
                                     "nullable": False}],
                        "primary_key": ["id"]},
            "imp": {"columns": [{"name": "id", "type": "INTEGER",
                                 "nullable": False},
                                {"name": "a", "type": "INTEGER"},
                                {"name": "stato", "type": "VARCHAR(10)"},
                                {"name": "r", "type": "INTEGER"}],
                    "primary_key": ["id"],
                    "foreign_keys": [{"name": "fk_r", "columns": ["r"],
                                      "refers_to": ["reparti.id"]}],
                    "indexes": [{"name": "ix_a", "columns": ["a"],
                                 "unique": False}]},
        },
    })

    assert _differenze_vincoli(vivo, vecchio) == []


@pytest.mark.parametrize("primo,secondo,atteso", [
    ({"ondelete": "CASCADE"}, {"ondelete": "RESTRICT"}, "azioni referenziali"),
    ({"discendente": True}, {}, "ordinamento o condizione"),
    ({"dove": "stato = 'x'"}, {}, "ordinamento o condizione"),
])
def test_lo_script_non_tace_sulle_differenze_di_attributo(primo, secondo, atteso):
    """Una differenza segnalata e poi assente dallo script e' una trappola.

    Questi oggetti ci sono in entrambi gli ambienti e combaciano per colonne,
    percio' hanno `missing_in` vuoto e la generazione li saltava senza
    scrivere niente: l'utente vedeva la differenza nel report e non trovava
    nulla nello script, senza una riga che lo spiegasse. Allinearli richiede
    di eliminarli e ricrearli, cosa che va decisa da chi conosce la finestra
    di manutenzione, quindi lo script lo dichiara invece di inventare un DDL.
    """
    sorgente = _con_vincoli("SVI", **primo)
    bersaglio = _con_vincoli("PRE", **secondo)
    sorgente.dialect_impl = bersaglio.dialect_impl = postgresql.dialect()

    diff = compare_snapshots(sorgente, bersaglio)
    righe = [r for r in generate_sql_scripts(diff, "PRE")["constraints"] if r]

    assert righe, "lo script non dice niente di una differenza segnalata"
    assert any(atteso in r for r in righe)


def test_lo_snapshot_nuovo_dichiara_di_avere_gli_attributi():
    """Il contrario del test precedente: uno snapshot scritto da questa
    versione deve dichiararsi completo, altrimenti i confronti su file
    resterebbero ciechi per sempre."""
    assert from_dict({"format": 2, "dialect": "postgresql",
                      "env_name": "NUOVO"}).attributi_vincoli_letti
    assert not from_dict({"format": 1, "dialect": "postgresql",
                          "env_name": "VECCHIO"}).attributi_vincoli_letti


# ---------------------------------------------------------------------------
# 7. I commenti di tabelle e colonne
# ---------------------------------------------------------------------------
#
# Il commento del catalogo e' quello che un collega legge per capire a cosa
# serve una tabella o cosa significa una colonna. Non veniva confrontato
# affatto: due ambienti che documentano la stessa colonna in modo diverso -
# o uno dei due che non la documenta - risultavano identici.

def _con_commenti(nome_ambiente: str, tabella=None, colonna=None) -> Snapshot:
    snapshot = Snapshot(env_name=nome_ambiente, dialect="postgresql",
                        dialect_impl=postgresql.dialect(), metadata=MetaData())
    Table("clienti", snapshot.metadata,
          Column("id", Integer, primary_key=True),
          Column("stato", String(10), comment=colonna),
          comment=tabella)
    return snapshot


def _differenze_commento(primo: dict, secondo: dict) -> list:
    diff = compare_snapshots(_con_commenti("SVI", **primo),
                             _con_commenti("PRE", **secondo))
    return [d for d in diff.all if d.change == COMMENT_MISMATCH]


@pytest.mark.parametrize("primo,secondo,come", [
    ({"tabella": "anagrafica clienti"}, {}, "commento della tabella solo da una parte"),
    ({"tabella": "clienti attivi"}, {"tabella": "tutti i clienti"},
     "commento della tabella diverso"),
    ({"colonna": "A=attivo, S=sospeso"}, {}, "commento della colonna solo da una parte"),
    ({"colonna": "A=attivo"}, {"colonna": "1=attivo"}, "commento della colonna diverso"),
])
def test_i_commenti_si_confrontano(primo, secondo, come):
    assert _differenze_commento(primo, secondo), come


@pytest.mark.parametrize("uguali", [
    {"tabella": "anagrafica", "colonna": "stato del cliente"},
    {},                                    # nessun commento da nessuna parte
    {"tabella": "  spazi attorno  "},      # gli spazi di contorno non contano
])
def test_commenti_identici_non_vengono_segnalati(uguali):
    assert _differenze_commento(uguali, uguali) == []


def test_dove_i_commenti_non_si_leggono_non_si_confrontano():
    """SQLite non ha i commenti nel catalogo: chiederglieli non da' errore, da'
    sempre None. Confrontare quel None con i commenti veri di un altro motore
    direbbe che ogni tabella ha perso il commento - una differenza inventata
    dallo strumento, non dai database."""
    commentato = _con_commenti("PG", tabella="anagrafica", colonna="stato")
    cieco = _con_commenti("LITE")
    cieco.dialect, cieco.commenti_letti = "sqlite", False

    diff = compare_snapshots(commentato, cieco)
    assert [d for d in diff.all if d.change == COMMENT_MISMATCH] == []


def test_su_sqlite_lo_snapshot_si_dichiara_cieco_sui_commenti():
    """La riga sopra vale solo se il flag si imposta da se' leggendo
    l'ambiente: qui si verifica sul motore vero, non a mano."""
    assert not take_snapshot("LITE", create_engine("sqlite://")).commenti_letti


def test_uno_snapshot_in_formato_vecchio_non_inventa_commenti():
    """Gli snapshot salvati prima non contengono i commenti: valgono come
    "non si sa", non come "nessun commento"."""
    vivo = _con_commenti("SVI", tabella="anagrafica", colonna="stato")
    vecchio = from_dict({
        "format": 1, "dialect": "postgresql", "env_name": "VECCHIO",
        "tables": {"clienti": {
            "columns": [{"name": "id", "type": "INTEGER", "nullable": False},
                        {"name": "stato", "type": "VARCHAR(10)"}],
            "primary_key": ["id"]}},
    })

    diff = compare_snapshots(vivo, vecchio)
    assert [d for d in diff.all if d.change == COMMENT_MISMATCH] == []


@pytest.mark.parametrize("primo,secondo,atteso", [
    ({"tabella": "anagrafica clienti"}, {},
     "COMMENT ON TABLE clienti IS 'anagrafica clienti';"),
    ({"colonna": "A=attivo"}, {},
     "COMMENT ON COLUMN clienti.stato IS 'A=attivo';"),
    ({}, {"tabella": "da cancellare"}, "COMMENT ON TABLE clienti IS NULL;"),
    ({"tabella": "l'anagrafica"}, {},
     "COMMENT ON TABLE clienti IS 'l''anagrafica';"),
])
def test_lo_script_allinea_i_commenti(primo, secondo, atteso):
    """Un commento si allinea con un'istruzione sola e senza rischi: non c'e'
    motivo di lasciarlo come nota da fare a mano. L'apice dentro al testo va
    raddoppiato, o l'istruzione si spezza a meta'."""
    diff = compare_snapshots(_con_commenti("SVI", **primo),
                             _con_commenti("PRE", **secondo))
    assert atteso in generate_sql_scripts(diff, "PRE")["tables"]


def test_lo_script_di_annullamento_rimette_il_commento_di_prima():
    diff = compare_snapshots(_con_commenti("SVI", tabella="nuovo"),
                             _con_commenti("PRE", tabella="quello di prima"))
    righe = generate_rollback_scripts(diff, "PRE")["tables"]

    assert "COMMENT ON TABLE clienti IS 'quello di prima';" in righe


def test_dove_il_commento_non_si_cambia_con_una_istruzione_lo_dice():
    """Su MySQL il commento di una colonna sta dentro la sua definizione:
    cambiarlo vuol dire riscrivere la colonna con MODIFY e perdere quello che
    non si ripete. Si dichiara invece di rischiare."""
    sorgente = _con_commenti("SVI", colonna="A=attivo")
    bersaglio = _con_commenti("PRE")
    for snap in (sorgente, bersaglio):
        snap.dialect, snap.dialect_impl = "mysql", mysql.dialect()

    righe = generate_sql_scripts(compare_snapshots(sorgente, bersaglio), "PRE")["tables"]
    assert any("va fatto a mano" in r for r in righe)
