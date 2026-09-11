"""Lingua dell'interfaccia e comportamenti della finestra.

Girano headless (QT_QPA_PLATFORM=offscreen): la finestra si costruisce davvero,
senza bisogno di uno schermo.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from diffdb import i18n, preferences  # noqa: E402
from diffdb.qt import QtCore, QtWidgets  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Preferenze isolate: i test non devono toccare quelle vere."""
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    return tmp_path


# --- cataloghi di traduzione ----------------------------------------------


def test_ogni_catalogo_e_compilato():
    """Un .ts senza il suo .qm vuol dire interfaccia che resta in italiano."""
    for sorgente in (RADICE / "diffdb" / "translations").glob("diffdb_*.ts"):
        assert sorgente.with_suffix(".qm").exists(), (
            f"manca {sorgente.stem}.qm: rigenera con 'python tools/traduzioni.py'")


def test_non_restano_stringhe_da_tradurre():
    sys.path.insert(0, str(RADICE / "tools"))
    from traduzioni import non_tradotte

    for sorgente in (RADICE / "diffdb" / "translations").glob("diffdb_*.ts"):
        lingua = sorgente.stem.removeprefix("diffdb_")
        assert non_tradotte(lingua) == []


def test_il_catalogo_inglese_traduce(app):
    traduttore = QtCore.QTranslator()
    assert traduttore.load(str(RADICE / "diffdb" / "translations" / "diffdb_en.qm"))

    assert traduttore.translate("ResultsTab", "Viste") == "Views"
    assert traduttore.translate("ChooseTab", "Confronta") == "Compare"
    assert traduttore.translate("ChooseTab", "Riferimento") == "Reference"
    assert traduttore.translate("HomeTab", "Ultimo confronto") == "Last comparison"
    assert traduttore.translate("DialogoConnessione", "Testa connessione") == "Test connection"
    # Anche le stringhe che arrivano dai file .ui di Qt Designer.
    assert traduttore.translate("AddConnectionDialog", "Nome Connessione") == "Connection name"


def test_i_segnaposto_sopravvivono_alla_traduzione():
    """Se una traduzione perde {0}, il messaggio esce monco a runtime."""
    import re
    import xml.etree.ElementTree as ET

    for sorgente in (RADICE / "diffdb" / "translations").glob("diffdb_*.ts"):
        for contesto in ET.parse(sorgente).getroot():
            for messaggio in contesto.findall("message"):
                originale = messaggio.findtext("source") or ""
                tradotto = messaggio.findtext("translation") or ""
                attesi = set(re.findall(r"\{\d+\}", originale))
                assert attesi == set(re.findall(r"\{\d+\}", tradotto)), (
                    f"segnaposto persi in [{contesto.findtext('name')}] {originale!r}")


# --- scelta della lingua ---------------------------------------------------


def test_la_lingua_automatica_segue_il_sistema(config):
    preferences.imposta_lingua(preferences.LINGUA_AUTOMATICA)
    assert i18n.lingua_effettiva() == QtCore.QLocale.system().name().split("_")[0]


def test_la_lingua_scelta_vince_sul_sistema(config):
    preferences.imposta_lingua("en")
    assert i18n.lingua_effettiva() == "en"


def test_si_offrono_solo_le_lingue_che_esistono(config):
    disponibili = i18n.lingue_disponibili()
    assert preferences.LINGUA_AUTOMATICA in disponibili
    assert "it" in disponibili   # lingua sorgente
    assert "en" in disponibili   # ha il suo catalogo


# --- finestra --------------------------------------------------------------


def test_la_finestra_si_puo_ingrandire(app, config):
    """Il .ui dichiarava minimo e massimo uguali: era bloccata a 800x600."""
    from diffdb.main_window import MainWindow

    finestra = MainWindow()
    try:
        massimo = finestra.maximumSize()
        assert massimo.width() > finestra.minimumSize().width()
        assert massimo.height() > finestra.minimumSize().height()

        finestra.resize(1400, 900)
        assert finestra.size().width() == 1400
    finally:
        finestra.close()


def test_c_e_la_presa_per_ridimensionare(app, config):
    """Senza cornice, i bordi non si trascinano: serve una presa esplicita."""
    from diffdb.main_window import MainWindow

    finestra = MainWindow()
    try:
        assert isinstance(finestra.size_grip, QtWidgets.QSizeGrip)
    finally:
        finestra.close()


def test_la_geometria_viene_ricordata(app, config):
    from diffdb.main_window import MainWindow

    prima = MainWindow()
    prima.resize(1234, 789)
    prima.close()          # closeEvent salva la geometria

    dopo = MainWindow()
    try:
        assert dopo.size().width() == 1234
        assert dopo.size().height() == 789
    finally:
        dopo.close()


def test_la_cartella_di_output_viene_ricordata(app, config, tmp_path):
    from diffdb.main_window import MainWindow

    scelta = str(tmp_path / "report")
    preferences.imposta_cartella_output(scelta)

    finestra = MainWindow()
    try:
        assert finestra.output_dir == scelta
    finally:
        finestra.close()


# --- annullamento e regole --------------------------------------------------


def test_annulla_compare_solo_mentre_si_lavora(app, config):
    """Un pulsante Annulla sempre spento e' rumore: deve esserci quando serve."""
    from diffdb.main_window import TAB_SCELTA, MainWindow

    finestra = MainWindow()
    try:
        finestra.show()
        finestra.tabWidget.setCurrentIndex(TAB_SCELTA)
        tab = finestra.scelta_tab()

        assert not tab.cancel_button.isVisible()

        tab.imposta_occupato(True)
        assert tab.cancel_button.isVisible()
        assert not tab.compare_button.isEnabled()

        tab.imposta_occupato(False)
        assert not tab.cancel_button.isVisible()
    finally:
        finestra.close()


def test_la_finestra_carica_le_regole_dalla_configurazione(app, config):
    """Le regole stanno accanto alla configurazione e valgono anche per la GUI."""
    import json

    from diffdb import rules
    from diffdb.main_window import MainWindow

    (config / rules.NOME_PREDEFINITO).write_text(
        json.dumps({"format": 1, "escludi": {"tabelle": ["TMP_*"]}}), encoding="utf-8")

    finestra = MainWindow()
    try:
        assert finestra.regole.escludi_tabelle == ["TMP_*"]
        assert not finestra.regole.tabella_inclusa("TMP_SCARTI")
    finally:
        finestra.close()


def test_un_file_di_regole_rotto_non_impedisce_l_avvio(app, config):
    """Meglio partire senza filtri che non partire."""
    from diffdb import rules
    from diffdb.main_window import MainWindow

    (config / rules.NOME_PREDEFINITO).write_text("{rotto", encoding="utf-8")

    finestra = MainWindow()
    try:
        assert finestra.regole.vuote
    finally:
        finestra.close()
