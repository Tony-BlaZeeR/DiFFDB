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


# --- connessioni, confronto, export ----------------------------------------
#
# Flussi che prima non avevano test: la tabella delle connessioni, la
# validazione del confronto e la scrittura dei file. Girano senza database e
# senza thread — i worker e le finestre di dialogo native vengono sostituiti.


@pytest.fixture
def finestra(app, config):
    from diffdb.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


@pytest.fixture
def box(monkeypatch):
    """Intercetta i message box: nessun popup, ma si sa cosa e' stato mostrato."""
    registro = {"warning": [], "information": [], "critical": []}

    def falso(tipo, risposta=None):
        def _finto(parent, titolo, testo, *a, **k):
            registro[tipo].append((titolo, testo))
            return risposta
        return _finto

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", falso("warning"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", falso("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", falso("critical"))
    return registro


def _conn(nome, stringa="postgresql+psycopg2://app:${keyring}@host:5432/db", schema=None):
    from diffdb.connections import Connection
    return Connection(name=nome, conn_string=stringa, schema=schema)


def test_aggiungi_connessione_compare_in_tabella(finestra, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(main_window, "ask_connection", lambda *a, **k: _conn("SVI"))

    prima = finestra.conn_table().rowCount()
    finestra.add_connection()

    assert finestra.connections[-1].name == "SVI"
    assert finestra.conn_table().rowCount() == prima + 1


def test_aggiungi_connessione_annullata_non_cambia_nulla(finestra, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(main_window, "ask_connection", lambda *a, **k: None)

    prima = len(finestra.connections)
    finestra.add_connection()
    assert len(finestra.connections) == prima


def test_modifica_connessione_sostituisce_la_riga(finestra, monkeypatch):
    from diffdb import main_window
    finestra.connections = [_conn("SVI")]
    finestra.refresh_conn_table()
    monkeypatch.setattr(main_window, "ask_connection", lambda *a, **k: _conn("COLLAUDO"))

    finestra.edit_connection(0)
    assert finestra.connections[0].name == "COLLAUDO"


def test_modifica_connessione_indice_fuori_scala_non_esplode(finestra):
    finestra.connections = [_conn("SVI")]
    finestra.edit_connection(9)          # niente eccezioni, niente cambi
    assert finestra.connections[0].name == "SVI"


def test_elimina_connessione_chiede_conferma(finestra, monkeypatch):
    si = QtWidgets.QMessageBox.StandardButton.Yes
    no = QtWidgets.QMessageBox.StandardButton.No
    monkeypatch.setattr("diffdb.keystore.elimina", lambda nome: False)

    finestra.connections = [_conn("SVI"), _conn("COLLAUDO")]
    finestra.refresh_conn_table()

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **k: no)
    finestra.delete_connection(0)
    assert [c.name for c in finestra.connections] == ["SVI", "COLLAUDO"]

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **k: si)
    finestra.delete_connection(0)
    assert [c.name for c in finestra.connections] == ["COLLAUDO"]


def test_la_pastiglia_dice_dove_sta_la_password(finestra):
    casi = {
        "postgresql://app:${keyring}@h/db": "buona",
        "postgresql://app:segreta@h/db": "allarme",
        "postgresql://app:${PROD_PWD}@h/db": "neutra",
        "sqlite:///locale.db": "neutra",
    }
    for stringa, atteso in casi.items():
        etichetta = finestra._pastiglia_password(_conn("X", stringa))
        assert etichetta.property("pastiglia") == atteso


def test_confronto_senza_due_connessioni_avverte(finestra, box):
    finestra.connections = []
    finestra.refresh_comboboxes()
    finestra.start_comparison()
    assert box["warning"]                      # un avviso, non un crash


def test_confronto_tra_ambienti_uguali_avverte(finestra, box, monkeypatch):
    # Due nomi diversi in lista ma, forzando la stessa scelta, stesso ambiente.
    svi = _conn("SVI")
    finestra.connections = [svi]
    monkeypatch.setattr(finestra, "selected_connections", lambda: (svi, svi))
    finestra.start_comparison()
    assert box["warning"]


def test_confronto_valido_parte_senza_toccare_il_db(finestra, monkeypatch):
    lanciati = []
    monkeypatch.setattr(finestra, "selected_connections", lambda: (_conn("A"), _conn("B")))
    monkeypatch.setattr(finestra, "_run", lambda worker, on_fine: lanciati.append(worker))

    finestra.start_comparison()
    assert lanciati                            # e' stato avviato un worker
    assert finestra.choose_tab._stack.currentIndex() == finestra.choose_tab.PAGINA_AVANZAMENTO


def _diff(vuoto=True):
    from diffdb.diff_DB import DiffResult
    from diffdb.schema_snapshot import Snapshot
    res = DiffResult(Snapshot("SVI", "sqlite"), Snapshot("COLLAUDO", "sqlite"))
    if not vuoto:
        from diffdb.diff_DB import Difference
        res.tables.append(Difference(kind="table", name="T", change="mancante",
                                     present_in="SVI", missing_in="COLLAUDO",
                                     detail="manca"))
    return res


