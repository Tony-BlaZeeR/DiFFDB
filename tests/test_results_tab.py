"""Il tab dei risultati: albero, selezione e export selettivo.

Gira headless (QT_QPA_PLATFORM=offscreen).
"""

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.diff_DB import compare_environments  # noqa: E402
from src.qt import Qt, QtWidgets  # noqa: E402
from src.results_tab import ResultsTab  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def diff(tmp_path):
    svi = f"sqlite:///{tmp_path / 'svi.db'}"
    col = f"sqlite:///{tmp_path / 'col.db'}"
    for url, ddl in (
        (svi, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50), email VARCHAR(120))",
               "CREATE TABLE ordini (id INTEGER PRIMARY KEY)"]),
        (col, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50))"]),
    ):
        engine = create_engine(url)
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        engine.dispose()
    return compare_environments("SVI", svi, "COL", col)


def _tab(app, **callbacks):
    return ResultsTab(**callbacks)


def test_albero_raggruppa_per_categoria(app, diff):
    tab = _tab(app)
    tab.show_result(diff)

    root = tab.tree.invisibleRootItem()
    # solo le sezioni non vuote compaiono: qui Tabelle (tabella + colonna mancanti)
    intestazioni = [root.child(i).text(0) for i in range(root.childCount())]
    assert any("Tabelle" in t for t in intestazioni)
    # il numero totale di foglie corrisponde al numero di differenze
    foglie = sum(root.child(i).childCount() for i in range(root.childCount()))
    assert foglie == len(diff.all)


def test_tutte_le_voci_partono_selezionate(app, diff):
    tab = _tab(app)
    tab.show_result(diff)
    assert len(tab.checked_differences()) == len(diff.all)


def test_deseleziona_e_riseleziona(app, diff):
    tab = _tab(app)
    tab.show_result(diff)

    tab._set_all_checked(False)
    assert tab.checked_differences() == []
    tab._set_all_checked(True)
    assert len(tab.checked_differences()) == len(diff.all)


def test_filtro_nasconde_le_voci_non_corrispondenti(app, diff):
    tab = _tab(app)
    tab.show_result(diff)

    tab.filter_input.setText("ordini")
    root = tab.tree.invisibleRootItem()
    visibili = [
        root.child(i).child(j).text(0)
        for i in range(root.childCount())
        for j in range(root.child(i).childCount())
        if not root.child(i).child(j).isHidden()
    ]
    assert visibili and all("ordini" in v.lower() for v in visibili)


def test_export_excel_passa_il_diff_completo(app, diff):
    ricevuti = []
    tab = _tab(app, on_export_excel=ricevuti.append)
    tab.show_result(diff)

    tab._export_excel()
    assert ricevuti and ricevuti[0] is diff


def test_export_sql_manda_solo_i_selezionati(app, diff):
    """Il cuore del punto 3: spunto una sola differenza ed esporto solo quella."""
    ricevuti = []
    tab = _tab(app, on_export_sql=ricevuti.append)
    tab.show_result(diff)

    # tengo selezionata solo la prima foglia
    tab._set_all_checked(False)
    root = tab.tree.invisibleRootItem()
    prima_foglia = root.child(0).child(0)
    prima_foglia.setCheckState(0, Qt.CheckState.Checked)

    tab._export_sql()
    assert len(ricevuti) == 1
    esportato = ricevuti[0]
    assert len(esportato.all) == 1                 # solo la differenza spuntata
    assert esportato.snapshot1.env_name == diff.snapshot1.env_name  # snapshot preservati


def test_export_sql_senza_selezione_non_chiama_il_callback(app, diff, monkeypatch):
    ricevuti = []
    tab = _tab(app, on_export_sql=ricevuti.append)
    tab.show_result(diff)
    tab._set_all_checked(False)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    tab._export_sql()
    assert ricevuti == []
