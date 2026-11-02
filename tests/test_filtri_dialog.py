"""Editor dei filtri di confronto (GUI) e la sua logica pura.

Gira headless (QT_QPA_PLATFORM=offscreen): il dialog si costruisce davvero.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from diffdb import rules  # noqa: E402
from diffdb.filters_dialog import (  # noqa: E402
    DialogoFiltri,
    pattern_da_testo,
    regole_aggiornate,
)
from diffdb.qt import QtWidgets  # noqa: E402
from diffdb.rules import Regole  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    return tmp_path


# --- logica pura (niente Qt) -----------------------------------------------


def test_pattern_separati_da_virgola_spazio_o_acapo():
    assert pattern_da_testo("*T_UTENTE*, APP_*  TMP_*\nX_*") == [
        "*T_UTENTE*", "APP_*", "TMP_*", "X_*"]


def test_pattern_rimuove_doppioni_conservando_ordine():
    assert pattern_da_testo("a, b, a, c, b") == ["a", "b", "c"]


def test_pattern_testo_vuoto():
    assert pattern_da_testo("") == []
    assert pattern_da_testo("   ,  ;  ") == []


def test_regole_aggiornate_conserva_le_accettate():
    base = Regole(accettate={"k1", "k2"}, origine="/percorso/regole.json")
    nuove = regole_aggiornate(
        base, solo_tabelle=["T_*"], escludi_tabelle=[], escludi_viste=[],
        escludi_sequenze=[], escludi_sinonimi=[], categorie_ignorate={"views"})
    assert nuove.solo_tabelle == ["T_*"]
    assert nuove.categorie_ignorate == {"views"}
    assert nuove.accettate == {"k1", "k2"}      # la baseline non si tocca
    assert nuove.origine == "/percorso/regole.json"


# --- dialog --------------------------------------------------------------


def test_dialog_rilegge_le_regole_che_mostra(app):
    base = Regole(solo_tabelle=["*T_UTENTE*"], escludi_tabelle=["TMP_*", "*_BAK"],
                  escludi_viste=["V_*"], categorie_ignorate={"triggers"}, accettate={"z"})
    dialog = DialogoFiltri(None, base)
    riletto = dialog._regole_correnti()

    assert riletto.solo_tabelle == ["*T_UTENTE*"]
    assert riletto.escludi_tabelle == ["TMP_*", "*_BAK"]
    assert riletto.escludi_viste == ["V_*"]
    assert riletto.categorie_ignorate == {"triggers"}
    assert riletto.accettate == {"z"}


def test_dialog_pulisci_svuota_tutto(app):
    dialog = DialogoFiltri(None, Regole(solo_tabelle=["A*"], escludi_tabelle=["B*"],
                                        categorie_ignorate={"views"}))
    dialog._pulisci()
    assert dialog._regole_correnti().vuote


def test_dialog_tutte_le_categorie_hanno_una_casella(app):
    dialog = DialogoFiltri(None, Regole())
    assert set(dialog.caselle_categorie) == set(rules.CATEGORIE)


# --- integrazione con la finestra ------------------------------------------


def test_la_finestra_salva_i_filtri_accanto_alla_config(app, config, monkeypatch):
    from diffdb.main_window import MainWindow

    finestra = MainWindow()
    scelte = Regole(solo_tabelle=["*T_UTENTE*"], escludi_tabelle=["TMP_*"])
    monkeypatch.setattr("diffdb.main_window._chiedi_filtri",
                        lambda parent, regole: scelte)

    finestra.modifica_filtri()

    percorso = config / rules.NOME_PREDEFINITO
    assert percorso.exists(), "il file delle regole doveva essere scritto"
    riletto = rules.carica(percorso)
    assert riletto.solo_tabelle == ["*T_UTENTE*"]
    assert riletto.escludi_tabelle == ["TMP_*"]
    # e la finestra usa subito le nuove regole
    assert finestra.regole.solo_tabelle == ["*T_UTENTE*"]


def test_annullare_il_dialog_non_cambia_le_regole(app, config, monkeypatch):
    from diffdb.main_window import MainWindow

    finestra = MainWindow()
    prima = finestra.regole
    monkeypatch.setattr("diffdb.main_window._chiedi_filtri", lambda parent, regole: None)

    finestra.modifica_filtri()

    assert finestra.regole is prima
    assert not (config / rules.NOME_PREDEFINITO).exists()
