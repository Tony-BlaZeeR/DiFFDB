"""Controllo aggiornamenti: logica delle versioni, lettura release, dialog Info.

Nessuna chiamata di rete vera: la si sostituisce (monkeypatch).
"""

import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import diffdb  # noqa: E402
from diffdb import preferences, updates  # noqa: E402
from diffdb.qt import QtWidgets  # noqa: E402
from diffdb.worker import UpdateCheckWorker  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    return tmp_path


# --- logica delle versioni -------------------------------------------------


def test_numeri_ignora_la_v_e_i_suffissi():
    assert updates._numeri("v1.10.0") == (1, 10, 0)
    assert updates._numeri("1.3.0") == (1, 3, 0)
    assert updates._numeri("2.0.0-rc1") == (2, 0, 0)


def test_confronto_numerico_non_lessicografico():
    # Come stringhe "1.10.0" < "1.9.0": qui deve risultare piu' recente.
    assert updates.e_piu_recente("1.10.0", "1.9.0") is True


@pytest.mark.parametrize("remota,corrente,atteso", [
    ("v1.4.0", "1.3.0", True),
    ("1.3.1", "1.3.0", True),
    ("1.3.0", "1.3.0", False),
    ("1.2.9", "1.3.0", False),
])
def test_e_piu_recente(remota, corrente, atteso):
    assert updates.e_piu_recente(remota, corrente) is atteso


# --- lettura dell'ultima release (rete simulata) ---------------------------


class _RispostaFinta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_ultima_release_legge_il_tag(monkeypatch):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: _RispostaFinta(json.dumps(
                            {"tag_name": "v2.5.0"}).encode()))
    assert updates.ultima_release() == "v2.5.0"


def test_ultima_release_senza_tag_solleva(monkeypatch):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: _RispostaFinta(json.dumps({}).encode()))
    with pytest.raises(ValueError):
        updates.ultima_release()


# --- worker ----------------------------------------------------------------


def test_worker_emette_il_tag(app, monkeypatch):
    monkeypatch.setattr(updates, "ultima_release", lambda timeout=6.0: "v9.9.9")
    visti = []
    w = UpdateCheckWorker()
    w.finished.connect(visti.append)
    w.run()
    assert visti == ["v9.9.9"]


def test_worker_segnala_errore(app, monkeypatch):
    def boom(timeout=6.0):
        raise OSError("niente rete")
    monkeypatch.setattr(updates, "ultima_release", boom)
    errori = []
    w = UpdateCheckWorker()
    w.failed.connect(errori.append)
    w.run()
    assert errori and "niente rete" in errori[0]


# --- dialog Info -----------------------------------------------------------


@pytest.fixture
def info(app, config):
    from diffdb import i18n, theme
    i18n.installa(app)
    theme.applica(app, theme.VARIANTE_MODERNA, theme.TEMA_SCURO, None)
    from diffdb.about_dialog import DialogoInfo
    return DialogoInfo(None)


def test_dialog_mostra_versione_piu_recente(info):
    info._esito_ok("v99.0.0")
    assert "99.0.0" in info.esito.text()
    assert "href" in info.esito.text()      # c'e' il link per scaricare


def test_dialog_versione_uguale_nessun_link(info):
    info._esito_ok(f"v{diffdb.__version__}")
    assert "href" not in info.esito.text()


def test_opt_in_spento_di_default_e_salvato_dalla_checkbox(info):
    assert preferences.controlla_aggiornamenti_avvio() is False
    info.auto.setChecked(True)
    assert preferences.controlla_aggiornamenti_avvio() is True
    info.auto.setChecked(False)
    assert preferences.controlla_aggiornamenti_avvio() is False


# --- finestra --------------------------------------------------------------


def test_la_finestra_non_controlla_se_opt_in_spento(app, config, monkeypatch):
    # Opt-in spento (default): nessuna lettura di rete all'avvio.
    chiamate = []
    monkeypatch.setattr(updates, "ultima_release",
                        lambda timeout=6.0: chiamate.append(1) or "v1.0.0")
    from diffdb.main_window import MainWindow
    win = MainWindow()
    win._ferma_upd_thread()
    assert hasattr(win, "info_button")
    assert chiamate == []
