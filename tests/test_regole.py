"""Regole di confronto: filtri e differenze accettate.

Sono il meccanismo che rende il confronto usabile su uno schema vero, dove la
maggior parte delle differenze e' rumore. Quello che va difeso qui e' che il
filtro tolga *solo* quello che deve, e che una differenza accettata torni a
farsi vedere quando cambia.
"""

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import rules, snapshot_io  # noqa: E402
from diffdb.diff_DB import compare_environments, generate_sql_scripts  # noqa: E402
from diffdb.schema_snapshot import (  # noqa: E402
    SECONDI_CONNESSIONE,
    connect_args_per,
    crea_engine,
    snapshot_connection,
)  # noqa: E402

SVI = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50), email VARCHAR(120))",
    "CREATE TABLE ordini (id INTEGER PRIMARY KEY, cliente_id INTEGER, "
    "FOREIGN KEY (cliente_id) REFERENCES clienti (id))",
    "CREATE VIEW clienti_attivi AS SELECT id FROM clienti",
]
# Collaudo ha meno schema applicativo e in piu' un po' di rumore.
COL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(30))",
    "CREATE TABLE TMP_IMPORT (id INTEGER)",
    "CREATE TABLE BCK_CLIENTI (id INTEGER)",
    "CREATE TABLE ordini_20240101 (id INTEGER)",
    "CREATE VIEW v_debug AS SELECT id FROM clienti",
]


def _crea(url, istruzioni):
    motore = create_engine(url)
    with motore.begin() as conn:
        for istruzione in istruzioni:
            conn.execute(text(istruzione))
    motore.dispose()


@pytest.fixture
def ambienti(tmp_path):
    svi, col = f"sqlite:///{tmp_path/'svi.db'}", f"sqlite:///{tmp_path/'col.db'}"
    _crea(svi, SVI)
    _crea(col, COL)
    return svi, col


@pytest.fixture
def regole_rumore():
    return rules.da_dizionario(
        {"escludi": {"tabelle": ["TMP_*", "BCK_*", "*_20??????"], "viste": ["v_debug"]}})


# --- corrispondenza dei modelli --------------------------------------------


@pytest.mark.parametrize("nome, atteso", [
    ("TMP_IMPORT", False),
    ("tmp_import", False),      # Oracle restituisce maiuscolo, PostgreSQL minuscolo
    ("BCK_CLIENTI", False),
    ("ordini_20240101", False),
    ("clienti", True),
    ("TEMPORANEE", True),       # 'TMP_*' non deve pescare qualunque cosa inizi per TMP
])
def test_i_modelli_pescano_solo_quello_che_devono(regole_rumore, nome, atteso):
    assert regole_rumore.tabella_inclusa(nome) is atteso


def test_includi_solo_esclude_tutto_il_resto():
    regole = rules.da_dizionario({"includi_solo": {"tabelle": ["FATT_*"]}})
    assert regole.tabella_inclusa("FATT_TESTA")
    assert not regole.tabella_inclusa("clienti")


def test_una_categoria_spenta_sparisce(ambienti):
    regole = rules.da_dizionario({"escludi": {"categorie": ["views"]}})
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1], regole=regole)
    assert diff.views == []


def test_una_categoria_sconosciuta_e_un_errore_esplicito():
    """Un refuso nel file non deve spegnere in silenzio qualcosa d'altro."""
    with pytest.raises(rules.RegoleNonValide, match="categorie sconosciute"):
        rules.da_dizionario({"escludi": {"categorie": ["tabelle"]}})


# --- effetto sul confronto --------------------------------------------------


def test_i_filtri_tolgono_il_rumore_e_non_altro(ambienti, regole_rumore):
    senza = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    con = compare_environments("SVI", ambienti[0], "COL", ambienti[1], regole=regole_rumore)

    tolte = {d.name for d in senza.all} - {d.name for d in con.all}
    assert tolte == {"TMP_IMPORT", "BCK_CLIENTI", "ordini_20240101", "v_debug"}
    # Le differenze vere restano tutte.
    assert {d.name for d in con.all} == {"ordini", "clienti", "clienti_attivi"}


