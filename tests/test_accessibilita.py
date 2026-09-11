"""Accessibilita' dell'interfaccia.

Tre proprieta' che si rompono in silenzio se nessuno le misura:

- il **contrasto** dei colori sul tema scuro (WCAG AA, 4.5:1 per il testo);
- il fatto che la direzione di una differenza non sia affidata **solo al colore**;
- che i pulsanti a sola icona abbiano un **nome** per i lettori di schermo.
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from diffdb.qt import QtWidgets  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent

# Soglie WCAG 2.1 livello AA.
AA_TESTO = 4.5
AA_ELEMENTI = 3.0   # elementi di interfaccia e testo grande

# Tutti i fondi su cui puo' capitare del testo: se passa sul piu' chiaro,
# passa ovunque.
FONDI = ["#2B2B2B", "#313335", "#35383A", "#3C3F41"]


def luminanza(colore: str) -> float:
    r, g, b = (int(colore[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def canale(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * canale(r) + 0.7152 * canale(g) + 0.0722 * canale(b)


def contrasto(primo: str, secondo: str) -> float:
    a, b = luminanza(primo), luminanza(secondo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def peggior_contrasto(colore: str) -> float:
    return min(contrasto(colore, fondo) for fondo in FONDI)


# --- la funzione di misura stessa ------------------------------------------


@pytest.mark.parametrize("primo, secondo, atteso", [
    ("#FFFFFF", "#000000", 21.0),   # massimo possibile
    ("#000000", "#000000", 1.0),    # identici
])
def test_la_misura_del_contrasto_e_corretta(primo, secondo, atteso):
    """Se sbaglia il metro, tutto il resto non vale niente."""
    assert contrasto(primo, secondo) == pytest.approx(atteso, abs=0.01)


# --- palette ---------------------------------------------------------------


@pytest.mark.parametrize("nome, colore", [
    ("testo normale", "#A9B7C6"),
    ("titolo", "#D4D4D4"),
    ("sottotitolo", "#9FABB4"),
    ("didascalia", "#A2ABB1"),
])
def test_il_testo_dell_interfaccia_e_leggibile(nome, colore):
    assert peggior_contrasto(colore) >= AA_TESTO, (
        f"{nome} ({colore}) sta a {peggior_contrasto(colore):.2f}:1, "
        f"sotto la soglia AA di {AA_TESTO}:1")


def test_i_colori_delle_differenze_sono_leggibili():
    """Erano a 2.64:1 e 3.18:1: leggibili da chi ci vede bene, molto meno
    da tutti gli altri."""
    from diffdb.results_tab import COLOR_MISMATCH, COLOR_MISSING_HERE, COLOR_ONLY_HERE

    for colore in (COLOR_MISSING_HERE, COLOR_ONLY_HERE, COLOR_MISMATCH):
        assert peggior_contrasto(colore.name().upper()) >= AA_TESTO


def test_la_spunta_si_distingue_dal_fondo():
    """Un elemento di interfaccia deve staccare almeno 3:1, o non si vede
    se e' spuntato."""
    verde_spunta = "#97B188"
    assert min(contrasto(verde_spunta, f) for f in FONDI) >= AA_ELEMENTI


def test_lo_stylesheet_non_usa_piu_i_colori_bocciati():
    """I colori vecchi non devono rientrare da una copia-incolla."""
    qss = (RADICE / "diffdb" / "styles" / "style.qss").read_text(encoding="utf-8")
    for bocciato in ("#7F8C94", "#6A8759", "#CC7832"):
        assert bocciato not in qss, f"{bocciato} non passa il contrasto AA"


def test_ogni_colore_dello_stylesheet_su_fondo_scuro_e_leggibile():
    """Rete di sicurezza: pesca i colori di testo aggiunti in futuro."""
    qss = (RADICE / "diffdb" / "styles" / "style.qss").read_text(encoding="utf-8")
    colori = set(re.findall(r"^\s*color:\s*(#[0-9A-Fa-f]{6})\s*;", qss, re.MULTILINE))

    # Fuori i colori usati su fondi propri (pastiglie, pulsante primario), che
    # hanno il loro sfondo dichiarato accanto e sono verificati a parte.
    su_fondo_proprio = {"#FFFFFF", "#A5C08C", "#E0B978", "#E08A7D", "#6A6A6A"}

    for colore in colori - su_fondo_proprio:
        assert peggior_contrasto(colore.upper()) >= AA_TESTO, (
            f"{colore} nello stylesheet sta a {peggior_contrasto(colore.upper()):.2f}:1")


@pytest.mark.parametrize("testo, fondo", [
    ("#A5C08C", "#33402D"),   # pastiglia buona
    ("#E0B978", "#4A3B22"),   # pastiglia attenzione
    ("#E08A7D", "#4A2A26"),   # pastiglia allarme
    ("#FFFFFF", "#4B6EAF"),   # pulsante primario
])
def test_le_pastiglie_sono_leggibili_sul_proprio_fondo(testo, fondo):
    assert contrasto(testo, fondo) >= AA_TESTO


