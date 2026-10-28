"""Temi, personalizzazione del colore, logo e schermate dedicate.

Coprono il codice aggiunto con il redesign dell'interfaccia: la tavolozza per
variante/tema, la ritintatura sull'accento scelto, il logo disegnato a runtime,
e il cambio di schermata (Avanzamento/Errore/Nessuna differenza) che prima era
affidato a message box.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import preferences, theme  # noqa: E402
from diffdb.qt import QtGui, QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def _ripristina_tema():
    """Il tema e' uno stato di modulo: ogni test lo lascia com'era."""
    yield
    theme._corrente = theme.MODERNA_SCURO
    theme._variante_corrente = theme.VARIANTE_MODERNA


# --- contrasto, per verificare che la ritintatura resti leggibile ------------

def _lum(hex_):
    c = hex_.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrasto(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# --- tavolozze per variante/tema ---------------------------------------------

@pytest.mark.parametrize("variante", ["moderna", "retro"])
@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_applica_restituisce_una_tavolozza_completa(app, variante, tema):
    token = theme.applica(app, variante, tema, theme.ACCENTO_PREDEFINITO)
    for chiave in ("bg", "surface", "text", "accent", "font_ui"):
        assert token[chiave]
    assert theme.variante_attiva() == variante
    assert theme.e_retro() == (variante == "retro")


def test_l_accento_di_default_lascia_la_tavolozza_invariata(app):
    token = theme.applica(app, "moderna", "scuro", theme.ACCENTO_PREDEFINITO)
    assert token["bg"] == theme.MODERNA_SCURO["bg"]
    assert token["accent"] == theme.MODERNA_SCURO["accent"]


def test_logo_file_segue_la_variante(app):
    theme.applica(app, "retro", "scuro")
    assert theme.logo_file() == "logo_retro.png"
    theme.applica(app, "moderna", "scuro")
    assert theme.logo_file() == "logo.png"


def test_colori_diff_sono_tre_qcolor(app):
    theme.applica(app, "moderna", "scuro")
    colori = theme.colori_diff()
    assert set(colori) == {"manca_primo", "solo_qui", "diverso"}
    assert all(isinstance(c, QtGui.QColor) and c.isValid() for c in colori.values())


# --- ritintatura sull'accento ------------------------------------------------

def test_ritinge_conserva_la_luminosita_e_cambia_tonalita():
    base = "#111A14"  # un fondo scuro verdastro
    tinto = theme._ritinge(base, QtGui.QColor("#3B6FE0").getHslF()[0], 0.3)
    l1 = QtGui.QColor(base).getHslF()[2]
    l2 = QtGui.QColor(tinto).getHslF()[2]
    assert abs(l1 - l2) < 0.03               # luminosita' quasi identica
    assert QtGui.QColor(tinto).blueF() > QtGui.QColor(tinto).greenF()  # ora vira al blu


def test_ritinge_conserva_l_alpha_su_rgba():
    out = theme._ritinge("rgba(214,235,221,33)", 0.6, 0.3)
    assert out.startswith("rgba(") and out.rstrip(")").endswith("33")


def test_un_accento_personalizzato_tinge_tutto_il_tema(app):
    blu = "#3B6FE0"
    token = theme.applica(app, "moderna", "scuro", blu)
    # l'accento cambia rispetto al verde di default
    assert token["accent"] != theme.MODERNA_SCURO["accent"]
    # anche i fondi virano verso la tonalita' scelta (non piu' verdi)
    bg = QtGui.QColor(token["bg"])
    assert bg.blueF() >= bg.greenF()


@pytest.mark.parametrize("accento", ["#3B6FE0", "#8A4FD8", "#C9A227"])
@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_la_ritintatura_resta_leggibile(app, accento, tema):
    token = theme.applica(app, "moderna", tema, accento)
    for fondo in (token["bg"], token["surface"], token["raised"]):
        assert _contrasto(token["text"], fondo) >= 4.5


# --- logo disegnato a runtime ------------------------------------------------

@pytest.mark.parametrize("variante", ["moderna", "retro"])
def test_logo_pixmap_non_e_vuoto(app, variante):
    from diffdb.widgets import logo_pixmap
    theme.applica(app, variante, "scuro")
    pix = logo_pixmap(64)
    assert not pix.isNull()
    assert pix.width() == 64 and pix.height() == 64


def test_il_logo_segue_il_colore(app):
    """Con un accento blu il gradiente del logo non e' piu' verde."""
    from diffdb.widgets import logo_pixmap
    theme.applica(app, "moderna", "scuro", "#3B6FE0")
    img = logo_pixmap(64).toImage()
    # un pixel non trasparente qualsiasi deve avere piu' blu che verde
    trovati = []
    for y in range(0, 64, 4):
        for x in range(0, 64, 4):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                trovati.append(c)
    assert trovati, "logo tutto trasparente?"
    assert sum(c.blue() for c in trovati) > sum(c.green() for c in trovati)


# --- widget disegnati a mano -------------------------------------------------

def test_wordmark_si_disegna(app):
    from diffdb.widgets import WordmarkGradiente
    theme.applica(app, "moderna", "scuro")
    w = WordmarkGradiente("DiFFDB", 20)
    w.resize(w.sizeHint() if w.sizeHint().isValid() else w.size())
    assert not w.grab().isNull()      # grab forza il paintEvent


def test_riquadro_nasconde_l_etichetta_interna_nel_retro(app):
    from diffdb.widgets import Riquadro
    r = Riquadro("Ultimo confronto")
    etichetta = QtWidgets.QLabel("Ultimo confronto")
    r.registra_etichetta(etichetta)

    theme.applica(app, "moderna", "scuro")
    r.aggiorna_tema()
    assert etichetta.isVisibleTo(r) or not etichetta.isHidden()  # mostrata nel moderno

    theme.applica(app, "retro", "scuro")
    r.aggiorna_tema()
    assert etichetta.isHidden()                                   # nascosta nel retro
    r.resize(200, 120)
    assert not r.grab().isNull()      # il paint TUI (angoli + titolo) non esplode


# --- preferenze --------------------------------------------------------------

def test_preferenze_variante_tema_accento(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    preferences.imposta_variante("retro")
    preferences.imposta_tema("chiaro")
    preferences.imposta_accento("#3B6FE0")
    assert preferences.variante() == "retro"
    assert preferences.tema() == "chiaro"
    assert preferences.accento() == "#3B6FE0"


def test_preferenze_valori_sporchi_tornano_al_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    preferences.imposta_variante("inesistente")
    preferences.imposta_accento("non-un-colore")
    assert preferences.variante() == "moderna"
    assert preferences.accento() == preferences.ACCENTO_PREDEFINITO


# --- finestra: cambio tema e schermate dedicate ------------------------------

@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    from diffdb.main_window import MainWindow
    win = MainWindow()
    yield win
    win.close()


def test_cambia_variante_e_tema_a_caldo(window):
    partenza = preferences.variante()
    window._cambia_variante()
    assert preferences.variante() != partenza
    window._cambia_variante()
    assert preferences.variante() == partenza

    t0 = preferences.tema()
    window._cambia_tema()
    assert preferences.tema() != t0


def test_scelta_e_ripristino_colore(window):
    window._imposta_colore("#8A4FD8")
    assert preferences.accento() == "#8A4FD8"
    assert theme.corrente()["accent"] != theme.MODERNA_SCURO["accent"]
    window._ripristina_colore()
    assert preferences.accento() == preferences.ACCENTO_PREDEFINITO


def test_schermate_dedicate_di_scelta(window):
    ct = window.choose_tab
    ct.mostra_avanzamento("Lettura...")
    assert ct._stack.currentIndex() == ct.PAGINA_AVANZAMENTO
    ct.avanza("57 / 142")
    assert "57" in ct.avanz_label.text()
    ct.mostra_errore("ORA-12541: TNS:no listener")
    assert ct._stack.currentIndex() == ct.PAGINA_ERRORE
    assert "ORA-12541" in ct.err_messaggio.text()
    ct.mostra_scelta()
    assert ct._stack.currentIndex() == ct.PAGINA_SCELTA


def test_risultati_mostra_la_schermata_nessuna_differenza(window):
    from diffdb.diff_DB import DiffResult
    from diffdb.schema_snapshot import Snapshot
    vuoto = DiffResult(Snapshot("SVI", "sqlite"), Snapshot("COL", "sqlite"))
    window.results_tab.show_result(vuoto)
    assert window.results_tab._stack.currentIndex() == 1   # pagina "nessuna differenza"
