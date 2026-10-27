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

from diffdb import theme  # noqa: E402
from diffdb.qt import QtWidgets  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent

# Soglie WCAG 2.1 livello AA.
AA_TESTO = 4.5
AA_ELEMENTI = 3.0   # elementi di interfaccia e testo grande

# Le tre tavolozze spedite: ognuna va verificata sui propri fondi, perche'
# l'interfaccia puo' cambiare variante e tema a caldo.
TEMI = {
    "moderna scuro": theme.MODERNA_SCURO,
    "moderna chiaro": theme.MODERNA_CHIARO,
    "retro": theme.RETRO,
}


def _fondi(tokens: dict) -> list[str]:
    """I fondi su cui puo' capitare del testo in un tema."""
    return [tokens["bg"], tokens["surface"], tokens["raised"], tokens["titlebar"]]


def _componi(colore: str, base: str) -> str:
    """Colore effettivo di un token rgba(...) sovrapposto a `base` (#RRGGBB).

    Le pastiglie hanno un fondo semitrasparente: per misurarne il contrasto va
    prima composto sul fondo pieno del riquadro che le ospita.
    """
    colore = colore.strip()
    if colore.startswith("#"):
        return colore
    n = [int(x) for x in re.findall(r"\d+", colore)]
    r, g, b = n[:3]
    a = n[3] if len(n) > 3 else 255
    br, bg, bb = (int(base[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda f, k: round(f * (a / 255) + k * (1 - a / 255))  # noqa: E731
    return f"#{mix(r, br):02X}{mix(g, bg):02X}{mix(b, bb):02X}"


def luminanza(colore: str) -> float:
    r, g, b = (int(colore[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def canale(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * canale(r) + 0.7152 * canale(g) + 0.0722 * canale(b)


def contrasto(primo: str, secondo: str) -> float:
    a, b = luminanza(primo), luminanza(secondo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def peggior_contrasto(colore: str, fondi: list[str]) -> float:
    return min(contrasto(colore, fondo) for fondo in fondi)


# --- la funzione di misura stessa ------------------------------------------


@pytest.mark.parametrize("primo, secondo, atteso", [
    ("#FFFFFF", "#000000", 21.0),   # massimo possibile
    ("#000000", "#000000", 1.0),    # identici
])
def test_la_misura_del_contrasto_e_corretta(primo, secondo, atteso):
    """Se sbaglia il metro, tutto il resto non vale niente."""
    assert contrasto(primo, secondo) == pytest.approx(atteso, abs=0.01)


# --- palette ---------------------------------------------------------------


@pytest.mark.parametrize("tema", list(TEMI))
@pytest.mark.parametrize("chiave", ["text", "text2", "muted"])
def test_il_testo_dell_interfaccia_e_leggibile(tema, chiave):
    """Testo, testo secondario e didascalie restano a >=4.5:1 in ogni tema."""
    tokens = TEMI[tema]
    colore = tokens[chiave]
    peggiore = peggior_contrasto(colore, _fondi(tokens))
    assert peggiore >= AA_TESTO, (
        f"{chiave} ({colore}) nel tema '{tema}' sta a {peggiore:.2f}:1, "
        f"sotto la soglia AA di {AA_TESTO}:1")


@pytest.mark.parametrize("tema", list(TEMI))
def test_i_colori_delle_differenze_sono_leggibili(tema):
    """Erano a 2.64:1 e 3.18:1: le tre direzioni del diff ora passano AA sui
    fondi dell'albero in ogni tema."""
    tokens = TEMI[tema]
    # L'albero dei risultati ha fondo 'code'/'surface' e righe alterne 'raised'.
    fondi = [tokens["code"], tokens["surface"], tokens["raised"]]
    for chiave in ("diff_manca_primo", "diff_solo_qui", "diff_diverso"):
        assert peggior_contrasto(tokens[chiave], fondi) >= AA_TESTO, (
            f"{chiave} ({tokens[chiave]}) nel tema '{tema}' sotto AA")


@pytest.mark.parametrize("tema", list(TEMI))
def test_la_spunta_si_distingue_dal_fondo(tema):
    """Un elemento di interfaccia deve staccare almeno 3:1, o non si vede
    se e' spuntato."""
    tokens = TEMI[tema]
    assert peggior_contrasto(tokens["accent"], _fondi(tokens)) >= AA_ELEMENTI


def test_gli_stylesheet_non_usano_i_colori_bocciati():
    """I colori vecchi non devono rientrare da una copia-incolla."""
    for foglio in ("moderna.qss", "retro.qss"):
        qss = (RADICE / "diffdb" / "styles" / foglio).read_text(encoding="utf-8")
        for bocciato in ("#7F8C94", "#6A8759", "#CC7832"):
            assert bocciato not in qss, f"{bocciato} in {foglio} non passa il contrasto AA"


@pytest.mark.parametrize("tema", list(TEMI))
def test_ogni_colore_di_testo_del_tema_e_leggibile(tema):
    """Rete di sicurezza: ogni colore di testo del tema stacca dai fondi."""
    tokens = TEMI[tema]
    for chiave in ("text", "text2", "muted", "accent", "accent_strong"):
        peggiore = peggior_contrasto(tokens[chiave], _fondi(tokens))
        assert peggiore >= AA_ELEMENTI, (
            f"{chiave} ({tokens[chiave]}) nel tema '{tema}' sta a {peggiore:.2f}:1")


@pytest.mark.parametrize("tema", list(TEMI))
@pytest.mark.parametrize("testo, fondo", [
    ("plus", "plus_bg"),         # pastiglia buona
    ("minus", "minus_bg"),       # pastiglia attenzione
    ("error", "error_bg"),       # pastiglia allarme
])
def test_le_pastiglie_sono_leggibili_sul_proprio_fondo(tema, testo, fondo):
    tokens = TEMI[tema]
    sfondo = _componi(tokens[fondo], tokens["surface"])
    assert contrasto(tokens[testo], sfondo) >= AA_TESTO, (
        f"pastiglia {testo} nel tema '{tema}' su {sfondo} sotto AA")


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
