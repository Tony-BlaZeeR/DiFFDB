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


def test_alla_riapertura_si_riprendono_le_proporzioni(app, impostazioni_isolate, diff):
    """Si ripristinano le proporzioni, non i pixel.

    Le larghezze salvate valgono come pesi: la finestra di oggi non e'
    necessariamente larga come quella dell'altra volta, e rimettere i pixel
    di allora lascerebbe un vuoto a destra o farebbe sforare.
    """
    from diffdb.results_tab import COL_DETTAGLIO, COL_OGGETTO, NOME_COLONNE, ResultsTab

    salvate = [250, 120, 130, 90, 90, 400]
    preferences.imposta_larghezze_colonne(NOME_COLONNE, salvate)

    tab = ResultsTab()
    tab.resize(1200, 500)
    tab.show()
    app.processEvents()
    tab.show_result(diff)
    app.processEvents()

    larghezze = [tab.tree.columnWidth(c) for c in range(tab.tree.columnCount())]
    # L'ordine di grandezza salvato va rispettato: il dettaglio e' la piu'
    # larga, l'oggetto la seconda.
    assert larghezze[COL_DETTAGLIO] == max(larghezze)
    assert larghezze[COL_OGGETTO] == sorted(larghezze)[-2]
    # E la tabella riempie la finestra, che e' il punto delle proporzioni.
    assert _vuoto_a_destra(tab.tree) == 0
    tab.close()


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
        LARGHE_CONNESSIONI,
        NOME_COLONNE_CONNESSIONI,
        MainWindow,
    )

    preferences.imposta_larghezze_colonne(
        NOME_COLONNE_CONNESSIONI, [200, 300, 110, 120])

    finestra = MainWindow()
    finestra.resize(1200, 700)
    finestra.show()
    app.processEvents()
    try:
        tabella = finestra.conn_table()
        larghezze = [tabella.columnWidth(c) for c in LARGHE_CONNESSIONI]
        # Come per i risultati: contano le proporzioni, non i pixel salvati.
        # La stringa di connessione era la piu' larga e deve restarlo.
        assert larghezze[1] == max(larghezze)
        assert larghezze[0] == sorted(larghezze)[-2]
        assert len(LARGHE_CONNESSIONI) == 4
    finally:
        finestra.close()


# --- adattamento alla finestra ----------------------------------------------
#
# Le colonne devono seguire la finestra: prima restavano della larghezza
# calcolata una volta, lasciando spazio vuoto a destra appena si allargava.
# Quello che si imposta a mano vale come proporzione, cosi' la regolazione
# sopravvive al ridimensionamento.

def _vuoto_a_destra(albero):
    larghezze = sum(albero.columnWidth(c) for c in range(albero.columnCount()))
    return albero.viewport().width() - larghezze


def test_le_colonne_seguono_la_finestra(app, impostazioni_isolate, diff):
    from diffdb.results_tab import ResultsTab

    tab = ResultsTab()
    tab.resize(900, 500)
    tab.show()
    app.processEvents()
    tab.show_result(diff)
    app.processEvents()

    for larghezza in (1400, 1800, 1000, 820):
        tab.resize(larghezza, 500)
        app.processEvents()
        assert _vuoto_a_destra(tab.tree) == 0, (
            f"a {larghezza} px restano {_vuoto_a_destra(tab.tree)} px vuoti")
    tab.close()


def test_la_regolazione_a_mano_sopravvive_al_ridimensionamento(
        app, impostazioni_isolate, diff):
    """Stringo una colonna, allargo la finestra: deve restare la piu'
    stretta, non tornare come prima."""
    from diffdb.results_tab import COL_OGGETTO, ResultsTab

    tab = ResultsTab()
    tab.resize(1200, 500)
    tab.show()
    app.processEvents()
    tab.show_result(diff)
    app.processEvents()

    tab.tree.setColumnWidth(COL_OGGETTO, 80)
    app.processEvents()
    assert _vuoto_a_destra(tab.tree) == 0, "dopo la regolazione resta un vuoto"

    tab.resize(1800, 500)
    app.processEvents()
    larghezze = [tab.tree.columnWidth(c) for c in range(tab.tree.columnCount())]
    assert larghezze[COL_OGGETTO] == min(larghezze)
    tab.close()


def test_se_il_contenuto_non_ci_sta_si_puo_scorrere(app, impostazioni_isolate, diff):
    """L'alternativa a stringere le colonne all'illeggibile."""
    from diffdb.results_tab import COL_DETTAGLIO, ResultsTab

    tab = ResultsTab()
    tab.resize(900, 500)
    tab.show()
    app.processEvents()
    tab.show_result(diff)
    app.processEvents()
    assert tab.tree.horizontalScrollBar().maximum() == 0, "si scorre senza motivo"

    tab.tree.setColumnWidth(COL_DETTAGLIO, 2000)
    app.processEvents()
    assert tab.tree.horizontalScrollBar().maximum() > 0, (
        "colonne piu' larghe della finestra ma non si puo' scorrere")
    tab.close()


def test_anche_le_connessioni_seguono_la_finestra(app, impostazioni_isolate):
    from diffdb.main_window import (
        COL_DELETE,
        COL_EDIT,
        LARGHE_CONNESSIONI,
        TAB_CONFIGURAZIONE,
        MainWindow,
    )

    finestra = MainWindow()
    finestra.resize(1000, 700)
    finestra.show()
    finestra.tabWidget.setCurrentIndex(TAB_CONFIGURAZIONE)
    app.processEvents()
    tabella = finestra.conn_table()

    try:
        for larghezza in (1500, 1900, 1100):
            finestra.resize(larghezza, 700)
            app.processEvents()
            pulsanti = sum(tabella.columnWidth(c) for c in (COL_EDIT, COL_DELETE))
            colonne = sum(tabella.columnWidth(c) for c in LARGHE_CONNESSIONI)
            vuoto = tabella.viewport().width() - pulsanti - colonne
            assert vuoto == 0, f"a {larghezza} px restano {vuoto} px vuoti"
    finally:
        finestra.close()