def test_le_tabelle_escluse_non_vengono_nemmeno_lette(ambienti, regole_rumore):
    """Il filtro serve anche a risparmiare tempo: su uno schema grande la
    riflessione e' quasi tutto il confronto."""
    snapshot = snapshot_connection("COL", ambienti[1], regole=regole_rumore)
    assert set(snapshot.tables) == {"clienti"}


def test_una_tabella_esclusa_ma_referenziata_non_rompe_il_ddl(ambienti):
    """SQLAlchemy riflette comunque le tabelle puntate da una foreign key.
    Devono restare fuori dal confronto ma dentro il metadata, o il CREATE TABLE
    di chi le referenzia non si compilerebbe."""
    regole = rules.da_dizionario({"escludi": {"tabelle": ["clienti"]}})
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1], regole=regole)

    assert "clienti" not in {d.name for d in diff.all}
    ddl = generate_sql_scripts(diff, "COL")["tables"]
    assert any("CREATE TABLE ordini" in istruzione for istruzione in ddl)


# --- differenze accettate ---------------------------------------------------


def test_una_differenza_accettata_non_si_vede_ma_si_conta(ambienti):
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    regole = rules.Regole(accettate={rules.chiave(d) for d in diff.all})

    dopo = compare_environments("SVI", ambienti[0], "COL", ambienti[1], regole=regole)

    assert dopo.all == []
    assert dopo.accettate == len(diff.all)


def test_una_differenza_nuova_torna_a_farsi_vedere(ambienti):
    """E' il punto della baseline: verde finche' non cambia qualcosa."""
    diff = compare_environments("SVI", ambienti[0], "COL", ambienti[1])
    regole = rules.Regole(accettate={rules.chiave(d) for d in diff.all})

    _crea(ambienti[1], ["ALTER TABLE clienti ADD COLUMN telefono VARCHAR(20)"])
    dopo = compare_environments("SVI", ambienti[0], "COL", ambienti[1], regole=regole)

    assert [(d.name, d.column) for d in dopo.all] == [("clienti", "telefono")]


def test_la_chiave_non_dipende_dal_dettaglio():
    """Una colonna che passa da VARCHAR(50) a VARCHAR(80) resta la stessa
    differenza gia' accettata."""
    from diffdb.diff_DB import TYPE_MISMATCH, Difference

    prima = Difference("column", "clienti", TYPE_MISMATCH, column="nome", detail="50 vs 30")
    dopo = Difference("column", "clienti", TYPE_MISMATCH, column="nome", detail="80 vs 30")
    assert rules.chiave(prima) == rules.chiave(dopo)


def test_la_chiave_distingue_il_tipo_di_differenza():
    from diffdb.diff_DB import MISSING, TYPE_MISMATCH, Difference

    manca = Difference("column", "clienti", MISSING, column="nome")
    diversa = Difference("column", "clienti", TYPE_MISMATCH, column="nome")
    assert rules.chiave(manca) != rules.chiave(diversa)


# --- impronta ---------------------------------------------------------------


def test_l_impronta_cambia_se_cambiano_i_filtri(ambienti, regole_rumore):
    """Senza questo, uno script generato con altre regole passerebbe --verify."""
    libera = snapshot_io.fingerprint(snapshot_connection("COL", ambienti[1]))
    filtrata = snapshot_io.fingerprint(
        snapshot_connection("COL", ambienti[1], regole=regole_rumore))
    assert libera != filtrata


def test_senza_filtri_l_impronta_resta_quella_di_prima(ambienti):
    """Le regole vuote non devono cambiare l'impronta degli snapshot esistenti."""
    senza = snapshot_connection("COL", ambienti[1])
    assert snapshot_io.to_dict(senza)["regole"] is None