def test_confronto_concluso_senza_differenze(finestra):
    from diffdb.main_window import TAB_RISULTATI
    finestra.on_comparison_done(_diff(vuoto=True))
    assert finestra.tabWidget.currentIndex() == TAB_RISULTATI
    assert finestra.results_tab._stack.currentIndex() == 1   # pagina "nessuna differenza"
    assert preferences.ultimo_confronto() is not None        # annotato per la Home


def test_confronto_concluso_con_differenze(finestra):
    finestra.on_comparison_done(_diff(vuoto=False))
    assert "1" in finestra.choose_tab.status_label.text()


def test_confronto_fallito_mostra_la_schermata_di_errore(finestra):
    from diffdb.main_window import TAB_SCELTA
    finestra.on_comparison_failed("ORA-12541: TNS:no listener")
    assert finestra.tabWidget.currentIndex() == TAB_SCELTA
    assert finestra.choose_tab._stack.currentIndex() == finestra.choose_tab.PAGINA_ERRORE
    assert "ORA-12541" in finestra.choose_tab.err_messaggio.text()


def test_snapshot_salvato_conferma(finestra, box):
    finestra.on_snapshot_saved("/tmp/snap.json")
    assert finestra.choose_tab._stack.currentIndex() == finestra.choose_tab.PAGINA_SCELTA
    assert box["information"]


def test_operazione_annullata_torna_alla_scelta(finestra):
    finestra.on_annullato()
    assert finestra.choose_tab._stack.currentIndex() == finestra.choose_tab.PAGINA_SCELTA
    assert "annull" in finestra.choose_tab.status_label.text().lower()


def test_modifica_db2_apre_la_connessione_da_allineare(finestra, monkeypatch):
    from diffdb import main_window
    from diffdb.main_window import TAB_CONFIGURAZIONE
    finestra.connections = [_conn("SVI"), _conn("COLLAUDO")]
    monkeypatch.setattr(finestra, "selected_connections",
                        lambda: (_conn("SVI"), _conn("COLLAUDO")))
    aperte = []
    monkeypatch.setattr(main_window, "ask_connection",
                        lambda parent, c=None: aperte.append(c) or None)

    finestra._modifica_db2()
    assert finestra.tabWidget.currentIndex() == TAB_CONFIGURAZIONE
    assert aperte and aperte[0].name == "COLLAUDO"   # ha aperto proprio la seconda


def test_ripeti_confronto_su_ambiente_sparito_avverte(finestra, box, monkeypatch):
    from diffdb.main_window import TAB_SCELTA
    finestra.connections = [_conn("SVI")]
    finestra.refresh_comboboxes()
    monkeypatch.setattr(finestra, "start_comparison", lambda: None)

    finestra.ripeti_confronto("SVI", "NON_ESISTE")
    assert box["warning"]
    assert finestra.tabWidget.currentIndex() == TAB_SCELTA


def test_export_excel_scrive_e_conferma(finestra, box, config, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(finestra, "_ask_output_dir", lambda: str(config))
    monkeypatch.setattr(main_window, "write_excel", lambda diff, d: f"{d}/diff.xlsx")

    finestra.export_excel(_diff())
    assert box["information"]


def test_export_excel_annullato_non_scrive(finestra, box, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(finestra, "_ask_output_dir", lambda: "")   # dialogo annullato
    chiamato = []
    monkeypatch.setattr(main_window, "write_excel", lambda *a: chiamato.append(1))

    finestra.export_excel(_diff())
    assert not chiamato and not box["information"]


def test_export_excel_errore_mostra_critico(finestra, box, config, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(finestra, "_ask_output_dir", lambda: str(config))

    def esplode(diff, d):
        raise OSError("disco pieno")
    monkeypatch.setattr(main_window, "write_excel", esplode)

    finestra.export_excel(_diff())
    assert box["critical"]


def test_export_sql_senza_script_lo_dice(finestra, box, config, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(finestra, "_ask_output_dir", lambda: str(config))
    monkeypatch.setattr(main_window, "write_sql", lambda diff, d, totali=None: [])

    finestra.export_sql(_diff())
    assert box["information"]
    assert "generare" in box["information"][0][0].lower()   # il titolo lo dice


def test_export_sql_scrive_i_file(finestra, box, config, monkeypatch):
    from diffdb import main_window
    monkeypatch.setattr(finestra, "_ask_output_dir", lambda: str(config))
    monkeypatch.setattr(main_window, "write_sql",
                        lambda diff, d, totali=None: [f"{d}/allinea.sql"])

    finestra.export_sql(_diff())
    assert box["information"]
    assert "allinea.sql" in box["information"][0][1]


def test_massimizza_cambia_il_simbolo(finestra):
    finestra.showNormal()
    testo = finestra.maximize_button.text()
    finestra.toggle_maximized()
    assert finestra.maximize_button.text() != testo
    finestra.toggle_maximized()


def test_le_scanline_compaiono_solo_nel_retro(finestra, app):
    from diffdb import preferences, theme
    preferences.imposta_variante(theme.VARIANTE_RETRO)
    finestra._applica_tema()
    # isVisible() e' False finche' la finestra non e' a schermo: conta isHidden().
    assert finestra.scanline is not None and not finestra.scanline.isHidden()
    finestra.scanline.resize(80, 40)
    assert not finestra.scanline.grab().isNull()   # il paint delle righe non esplode

    preferences.imposta_variante(theme.VARIANTE_MODERNA)
    finestra._applica_tema()
    assert finestra.scanline.isHidden()
