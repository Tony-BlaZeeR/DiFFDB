"""Ridimensionamento di una finestra senza cornice.

Senza cornice non ci sono i bordi di sistema, percio' Qt non ridimensiona dai
lati: c'era solo la presa in basso a destra, e per cambiare larghezza
bisognava passare da quell'angolo di sedici pixel. Qui si verifica che tutti
e otto i bordi rispondano, e che il minimo imposto non neghi spazio che il
layout non chiede.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.qt import Qt, QtCore, QtGui, QtWidgets  # noqa: E402

SX, DX = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
SU, GIU = Qt.Edge.TopEdge, Qt.Edge.BottomEdge


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def finestra(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    from diffdb.main_window import MainWindow

    w = MainWindow()
    w.resize(1000, 700)
    w.show()
    app.processEvents()
    yield w
    w.close()


def _punti(w):
    larghezza, altezza = w.width(), w.height()
    return {
        SX: (1, altezza // 2),
        DX: (larghezza - 1, altezza // 2),
        SU: (larghezza // 2, 1),
        GIU: (larghezza // 2, altezza - 1),
        SX | SU: (1, 1),
        DX | SU: (larghezza - 1, 1),
        SX | GIU: (1, altezza - 1),
        DX | GIU: (larghezza - 1, altezza - 1),
    }


def test_tutti_gli_otto_bordi_rispondono(finestra):
    """Quattro lati e quattro angoli, non solo l'angolo in basso a destra."""
    for attesi, (x, y) in _punti(finestra).items():
        trovati = finestra._bordi_sotto_il_mouse(QtCore.QPoint(x, y))
        assert trovati == attesi, f"in ({x},{y}) attesi {attesi}, trovati {trovati}"


def test_ogni_direzione_ha_il_suo_cursore(finestra):
    atteso = {
        SX: Qt.CursorShape.SizeHorCursor,
        DX: Qt.CursorShape.SizeHorCursor,
        SU: Qt.CursorShape.SizeVerCursor,
        GIU: Qt.CursorShape.SizeVerCursor,
        SX | SU: Qt.CursorShape.SizeFDiagCursor,
        DX | GIU: Qt.CursorShape.SizeFDiagCursor,
        DX | SU: Qt.CursorShape.SizeBDiagCursor,
        SX | GIU: Qt.CursorShape.SizeBDiagCursor,
    }
    for bordi, forma in atteso.items():
        assert finestra._forma_cursore(bordi) == forma, bordi


def test_al_centro_non_si_ridimensiona(finestra):
    punto = QtCore.QPoint(finestra.width() // 2, finestra.height() // 2)
    assert finestra._bordi_sotto_il_mouse(punto) == Qt.Edge(0)
    assert finestra._forma_cursore(Qt.Edge(0)) is None


def test_appena_dentro_il_margine_non_si_ridimensiona(finestra):
    """Il bordo sensibile non deve rubare i clic a quello che gli sta vicino."""
    from diffdb.main_window import MARGINE_RESIZE

    punto = QtCore.QPoint(MARGINE_RESIZE + 5, finestra.height() // 2)
    assert finestra._bordi_sotto_il_mouse(punto) == Qt.Edge(0)


def test_da_massimizzata_non_si_ridimensiona(finestra, app):
    finestra.showMaximized()
    app.processEvents()
    angolo = QtCore.QPoint(finestra.width() - 1, finestra.height() - 1)
    assert finestra._bordi_sotto_il_mouse(angolo) == Qt.Edge(0)


def test_la_presa_d_angolo_resta_come_riserva(finestra):
    """Dove il sistema non supporta startSystemResize e' l'unica via."""
    assert isinstance(finestra.size_grip, QtWidgets.QSizeGrip)


# --- il minimo imposto ------------------------------------------------------

def test_il_minimo_non_nega_spazio_che_il_layout_non_chiede(finestra):
    """Il minimo era 800x600 mentre al layout bastava molto meno in altezza:
    pixel negati senza motivo, scomodi su uno schermo basso.

    Non si confronta con minimumSizeHint: quel valore cambia con il
    contenuto e con la scheda aperta (misurati 393 e 445 nella stessa
    finestra in due momenti diversi), percio' un test che lo usasse come
    riferimento passerebbe o fallirebbe a seconda dell'ordine di esecuzione.
    Qui si verificano i due limiti che contano e che non ballano.
    """
    minimo = finestra.minimumSize()

    assert minimo.height() < 600, "l'altezza minima e' ancora quella vecchia"
    assert minimo.height() >= 460, (
        "minimo troppo basso: con un margine cosi' stretto sul minimo che "
        "Qt calcola, in qualche stato della finestra qualcosa viene tagliato")


def test_la_finestra_si_puo_rimpicciolire_oltre_il_vecchio_limite(finestra, app):
    finestra.showNormal()
    finestra.resize(800, 505)
    app.processEvents()
    assert finestra.height() < 600


def test_chiudendo_non_resta_il_cursore_di_ridimensionamento(app, tmp_path, monkeypatch):
    """Il cursore sovrapposto e' globale: restare impostato lo lascerebbe
    anche sulle altre finestre."""
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    from diffdb.main_window import MainWindow

    w = MainWindow()
    w.show()
    app.processEvents()
    w._aggiorna_cursore_bordo(SX | SU)
    assert QtWidgets.QApplication.overrideCursor() is not None

    w.close()
    assert QtWidgets.QApplication.overrideCursor() is None


# --- il collegamento, non solo i conti ---------------------------------------
#
# I test sopra provano il calcolo dei bordi chiamando i metodi. Questi due
# provano che il filtro sia attaccato dove serve e che reagisca davvero a un
# evento del mouse: senza, il calcolo potrebbe essere giusto e la finestra
# restare comunque non ridimensionabile.

def _movimento(finestra, x, y):
    punto = QtCore.QPointF(float(x), float(y))
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove, punto, punto,
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier)


def test_il_filtro_e_attaccato_alla_finestra_di_sistema(finestra):
    """Sulla QWindow e non sull'applicazione: col filtro sull'applicazione
    ogni evento di ogni widget passava da Python e applicare un tema era
    quattro volte piu' lento."""
    assert finestra._filtro_bordi_attivo
    assert finestra.windowHandle() is not None


def test_avvicinandosi_al_bordo_il_cursore_cambia(finestra):
    """Il percorso completo: evento del mouse -> filtro -> cursore."""
    QtWidgets.QApplication.restoreOverrideCursor()
    while QtWidgets.QApplication.overrideCursor() is not None:
        QtWidgets.QApplication.restoreOverrideCursor()
    finestra._cursore_bordo = None

    QtWidgets.QApplication.sendEvent(
        finestra.windowHandle(), _movimento(finestra, 1, finestra.height() // 2))
    attuale = QtWidgets.QApplication.overrideCursor()
    assert attuale is not None, "sul bordo il cursore non e' cambiato"
    assert attuale.shape() == Qt.CursorShape.SizeHorCursor

    # Tornando al centro deve sparire, altrimenti resterebbe la freccia di
    # ridimensionamento su tutta l'applicazione.
    QtWidgets.QApplication.sendEvent(
        finestra.windowHandle(),
        _movimento(finestra, finestra.width() // 2, finestra.height() // 2))
    assert QtWidgets.QApplication.overrideCursor() is None
