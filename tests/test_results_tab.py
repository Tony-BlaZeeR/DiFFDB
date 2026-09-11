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

from diffdb.diff_DB import compare_environments  # noqa: E402
from diffdb.qt import Qt, QtWidgets  # noqa: E402
from diffdb.results_tab import DIFF_ROLE, ResultsTab  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def diff(tmp_path):
    svi = f"sqlite:///{tmp_path / 'svi.db'}"
    col = f"sqlite:///{tmp_path / 'col.db'}"
    for url, ddl in (
        (svi, ["CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50), "
               "email VARCHAR(120))",
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
    tab = _tab(app, on_export_sql=lambda d, totali=None: ricevuti.append((d, totali)))
    tab.show_result(diff)

    # tengo selezionata solo la prima foglia
    tab._set_all_checked(False)
    root = tab.tree.invisibleRootItem()
    prima_foglia = root.child(0).child(0)
    prima_foglia.setCheckState(0, Qt.CheckState.Checked)

    tab._export_sql()
    assert len(ricevuti) == 1
    esportato, totali = ricevuti[0]
    assert len(esportato.all) == 1                 # solo la differenza spuntata
    assert esportato.snapshot1.env_name == diff.snapshot1.env_name  # snapshot preservati
    # Il totale viaggia con l'export: l'intestazione dello script deve poter
    # dire che e' parziale.
    assert totali == len(diff.all) > 1


def test_export_sql_senza_selezione_non_chiama_il_callback(app, diff, monkeypatch):
    ricevuti = []
    tab = _tab(app, on_export_sql=lambda d, totali=None: ricevuti.append(d))
    tab.show_result(diff)
    tab._set_all_checked(False)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    tab._export_sql()
    assert ricevuti == []


# --- scala: molte differenze --------------------------------------------


def _diff_con_n_differenze(n):
    """Un DiffResult sintetico, senza toccare un database: serve solo a
    misurare come si comporta l'albero con molte righe."""
    from diffdb.diff_DB import Difference, DiffResult
    from diffdb.schema_snapshot import Snapshot

    snap1, snap2 = Snapshot("SVI", "postgresql"), Snapshot("COL", "postgresql")
    diffs = [Difference("column", f"tabella_{i}", "mancante", column=f"col_{i}",
                        missing_in="COL", present_in="SVI", detail=f"VARCHAR({i % 200})")
             for i in range(n)]
    return DiffResult(snapshot1=snap1, snapshot2=snap2, tables=diffs)


def test_l_albero_regge_decine_di_migliaia_di_righe(app):
    """QTreeWidgetItem(parent, ...) chiamato una riga alla volta e' quadratico
    in Qt: ogni inserimento ricalcola qualcosa sui fratelli esistenti. Prima
    di questo test, 100.000 differenze bloccavano l'interfaccia per 7-8
    secondi; con gli item costruiti senza genitore e attaccati tutti insieme
    (addChildren), lo stesso caso sta sotto i 3 secondi anche su una macchina
    lenta come un runner di CI — la vecchia quadratica non ci passerebbe
    nemmeno vicino."""
    import time

    tab = _tab(app)
    diff = _diff_con_n_differenze(100_000)

    t0 = time.perf_counter()
    tab.show_result(diff)
    durata = time.perf_counter() - t0

    assert durata < 3.0, f"show_result su 100.000 differenze ha impiegato {durata:.2f}s"


def test_le_righe_costruite_in_massa_sono_corrette_come_prima(app):
    """La velocita' non deve costare la correttezza: checkbox, colonne e il
    ruolo con la Difference devono essere quelli di sempre."""
    tab = _tab(app)
    diff = _diff_con_n_differenze(50)
    tab.show_result(diff)

    sezione = tab.tree.invisibleRootItem().child(0)
    assert sezione.childCount() == 50

    riga = sezione.child(0)
    assert riga.checkState(0) == Qt.CheckState.Checked
    assert riga.text(0) == "tabella_0.col_0"
    assert riga.data(0, DIFF_ROLE) is not None
    assert riga.data(0, DIFF_ROLE).name == "tabella_0"

    assert len(tab.checked_differences()) == 50
