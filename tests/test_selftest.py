"""L'autodiagnosi dei driver.

Attenzione a cosa questi test possono e non possono dimostrare: girano da
sorgente, dove i driver sono installati, quindi verificano la *logica* del
report, non che il bundle PyInstaller sia completo. Quello lo controlla la CI
eseguendo `--selftest` sul binario appena costruito (vedi ci.yml).
"""

from __future__ import annotations

import sys

import diffdb.selftest as selftest


def test_ambiente_di_sviluppo_e_completo():
    """Da sorgente tutti i driver ci sono: l'esito deve essere 0."""
    assert selftest.esegui() == 0


def test_scrive_il_report_su_file(tmp_path, monkeypatch):
    """Su Windows l'eseguibile non ha console: il report su file e' l'unico
    modo di sapere quale modulo manca."""
    monkeypatch.chdir(tmp_path)
    selftest.esegui()
    report = tmp_path / selftest.NOME_REPORT
    assert report.exists()
    assert "Autodiagnosi OK" in report.read_text(encoding="utf-8")


def test_segnala_il_modulo_mancante(tmp_path, monkeypatch):
    """Il caso che conta: un driver assente deve dare esito 1 e comparire nel
    report col suo nome, altrimenti in CI non si capisce cosa aggiungere."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        selftest, "MODULI", [("modulo_che_non_esiste_davvero", "driver finto")]
    )

    assert selftest.esegui() == 1

    report = (tmp_path / selftest.NOME_REPORT).read_text(encoding="utf-8")
    assert "modulo_che_non_esiste_davvero" in report
    assert "Autodiagnosi FALLITA" in report


def test_su_macos_pymssql_e_saltato_non_bocciato(tmp_path, monkeypatch):
    """Su macOS pymssql e' escluso dal bundle di proposito: la sua assenza
    deve essere l'esito giusto, altrimenti la build macOS non passerebbe
    mai."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(selftest, "MODULI", [("pymssql", "driver SQL Server")])

    assert selftest.esegui() == 0

    report = (tmp_path / selftest.NOME_REPORT).read_text(encoding="utf-8")
    assert "salto" in report
    assert "Autodiagnosi OK" in report


def test_su_macos_un_driver_davvero_mancante_boccia(tmp_path, monkeypatch):
    """L'eccezione per pymssql non deve diventare un'amnistia generale: su
    macOS gli altri driver restano obbligatori."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        selftest, "MODULI", [("modulo_che_non_esiste_davvero", "driver finto")]
    )

    assert selftest.esegui() == 1


def test_pymssql_resta_atteso_fuori_da_macos(monkeypatch):
    """Su Windows e Linux SQL Server e' supportato: niente deroghe."""
    for piattaforma in ("win32", "linux"):
        monkeypatch.setattr(sys, "platform", piattaforma)
        assert "pymssql" not in selftest.NON_ATTESI.get(piattaforma, {})


def test_copre_cryptography_e_oracle():
    """La regressione da cui nasce tutto: senza queste voci il DPY-3016
    tornerebbe a passare inosservato."""
    nomi = [nome for nome, _ in selftest.MODULI]
    assert "oracledb" in nomi
    assert "cryptography" in nomi
    assert "cryptography.hazmat.bindings._rust" in nomi


def test_copre_anche_l_export_excel():
    """La seconda regressione dello stesso tipo: numpy impacchettato a meta'
    faceva fallire pandas, e l'app diceva "manca pandas" consigliando un pip
    install inutile. Da sorgente nessun test poteva accorgersene."""
    nomi = [nome for nome, _ in selftest.MODULI]
    assert "numpy" in nomi
    assert "pandas" in nomi
    assert "openpyxl" in nomi
