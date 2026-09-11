"""Dove finiscono le password.

La proprieta' che conta: quello che si scrive su disco non deve mai essere un
segreto, e quello che esce dal processo (log, finestre, file) non deve mai
contenerne uno.
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import keystore, log  # noqa: E402
from diffdb.connections import Connection, con_riferimento_al_portachiavi  # noqa: E402
from diffdb.urls import (  # noqa: E402
    KEYRING_TOKEN,
    VARIABILE_POLICY,
    PasswordInChiaro,
    expand,
    mask_password,
    password_letterale,
    sanitize,
)

SEGRETO = "pa/ss@wo:rd$1"


@pytest.fixture
def portachiavi_finto(monkeypatch):
    """Portachiavi in memoria: i test non devono toccare quello vero."""
    voci = {}
    monkeypatch.setattr(keystore, "disponibile", lambda: True)
    monkeypatch.setattr(keystore, "descrizione", lambda: "PortachiaviFinto")
    monkeypatch.setattr(keystore, "leggi", voci.get)
    monkeypatch.setattr(keystore, "scrivi", lambda nome, pw: voci.__setitem__(nome, pw))
    monkeypatch.setattr(keystore, "elimina", lambda nome: voci.pop(nome, None) is not None)
    return voci


# --- risoluzione dei segreti ----------------------------------------------


def test_la_password_arriva_dal_portachiavi(portachiavi_finto):
    portachiavi_finto["PROD"] = SEGRETO
    risolto = expand(f"postgresql://app:{KEYRING_TOKEN}@host:5432/db", name="PROD")

    assert KEYRING_TOKEN not in risolto
    # Codificata, altrimenti '@' e '/' spezzerebbero l'URL.
    assert "pa%2Fss%40wo%3Ard%241" in risolto


def test_la_password_del_portachiavi_non_viene_reinterpretata(portachiavi_finto, monkeypatch):
    """Una password che contiene $ non deve essere espansa come variabile."""
    monkeypatch.setenv("UNA_VARIABILE", "SBAGLIATO")
    portachiavi_finto["PROD"] = "${UNA_VARIABILE}"

    risolto = expand(f"postgresql://app:{KEYRING_TOKEN}@host/db", name="PROD")

    assert "SBAGLIATO" not in risolto


def test_le_variabili_d_ambiente_funzionano_ancora(monkeypatch):
    monkeypatch.setenv("PROD_DB_PWD", "dallambiente")
    assert "dallambiente" in expand("postgresql://app:${PROD_DB_PWD}@host/db", name="PROD")


def test_senza_password_nel_portachiavi_l_errore_dice_cosa_fare(portachiavi_finto):
    with pytest.raises(keystore.KeystoreNonDisponibile, match="--set-password PROD"):
        expand(f"postgresql://app:{KEYRING_TOKEN}@host/db", name="PROD")


def test_senza_portachiavi_l_errore_dice_perche(monkeypatch):
    monkeypatch.setattr(keystore, "disponibile", lambda: False)
    monkeypatch.setattr(keystore, "descrizione", lambda: "nessun backend")

    with pytest.raises(keystore.KeystoreNonDisponibile, match="nessun backend"):
        expand(f"postgresql://app:{KEYRING_TOKEN}@host/db", name="PROD")


# --- policy ----------------------------------------------------------------


@pytest.mark.parametrize("conn_string, atteso", [
    ("postgresql://app:segreta@host/db", "segreta"),
    (f"postgresql://app:{KEYRING_TOKEN}@host/db", None),
    ("postgresql://app:${PROD_PWD}@host/db", None),
    ("postgresql://app:%PROD_PWD%@host/db", None),
    ("postgresql://app@host/db", None),      # nessuna password
    ("sqlite:///percorso/a.db", None),       # nessuna credenziale
])
def test_riconosce_una_password_in_chiaro(conn_string, atteso):
    assert password_letterale(conn_string) == atteso


def test_la_policy_rifiuta_le_password_in_chiaro(monkeypatch):
    monkeypatch.setenv(VARIABILE_POLICY, "1")
    with pytest.raises(PasswordInChiaro, match="PROD"):
        expand("postgresql://app:segreta@host/db", name="PROD")


def test_senza_policy_si_passa_ma_con_un_avviso(monkeypatch, caplog):
    monkeypatch.delenv(VARIABILE_POLICY, raising=False)
    with caplog.at_level(logging.WARNING):
        assert expand("postgresql://app:segreta@host/db", name="PROD")
    assert "in chiaro" in caplog.text


# --- niente segreti in uscita ----------------------------------------------


def test_mascheramento_di_una_password_letterale():
    assert mask_password("postgresql://app:segreta@host:5432/db") == \
        "postgresql://app:****@host:5432/db"


def test_i_riferimenti_restano_visibili():
    """Non sono segreti, e vederli dice all'utente dove sta davvero la password."""
    for url in (f"postgresql://app:{KEYRING_TOKEN}@host/db",
                "postgresql://app:${PROD_PWD}@host/db"):
        assert mask_password(url) == url


def test_sanitize_maschera_gli_url_dentro_un_errore():
    testo = ("(psycopg2.OperationalError) connection to "
             "postgresql://app:segretissima@host:5432/db failed")
    ripulito = sanitize(testo)

    assert "segretissima" not in ripulito
    assert "postgresql://app:****@host:5432/db" in ripulito


def test_sanitize_ne_maschera_piu_di_uno():
    ripulito = sanitize("mysql://root:pw1@a/db e oracle+oracledb://sys:pw2@b:1521/x")
    assert "pw1" not in ripulito and "pw2" not in ripulito


def test_il_log_su_file_non_contiene_password(tmp_path, monkeypatch):
    """La sanificazione sta nel formatter, quindi passa anche il traceback."""
    monkeypatch.setenv("DIFFDB_HOME", str(tmp_path))
    percorso = log.configure(su_file=True)
    try:
        logger = logging.getLogger("prova.segreti")
        try:
            raise RuntimeError("connect to postgresql://app:segretissima@host/db failed")
        except RuntimeError:
            logger.exception("confronto fallito")

        for handler in logging.getLogger().handlers:
            handler.flush()
        testo = Path(percorso).read_text(encoding="utf-8")
    finally:
        log.configure(su_file=False)

    assert "segretissima" not in testo
    assert "postgresql://app:****@host/db" in testo


# --- passaggio al portachiavi ----------------------------------------------


def test_sostituzione_della_password_con_il_segnaposto():
    assert con_riferimento_al_portachiavi("postgresql://app:segreta@host:5432/db") == \
        f"postgresql://app:{KEYRING_TOKEN}@host:5432/db"


def test_il_segnaposto_e_riconoscibile():
    from diffdb.connections import usa_portachiavi

    assert usa_portachiavi(Connection("PROD", f"postgresql://app:{KEYRING_TOKEN}@h/db"))
    assert not usa_portachiavi(Connection("PROD", "postgresql://app:segreta@h/db"))
