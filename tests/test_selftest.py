"""L'autodiagnosi dei driver.

Attenzione a cosa questi test possono e non possono dimostrare: girano da
sorgente, dove i driver sono installati, quindi verificano la *logica* del
report, non che il bundle PyInstaller sia completo. Quello lo controlla la CI
eseguendo `--selftest` sul binario appena costruito (vedi ci.yml).
"""

from __future__ import annotations

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


def test_copre_cryptography_e_oracle():
    """La regressione da cui nasce tutto: senza queste voci il DPY-3016
    tornerebbe a passare inosservato."""
    nomi = [nome for nome, _ in selftest.MODULI]
    assert "oracledb" in nomi
    assert "cryptography" in nomi
    assert "cryptography.hazmat.bindings._rust" in nomi
