"""La finestra si costruisce davvero su PySide6.

Gira headless (QT_QPA_PLATFORM=offscreen): e' il test che difende la migrazione
da PyQt5, dove i .ui venivano caricati con uic.loadUi e i figli erano esposti
come attributi in automatico.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connections import Connection  # noqa: E402
from src.qt import QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))  # niente scritture sulla config vera
    from src.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


def test_la_finestra_ha_i_tre_tab(window):
    titoli = [window.tabWidget.tabText(i) for i in range(window.tabWidget.count())]
    assert titoli[:4] == ["Home", "Configurazione", "Scelta", "Risultati"]


def test_i_widget_dei_tab_sono_raggiungibili(window):
    """QUiLoader non espone i figli come attributi: lo fa bind_children."""
    assert window.conn_table() is not None
    assert window.scelta_tab().comboBox1 is not None
    assert window.scelta_tab().compare_button is not None


def test_la_tabella_mostra_schema_e_password_mascherata(window):
    window.connections = [
        Connection("SVI", "postgresql+psycopg2://app:segreta@localhost:5432/db", schema="APP")
    ]
    window.refresh_conn_table()

    table = window.conn_table()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "SVI"
    assert table.item(0, 2).text() == "APP"
    assert "segreta" not in table.item(0, 1).text()
    assert "****" in table.item(0, 1).text()


def test_le_combo_mostrano_lo_schema(window):
    window.connections = [
        Connection("SVI", "sqlite:///a.db", schema="APP"),
        Connection("COL", "sqlite:///b.db"),
    ]
    window.refresh_comboboxes()

    combo = window.scelta_tab().comboBox1
    assert combo.count() == 2
    assert combo.itemText(0) == "SVI [APP]"
    assert combo.itemData(0) == "SVI"      # il dato resta il nome, non l'etichetta
    assert combo.itemText(1) == "COL"


def test_confronto_fra_ambienti_uguali_bloccato(window, monkeypatch):
    window.connections = [Connection("SVI", "sqlite:///a.db")]
    window.refresh_comboboxes()

    avvisi = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *args, **kwargs: avvisi.append(args[2]))
    # Se partisse un confronto, chiederebbe la cartella di output: se venisse
    # chiamata, il test fallirebbe con l'eccezione qui sotto.
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: pytest.fail("non deve chiedere la cartella"))

    window.start_comparison()

    assert avvisi and "diversi" in avvisi[0]
    assert window.thread is None