def test_i_filtri_sopravvivono_al_salvataggio(ambienti, regole_rumore, tmp_path):
    """Lo snapshot riletto deve avere la stessa impronta del file, altrimenti
    --verify su una baseline filtrata non tornerebbe mai."""
    dal_vivo = snapshot_connection("COL", ambienti[1], regole=regole_rumore)
    percorso = snapshot_io.save(dal_vivo, tmp_path / "col.json")

    salvata = json.loads(percorso.read_text(encoding="utf-8"))["fingerprint"]
    riletto = snapshot_io.load(percorso)

    assert snapshot_io.fingerprint(riletto) == salvata == snapshot_io.fingerprint(dal_vivo)
    # Il file li salva ordinati: e' la forma canonica su cui si calcola l'impronta.
    assert set(riletto.regole.escludi_tabelle) == set(regole_rumore.escludi_tabelle)


def test_le_accettate_non_entrano_nell_impronta(ambienti):
    """Accettare una differenza non cambia cosa si e' letto dal database."""
    pulite = rules.Regole()
    con_accettate = rules.Regole(accettate={"qualcosa"})
    assert pulite.firma() == con_accettate.firma() is None


# --- file delle regole ------------------------------------------------------


def test_salvataggio_e_rilettura(tmp_path, regole_rumore):
    regole_rumore.accettate = {"table|ordini||mancante|COL"}
    percorso = rules.salva(regole_rumore, tmp_path / rules.NOME_PREDEFINITO)
    riletto = rules.carica(percorso)

    assert riletto.escludi_tabelle == sorted(regole_rumore.escludi_tabelle)
    assert riletto.accettate == regole_rumore.accettate


def test_un_formato_futuro_viene_rifiutato(tmp_path):
    percorso = tmp_path / "regole.json"
    percorso.write_text(json.dumps({"format": rules.FORMATO + 1}), encoding="utf-8")
    with pytest.raises(rules.RegoleNonValide, match="formato"):
        rules.carica(percorso)


def test_un_json_rotto_lo_dice(tmp_path):
    percorso = tmp_path / "regole.json"
    percorso.write_text("{non e' json", encoding="utf-8")
    with pytest.raises(rules.RegoleNonValide, match="JSON"):
        rules.carica(percorso)


def test_cerca_trova_il_file_predefinito(tmp_path):
    assert rules.cerca([tmp_path]) is None
    (tmp_path / rules.NOME_PREDEFINITO).write_text("{}", encoding="utf-8")
    assert rules.cerca([tmp_path]) == tmp_path / rules.NOME_PREDEFINITO


# --- connessione ------------------------------------------------------------


@pytest.mark.parametrize("url, parametro", [
    ("postgresql+psycopg2://u:p@h/d", "connect_timeout"),
    ("mysql+pymysql://u:p@h/d", "connect_timeout"),
    ("mssql+pymssql://u:p@h/d", "login_timeout"),
    ("oracle+oracledb://u:p@h/d", "tcp_connect_timeout"),
])
def test_ogni_driver_riceve_il_suo_timeout(url, parametro):
    """Senza timeout un host irraggiungibile blocca per il timeout di sistema,
    che su TCP puo' essere di minuti."""
    assert connect_args_per(url).get(parametro) == SECONDI_CONNESSIONE


def test_la_lettura_in_parallelo_restituisce_entrambi(ambienti):
    from diffdb.diff_DB import leggi_in_parallelo

    primo, secondo = leggi_in_parallelo(("SVI", ambienti[0], None),
                                        ("COL", ambienti[1], None))
    assert primo.env_name == "SVI" and secondo.env_name == "COL"
    assert "ordini" in primo.tables


def test_annullare_chiude_le_connessioni(ambienti):
    from diffdb.schema_snapshot import Annullabile

    annullabile = Annullabile()
    motore = crea_engine(ambienti[0])
    annullabile.registra(motore)

    annullabile.annulla()

    assert annullabile.annullato
    # Un engine gia' registrato viene chiuso; uno registrato dopo, subito.
    altro = crea_engine(ambienti[0])
    annullabile.registra(altro)