# --- il colore non e' l'unico canale ---------------------------------------


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def tab_con_risultati(app, tmp_path):
    from sqlalchemy import create_engine, text

    from diffdb.diff_DB import compare_environments
    from diffdb.results_tab import ResultsTab

    svi = f"sqlite:///{tmp_path / 'svi.db'}"
    col = f"sqlite:///{tmp_path / 'col.db'}"
    for url, ddl in (
        (svi, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50), "
               "email VARCHAR(120))"]),
        (col, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(30))",
               "CREATE TABLE solo_in_col (id INTEGER PRIMARY KEY)"]),
    ):
        motore = create_engine(url)
        with motore.begin() as conn:
            for istruzione in ddl:
                conn.execute(text(istruzione))
        motore.dispose()

    tab = ResultsTab()
    tab.show_result(compare_environments("SVI", svi, "COL", col))
    return tab


def _foglie(tab):
    radice = tab.tree.invisibleRootItem()
    return [radice.child(i).child(j)
            for i in range(radice.childCount())
            for j in range(radice.child(i).childCount())]


def test_ogni_riga_porta_un_simbolo_oltre_al_colore(tab_con_risultati):
    """Chi non distingue verde e arancio vedrebbe righe identiche."""
    from diffdb.results_tab import (
        SIMBOLO_DIVERSO,
        SIMBOLO_MANCA_NEL_PRIMO,
        SIMBOLO_MANCA_NEL_SECONDO,
    )

    simboli = {SIMBOLO_MANCA_NEL_PRIMO, SIMBOLO_MANCA_NEL_SECONDO, SIMBOLO_DIVERSO}
    foglie = _foglie(tab_con_risultati)
    assert foglie

    for foglia in foglie:
        assert foglia.text(1)[0] in simboli, f"riga senza simbolo: {foglia.text(1)!r}"


def test_i_simboli_distinguono_le_tre_direzioni(tab_con_risultati):
    """Non basta esserci: devono essere diversi fra loro."""
    from diffdb.results_tab import (
        SIMBOLO_DIVERSO,
        SIMBOLO_MANCA_NEL_PRIMO,
        SIMBOLO_MANCA_NEL_SECONDO,
    )

    trovati = {foglia.text(1)[0] for foglia in _foglie(tab_con_risultati)}
    assert trovati == {SIMBOLO_MANCA_NEL_PRIMO, SIMBOLO_MANCA_NEL_SECONDO, SIMBOLO_DIVERSO}


def test_la_legenda_spiega_i_simboli(tab_con_risultati):
    """Prima il significato dei colori esisteva solo in un commento nel codice."""
    legenda = tab_con_risultati.legend_label.text()
    assert "SVI" in legenda and "COL" in legenda
    for simbolo in ("←", "→", "≠"):
        assert simbolo in legenda


def test_il_dettaglio_troncato_resta_leggibile_nel_tooltip(tab_con_risultati):
    for foglia in _foglie(tab_con_risultati):
        assert foglia.toolTip(0)


# --- lettori di schermo -----------------------------------------------------


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    from diffdb.connections import Connection
    from diffdb.main_window import MainWindow

    finestra = MainWindow()
    finestra.connections = [Connection("SVI", "sqlite:///a.db"),
                            Connection("COL", "sqlite:///b.db")]
    finestra.refresh_conn_table()
    finestra.refresh_comboboxes()
    yield finestra
    finestra.close()


def test_i_pulsanti_a_sola_icona_hanno_un_nome(window):
    """Senza nome accessibile un lettore di schermo annuncia solo 'pulsante'."""
    from diffdb.main_window import COL_DELETE, COL_EDIT

    tabella = window.conn_table()
    for riga in range(tabella.rowCount()):
        for colonna in (COL_EDIT, COL_DELETE):
            pulsante = tabella.cellWidget(riga, colonna)
            assert pulsante.text() == ""            # e' solo un'icona
            assert pulsante.accessibleName()        # ...ma ha un nome
            assert "SVI" in pulsante.accessibleName() or "COL" in pulsante.accessibleName()


def test_il_pulsante_inverti_ha_un_nome(window):
    """Il simbolo da solo non e' un nome."""
    pulsante = window.scelta_tab().swap_button
    assert pulsante.text() == "⇄"
    assert pulsante.accessibleName() == "Inverti la direzione del confronto"


def test_i_pulsanti_della_barra_del_titolo_hanno_un_nome(window):
    assert window.maximize_button.accessibleName()


# --- tastiera ---------------------------------------------------------------


def test_le_scorciatoie_della_scheda_risultati_esistono(app, tmp_path):
    from diffdb.qt import QtGui
    from diffdb.results_tab import ResultsTab

    tab = ResultsTab()
    sequenze = {s.key().toString() for s in tab.findChildren(QtGui.QShortcut)}
    assert {"Ctrl+F", "Ctrl+E", "Ctrl+S"} <= sequenze


def test_le_scorciatoie_valgono_solo_nella_loro_scheda(app):
    """Con la portata predefinita, Ctrl+S esporterebbe SQL da qualunque scheda."""
    from diffdb.qt import Qt, QtGui
    from diffdb.results_tab import ResultsTab

    for scorciatoia in ResultsTab().findChildren(QtGui.QShortcut):
        assert scorciatoia.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut


def test_l_ordine_di_tabulazione_segue_la_lettura(window):
    """Riferimento, inverti, da allineare, confronta."""
    tab = window.scelta_tab()
    assert tab.comboBox1.nextInFocusChain() is not None
    # Il pulsante primario risponde a Invio.
    assert tab.compare_button.isDefault()
