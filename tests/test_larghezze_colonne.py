"""Larghezze delle colonne: trascinabili e ricordate.

Tre guasti distinti, tutti e tre coperti qui:

- la tabella delle connessioni stava in ResizeToContents con la stringa in
  Stretch, e in nessuna delle due modalita' Qt lascia trascinare il bordo:
  non si poteva ridimensionare affatto;
- l'albero dei risultati rifaceva resizeColumnToContents a ogni confronto,
  quindi buttava via le larghezze appena sistemate a mano;
- nessuna delle due si ricordava niente fra una sessione e l'altra.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import preferences  # noqa: E402
from diffdb.qt import QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def impostazioni_isolate(tmp_path, monkeypatch):
    """Le preferenze vanno in una cartella usa e getta, non in quelle vere."""
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def diff(tmp_path):
    from sqlalchemy import create_engine, text

    from diffdb.diff_DB import compare_environments

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
    return compare_environments("UNO", uno, "DUE", due)


# --- il magazzino delle larghezze ------------------------------------------

def test_senza_niente_salvato_non_inventa(impostazioni_isolate):
    assert preferences.larghezze_colonne("risultati", 6) is None


def test_salva_e_rilegge(impostazioni_isolate):
    preferences.imposta_larghezze_colonne("risultati", [10, 20, 30, 40, 50, 60])
    assert preferences.larghezze_colonne("risultati", 6) == [10, 20, 30, 40, 50, 60]


def test_se_il_numero_di_colonne_non_combacia_si_ignora(impostazioni_isolate):
    """Il caso dell'aggiornamento: abbiamo aggiunto "Tipo" in mezzo, e le
    larghezze salvate prima finirebbero sulle colonne sbagliate."""
    preferences.imposta_larghezze_colonne("risultati", [10, 20, 30, 40, 50])
    assert preferences.larghezze_colonne("risultati", 6) is None


def test_valori_rovinati_non_fanno_danni(impostazioni_isolate):
    preferences.imposta_larghezze_colonne("risultati", [10, 20, 30, 40, 50, 60])
    percorso = impostazioni_isolate / "diffdb.ini"
    percorso.write_text(
        percorso.read_text(encoding="utf-8").replace("10,20", "dieci,venti"),
        encoding="utf-8")
    assert preferences.larghezze_colonne("risultati", 6) is None


def test_larghezze_assurde_si_ignorano(impostazioni_isolate):
    preferences.imposta_larghezze_colonne("risultati", [0, 20, 30, 40, 50, 60])
    assert preferences.larghezze_colonne("risultati", 6) is None


# --- l'albero dei risultati -------------------------------------------------

def test_tutte_le_colonne_sono_trascinabili(app, impostazioni_isolate, diff):
    """Compresa l'ultima: in Stretch Qt non la fa ridimensionare."""
    from diffdb.results_tab import ResultsTab

    tab = ResultsTab()
    tab.show_result(diff)
    intestazione = tab.tree.header()

    assert not intestazione.stretchLastSection()
    for colonna in range(tab.tree.columnCount()):
        assert (intestazione.sectionResizeMode(colonna)
                == QtWidgets.QHeaderView.ResizeMode.Interactive), colonna


def test_un_nuovo_confronto_non_azzera_le_larghezze(app, impostazioni_isolate, diff):
    """Il fastidio quotidiano: ogni confronto rimetteva tutto come voleva lui."""
    from diffdb.results_tab import COL_OGGETTO, ResultsTab

    tab = ResultsTab()
    tab.show_result(diff)

    tab.tree.setColumnWidth(COL_OGGETTO, 321)
    tab.show_result(diff)

    assert tab.tree.columnWidth(COL_OGGETTO) == 321


def test_quello_che_trascina_l_utente_viene_salvato(app, impostazioni_isolate, diff):
    from diffdb.results_tab import COL_OGGETTO, NOME_COLONNE, ResultsTab

    tab = ResultsTab()
    tab.show_result(diff)
    tab.tree.setColumnWidth(COL_OGGETTO, 277)

    salvate = preferences.larghezze_colonne(NOME_COLONNE, tab.tree.columnCount())
    assert salvate is not None
    assert salvate[COL_OGGETTO] == 277


def test_alla_riapertura_si_riprendono_le_larghezze(app, impostazioni_isolate, diff):
    from diffdb.results_tab import COL_OGGETTO, NOME_COLONNE, ResultsTab

    preferences.imposta_larghezze_colonne(NOME_COLONNE, [250, 120, 130, 90, 90, 400])

    tab = ResultsTab()
    tab.show_result(diff)

    assert tab.tree.columnWidth(COL_OGGETTO) == 250


# --- la tabella delle connessioni ------------------------------------------

def test_le_colonne_delle_connessioni_sono_trascinabili(app, impostazioni_isolate):
    """Erano in ResizeToContents piu' Stretch: nessun bordo trascinabile."""
    from diffdb.main_window import (
        COL_DELETE,
        COL_EDIT,
        LARGHE_CONNESSIONI,
        MainWindow,
    )

    finestra = MainWindow()
    try:
        intestazione = finestra.conn_table().horizontalHeader()
        for colonna in LARGHE_CONNESSIONI:
            assert (intestazione.sectionResizeMode(colonna)
                    == QtWidgets.QHeaderView.ResizeMode.Interactive), colonna
        # Le colonne dei pulsanti restano aderenti alle icone.
        for colonna in (COL_EDIT, COL_DELETE):
            assert (intestazione.sectionResizeMode(colonna)
                    == QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    finally:
        finestra.close()


def test_le_larghezze_delle_connessioni_si_ricordano(app, impostazioni_isolate):
    from diffdb.main_window import (
        COL_NAME,
        LARGHE_CONNESSIONI,
        NOME_COLONNE_CONNESSIONI,
        MainWindow,
    )

    preferences.imposta_larghezze_colonne(
        NOME_COLONNE_CONNESSIONI, [200, 300, 110, 120])

    finestra = MainWindow()
    try:
        assert finestra.conn_table().columnWidth(COL_NAME) == 200
        assert len(LARGHE_CONNESSIONI) == 4
    finally:
        finestra.close()
