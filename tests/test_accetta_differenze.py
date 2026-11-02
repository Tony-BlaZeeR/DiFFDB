"""Accettazione delle differenze dalla GUI (la baseline tipo-linter).

Gira headless. Usa due DB SQLite veri e la logica di confronto reale, cosi' il
test copre anche il ricalcolo in memoria dopo l'accettazione.
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from diffdb import rules  # noqa: E402
from diffdb.connections import Connection  # noqa: E402
from diffdb.qt import QtWidgets  # noqa: E402
from diffdb.snapshot_io import compare_sources  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _crea_db(percorso, istruzioni):
    con = sqlite3.connect(percorso)
    for i in istruzioni:
        con.execute(i)
    con.commit()
    con.close()


@pytest.fixture
def finestra(app, tmp_path, monkeypatch):
    """Finestra con un confronto gia' mostrato e config isolata in tmp."""
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    pre, prod = tmp_path / "pre.db", tmp_path / "prod.db"
    _crea_db(pre, [
        "CREATE TABLE cliente (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT)",
        "CREATE TABLE ordine (id INTEGER PRIMARY KEY, totale REAL)",
    ])
    _crea_db(prod, [
        "CREATE TABLE cliente (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)",       # -email
        "CREATE TABLE ordine (id INTEGER PRIMARY KEY, totale REAL, note TEXT)",    # +note
    ])
    diff = compare_sources(Connection("PRE", f"sqlite:///{pre.as_posix()}", None),
                           Connection("PROD", f"sqlite:///{prod.as_posix()}", None))
    assert len(diff.all) == 2

    from diffdb.main_window import MainWindow
    win = MainWindow()
    win.on_comparison_done(diff)
    return win, diff, tmp_path


def _conferma_si(monkeypatch):
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes))


def test_accetta_tutte_rende_il_confronto_vuoto(finestra, monkeypatch):
    win, diff, home = finestra
    _conferma_si(monkeypatch)

    win.results_tab._set_all_checked(True)
    win.results_tab._accept()

    percorso = home / rules.NOME_PREDEFINITO
    assert percorso.exists()
    assert len(rules.carica(percorso).accettate) == 2
    assert win._ultimo_diff.is_empty          # il semaforo diventa verde
    assert win.regole.accettate == {rules.chiave(d) for d in diff.all}


def test_accetta_sottoinsieme_lascia_le_altre(finestra, monkeypatch):
    win, diff, home = finestra
    _conferma_si(monkeypatch)

    una = diff.all[:1]
    win.accetta_differenze(una)

    riletto = rules.carica(home / rules.NOME_PREDEFINITO)
    assert riletto.accettate == {rules.chiave(una[0])}
    # resta esattamente l'altra differenza
    assert len(win._ultimo_diff.all) == 1
    assert rules.chiave(win._ultimo_diff.all[0]) != rules.chiave(una[0])


def test_annullare_non_scrive_niente(finestra, monkeypatch):
    win, diff, home = finestra
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No))
    prima = win.regole

    win.accetta_differenze(diff.all)

    assert not (home / rules.NOME_PREDEFINITO).exists()
    assert win.regole is prima
    assert not win._ultimo_diff.is_empty


def test_la_baseline_e_condivisa_con_la_cli(finestra, monkeypatch):
    """Il file scritto dalla GUI e' quello che rilegge la CLI (stesse chiavi)."""
    win, diff, home = finestra
    _conferma_si(monkeypatch)

    win.accetta_differenze(diff.all)

    # Un nuovo confronto che carica quel file non mostra piu' nulla.
    regole = rules.carica(home / rules.NOME_PREDEFINITO)
    assert all(regole.accettata(d) for d in diff.all)
