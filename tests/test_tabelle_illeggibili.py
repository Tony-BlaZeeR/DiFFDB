"""Una tabella che non si legge non deve far cadere tutto il confronto.

La riflessione in blocco e' una sola istruzione: basta una tabella con un
riferimento rotto, un tipo che il dialetto non sa ricostruire o un permesso
che manca, e saltava l'intera fotografia dell'ambiente - quindi il confronto
di tutto lo schema, anche delle centinaia di tabelle sane. Su uno strumento
che si usa prima di un rilascio e' la differenza fra "ecco le differenze" e
"non ho potuto dirti niente".

Il caso qui riprodotto e' vero e si ottiene con SQLite puro: una tabella con
una foreign key che punta a una tabella che non esiste. SQLite la lascia
creare, SQLAlchemy non la sa riflettere, e l'errore arriva a meta' della
lettura in blocco - portandosi via anche le tabelle che venivano dopo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import (  # noqa: E402
    MISSING,
    UNREADABLE,
    compare_snapshots,
    generate_sql_scripts,  # noqa: E402
)
from diffdb.schema_snapshot import take_snapshot  # noqa: E402
from diffdb.snapshot_io import from_dict, to_dict  # noqa: E402

BUONA = "CREATE TABLE buona (id INTEGER PRIMARY KEY, x TEXT)"
ALTRA = "CREATE TABLE altra (id INTEGER PRIMARY KEY)"
# "rotta" sta in mezzo di proposito: in ordine alfabetico viene fra le altre
# due, cosi' si vede che l'errore si portava via anche quelle successive.
ROTTA = ("CREATE TABLE rotta (id INTEGER PRIMARY KEY, "
         "y INTEGER REFERENCES assente(id))")


def _ambiente(istruzioni) -> object:
    motore = create_engine("sqlite://")
    with motore.begin() as conn:
        for istruzione in istruzioni:
            conn.exec_driver_sql(istruzione)
    return motore


def test_la_riflessione_in_blocco_da_sola_fallirebbe():
    """Il guasto, prima della correzione: una sola istruzione per tutte le
    tabelle, e con essa l'intero snapshot."""
    motore = _ambiente([BUONA, ROTTA, ALTRA])
    with pytest.raises(SQLAlchemyError):
        MetaData().reflect(bind=motore, views=False,
                           only=["altra", "buona", "rotta"])


def test_le_tabelle_sane_si_leggono_comunque():
    snapshot = take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA]))

    assert sorted(snapshot.tables) == ["altra", "buona"]
    assert list(snapshot.tabelle_illeggibili) == ["rotta"]
    assert "assente" in snapshot.tabelle_illeggibili["rotta"]


def test_senza_tabelle_rotte_non_cambia_niente():
    """La strada veloce resta quella in blocco: il ripiego serve solo quando
    serve, e non deve lasciare tracce quando non serve."""
    snapshot = take_snapshot("SVI", _ambiente([BUONA, ALTRA]))

    assert sorted(snapshot.tables) == ["altra", "buona"]
    assert snapshot.tabelle_illeggibili == {}


def test_la_tabella_illeggibile_viene_dichiarata():
    """Il buco va detto: chi legge il report lo prenderebbe per completo."""
    diff = compare_snapshots(take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA])),
                             take_snapshot("PRE", _ambiente([BUONA, ALTRA])))

    righe = [d for d in diff.all if d.change == UNREADABLE]
    assert [(d.kind, d.name, d.present_in) for d in righe] == [
        ("table", "rotta", "SVI")]
    assert "non confrontata" in righe[0].detail


def test_non_viene_spacciata_per_mancante():
    """La bugia da evitare: "rotta" c'e' in SVI, non si e' potuta leggere.
    Dire "mancante in PRE" mandava a cercare una differenza inesistente, e
    dire "mancante in SVI" sarebbe stato il contrario del vero."""
    diff = compare_snapshots(take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA])),
                             take_snapshot("PRE", _ambiente([BUONA, ALTRA])))

    assert [d.name for d in diff.all if d.change == MISSING] == []


def test_le_differenze_vere_si_vedono_ancora():
    """Il punto di tutto: le altre tabelle si confrontano come sempre."""
    diff = compare_snapshots(
        take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA])),
        take_snapshot("PRE", _ambiente([BUONA])))

    mancanti = [(d.name, d.missing_in) for d in diff.all if d.change == MISSING]
    assert mancanti == [("altra", "PRE")]


def test_lo_script_dichiara_quello_che_non_ha_confrontato():
    diff = compare_snapshots(take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA])),
                             take_snapshot("PRE", _ambiente([BUONA, ALTRA])))

    righe = generate_sql_scripts(diff, "PRE")["tables"]
    assert any("rotta" in r and "non e' stata letta" in r for r in righe)


def test_il_buco_sopravvive_al_salvataggio_su_file():
    """Uno snapshot salvato deve dire da solo cosa non contiene, o un
    confronto fatto su file tornerebbe a tacere."""
    snapshot = take_snapshot("SVI", _ambiente([BUONA, ROTTA, ALTRA]))
    ricostruito = from_dict(to_dict(snapshot), origin="prova")

    assert ricostruito.tabelle_illeggibili == snapshot.tabelle_illeggibili
