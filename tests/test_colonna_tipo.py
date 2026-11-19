"""La colonna "Tipo" nell'albero dei risultati.

Dentro la sezione "Indici, chiavi e vincoli" finiscono insieme indici, chiavi
primarie, chiavi esterne, vincoli di unicita' e CHECK: il dato c'era gia' in
Difference.kind ed era gia' nel report Excel, ma l'albero mostrava solo nome
e direzione, quindi non si capiva di quale dei cinque si parlasse.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.qt import QtWidgets  # noqa: E402

# Tutti i kind che diff_DB sa produrre. Se ne nasce uno nuovo senza etichetta,
# la colonna mostrerebbe la chiave grezza ("foreign_key") invece del nome.
TIPI_ATTESI = [
    "table", "column", "index", "primary_key", "foreign_key", "unique",
    "check", "view", "sequence", "synonym", "trigger", "procedure", "function",
]


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def tab(app):
    from diffdb.results_tab import ResultsTab
    return ResultsTab()


def test_ogni_tipo_ha_una_etichetta_leggibile(tab):
    for kind in TIPI_ATTESI:
        etichetta = tab._etichetta_tipo(kind)
        assert etichetta != kind, f"'{kind}' non ha un'etichetta"
        assert "_" not in etichetta, f"'{kind}' mostra la chiave grezza"


def test_i_vincoli_si_distinguono_fra_loro(tab):
    """Il punto dell'aggiunta: dentro una sola sezione, cinque cose diverse."""
    etichette = {tab._etichetta_tipo(k) for k in
                 ("index", "primary_key", "foreign_key", "unique", "check")}
    assert len(etichette) == 5


def test_un_tipo_sconosciuto_non_fa_esplodere_nulla(tab):
    assert tab._etichetta_tipo("qualcosa_di_nuovo") == "qualcosa_di_nuovo"


def test_la_colonna_tipo_compare_nelle_righe(app, tmp_path):
    """Dal confronto vero all'albero: la colonna deve essere riempita."""
    from sqlalchemy import create_engine, text

    from diffdb.diff_DB import compare_environments
    from diffdb.results_tab import COL_TIPO, ResultsTab

    uno = f"sqlite:///{tmp_path / 'uno.db'}"
    due = f"sqlite:///{tmp_path / 'due.db'}"
    for url, ddl in (
        (uno, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50))"]),
        (due, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(30))",
               "CREATE TABLE solo_qui (id INTEGER PRIMARY KEY)"]),
    ):
        motore = create_engine(url)
        with motore.begin() as conn:
            for istruzione in ddl:
                conn.execute(text(istruzione))
        motore.dispose()

    tab = ResultsTab()
    tab.show_result(compare_environments("UNO", uno, "DUE", due))

    radice = tab.tree.invisibleRootItem()
    foglie = [radice.child(i).child(j)
              for i in range(radice.childCount())
              for j in range(radice.child(i).childCount())]
    assert foglie, "nessuna differenza da controllare"

    tipi = {foglia.text(COL_TIPO) for foglia in foglie}
    assert all(tipi), "qualche riga ha la colonna Tipo vuota"
    # La tabella in piu' e la colonna cambiata devono apparire come tali.
    assert tab._etichetta_tipo("table") in tipi
    assert tab._etichetta_tipo("column") in tipi


def test_le_intestazioni_sono_sei_e_in_ordine(tab):
    from diffdb.results_tab import (
        COL_DETTAGLIO,
        COL_DIFFERENZA,
        COL_MANCA,
        COL_OGGETTO,
        COL_PRESENTE,
        COL_TIPO,
    )

    assert tab.tree.columnCount() == 6
    assert [COL_OGGETTO, COL_TIPO, COL_DIFFERENZA,
            COL_PRESENTE, COL_MANCA, COL_DETTAGLIO] == list(range(6))
    intestazione = tab.tree.headerItem()
    assert intestazione.text(COL_TIPO)
