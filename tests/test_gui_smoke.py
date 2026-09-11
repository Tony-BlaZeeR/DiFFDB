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

from diffdb.connections import Connection  # noqa: E402
from diffdb.qt import QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))  # niente scritture sulla config vera
    from diffdb.main_window import MainWindow

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
    from diffdb.main_window import COL_NAME, COL_SCHEMA, COL_STRING

    window.connections = [
        Connection("SVI", "postgresql+psycopg2://app:segreta@localhost:5432/db", schema="APP")
    ]
    window.refresh_conn_table()

    table = window.conn_table()
    assert table.rowCount() == 1
    assert table.item(0, COL_NAME).text() == "SVI"
    assert table.item(0, COL_SCHEMA).text() == "APP"
    assert "segreta" not in table.item(0, COL_STRING).text()
    assert "****" in table.item(0, COL_STRING).text()


def test_la_tabella_dice_dove_sta_la_password(window):
    from diffdb.main_window import COL_PASSWORD

    window.connections = [
        Connection("CHIARO", "postgresql://app:segreta@host/db"),
        Connection("PORTACHIAVI", "postgresql://app:${keyring}@host/db"),
        Connection("VARIABILE", "postgresql://app:${PWD}@host/db"),
    ]
    window.refresh_conn_table()

    table = window.conn_table()
    etichette = [table.cellWidget(riga, COL_PASSWORD).text() for riga in range(3)]
    assert etichette == ["in chiaro", "portachiavi", "variabile"]
    # Quella in chiaro deve saltare all'occhio, non essere una riga come le altre.
    assert table.cellWidget(0, COL_PASSWORD).property("pastiglia") == "allarme"
    assert table.cellWidget(1, COL_PASSWORD).property("pastiglia") == "buona"


def test_le_combo_portano_il_nome_e_la_didascalia_il_resto(window):
    """Lo schema non sta piu' appiccicato al nome: sta nella riga di dettaglio,
    insieme a dialetto e host, che dicono davvero cosa si sta per toccare."""
    window.connections = [
        Connection("SVI", "postgresql://app:pw@dbsrv/gestionale", schema="APP"),
        Connection("COL", "sqlite:///b.db"),
    ]
    window.refresh_comboboxes()

    tab = window.scelta_tab()
    assert tab.comboBox1.count() == 2
    assert tab.comboBox1.itemText(0) == "SVI"
    assert tab.comboBox1.itemData(0) == "SVI"

    dettaglio = tab.dettaglio1.text()
    assert "postgresql" in dettaglio and "dbsrv/gestionale" in dettaglio
    assert "APP" in dettaglio
    assert "pw" not in dettaglio          # mai le credenziali


def test_all_avvio_i_due_ambienti_sono_diversi(window):
    """Partire con lo stesso ambiente da entrambe le parti significa aprire
    l'applicazione in uno stato non valido."""
    window.connections = [
        Connection("SVI", "sqlite:///a.db"),
        Connection("COL", "sqlite:///b.db"),
    ]
    window.refresh_comboboxes()

    tab = window.scelta_tab()
    assert tab.comboBox1.currentData() != tab.comboBox2.currentData()
    assert tab.compare_button.isEnabled()


def test_inverti_scambia_la_direzione(window):
    window.connections = [
        Connection("SVI", "sqlite:///a.db"),
        Connection("COL", "sqlite:///b.db"),
    ]
    window.refresh_comboboxes()

    tab = window.scelta_tab()
    prima = (tab.comboBox1.currentData(), tab.comboBox2.currentData())
    tab.inverti()

    assert (tab.comboBox1.currentData(), tab.comboBox2.currentData()) == prima[::-1]


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
