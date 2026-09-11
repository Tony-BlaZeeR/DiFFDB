"""Test degli snapshot su file.

La proprieta' che conta: uno snapshot riletto deve essere indistinguibile
dall'originale letto dal vivo. Se il round-trip perde qualcosa, il confronto
inventa differenze che non esistono e la drift detection diventa inutilizzabile.
"""

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb import snapshot_io  # noqa: E402
from diffdb.connections import Connection  # noqa: E402
from diffdb.diff_DB import compare_snapshots, generate_sql_scripts  # noqa: E402
from diffdb.schema_snapshot import snapshot_connection  # noqa: E402
from diffdb.snapshot_io import (  # noqa: E402
    FORMAT_VERSION,
    RawType,
    SnapshotFile,
    SnapshotFormatError,
    compare_sources,
    looks_like_snapshot,
    type_from_text,
)

# Schema con tutto quello che il round-trip deve conservare: PK composta,
# default lato server, unique, foreign key, indice e vista.
DDL = [
    "CREATE TABLE clienti (id INTEGER PRIMARY KEY, nome VARCHAR(50) NOT NULL, "
    "email VARCHAR(120), saldo NUMERIC(10, 2) DEFAULT 0, note TEXT, "
    "partita_iva VARCHAR(11), UNIQUE (partita_iva))",
    "CREATE TABLE ordini (id INTEGER, riga INTEGER, cliente_id INTEGER NOT NULL, "
    "totale NUMERIC(10, 2), PRIMARY KEY (id, riga), "
    "FOREIGN KEY (cliente_id) REFERENCES clienti (id))",
    "CREATE INDEX ix_clienti_email ON clienti (email)",
    "CREATE VIEW clienti_attivi AS SELECT id, nome FROM clienti WHERE email IS NOT NULL",
]


@pytest.fixture
def live(tmp_path):
    url = f"sqlite:///{tmp_path / 'svi.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
    engine.dispose()
    return snapshot_connection("SVI", url), url


@pytest.fixture
def riletto(live, tmp_path):
    snapshot, url = live
    return snapshot_io.load(snapshot_io.save(snapshot, tmp_path / "svi.json", source=url))


def test_round_trip_non_inventa_differenze(live, riletto):
    """Il test che tiene in piedi tutto il resto."""
    assert compare_snapshots(live[0], riletto).all == []


def test_round_trip_conserva_il_ddl(live, riletto, tmp_path):
    """Lo snapshot da file deve generare lo stesso SQL di quello dal vivo."""
    vuoto = snapshot_connection("COL", f"sqlite:///{tmp_path / 'col.db'}")
    dal_vivo = generate_sql_scripts(compare_snapshots(live[0], vuoto), "COL")
    da_file = generate_sql_scripts(compare_snapshots(riletto, vuoto), "COL")
    assert da_file == dal_vivo


def test_conserva_ordine_della_chiave_composta(riletto):
    assert riletto.primary_key("ordini") == ("id", "riga")


def test_conserva_il_default_come_sql_non_come_stringa(riletto, tmp_path):
    """Passare il default come stringa produrrebbe DEFAULT '0' invece di DEFAULT 0."""
    vuoto = snapshot_connection("COL", f"sqlite:///{tmp_path / 'col.db'}")
    ddl = "\n".join(generate_sql_scripts(compare_snapshots(riletto, vuoto), "COL")["tables"])
    assert "DEFAULT 0" in ddl
    assert "DEFAULT '0'" not in ddl


def test_l_autoincrement_sopravvive_al_round_trip(live, riletto):
    """Quanto vale dipende dal dialetto (PostgreSQL riflette False, SQLite 'auto'):
    quello che conta e' che il file non lo cambi."""
    originale, _ = live
    for tabella in ("clienti", "ordini"):
        assert ({c: col.autoincrement for c, col in riletto.columns(tabella).items()}
                == {c: col.autoincrement for c, col in originale.columns(tabella).items()})


def test_senza_il_flag_non_si_inventa_un_serial(tmp_path):
    """Il caso che rompeva l'allineamento da baseline su PostgreSQL.

    Ricostruendo la tabella, SQLAlchemy decide da se' che un intero in chiave
    primaria e' auto-incrementante e lo riemette come SERIAL: la tabella creata
    avrebbe una sequenza e un default che l'originale non ha.
    """
    payload = {
        "format": FORMAT_VERSION, "env_name": "PROD", "dialect": "postgresql", "schema": None,
        "tables": {
            "ordini": {
                # Nessuna chiave "autoincrement": il default deve essere prudente.
                "columns": [{"name": "id", "type": "INTEGER", "nullable": False,
                             "server_default": None}],
                "primary_key": ["id"],
                "indexes": [], "unique_constraints": [], "foreign_keys": [],
            }
        },
        "views": {}, "sequences": {}, "synonyms": {},
    }
    path = tmp_path / "prod.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    prod = snapshot_io.load(path)
    assert prod.columns("ordini")["id"].autoincrement is False

    vuoto = snapshot_connection("PRE", f"sqlite:///{tmp_path / 'pre.db'}")
    ddl = "\n".join(generate_sql_scripts(compare_snapshots(prod, vuoto), "PRE")["tables"])
    assert "SERIAL" not in ddl.upper()
    assert "id INTEGER NOT NULL" in ddl


def test_conserva_vincoli_e_vista(riletto):
    assert list(riletto.views) == ["clienti_attivi"]
    assert list(riletto.unique_constraints("clienti")) == ["(partita_iva)"]
    assert list(riletto.foreign_keys("ordini")) == ["(cliente_id) -> (clienti.id)"]
    assert list(riletto.indexes("clienti")) == ["(email)"]


# --- sicurezza del file ----------------------------------------------------


def test_lo_snapshot_non_contiene_la_password(live, tmp_path):
    snapshot, _ = live
    path = snapshot_io.save(
        snapshot, tmp_path / "s.json",
        source="postgresql+psycopg2://app:segretissima@host:5432/db",
    )
    contenuto = path.read_text(encoding="utf-8")
    assert "segretissima" not in contenuto
    assert "app:****@host" in contenuto


# --- formato ---------------------------------------------------------------


def test_rifiuta_un_formato_piu_recente(tmp_path):
    path = tmp_path / "futuro.json"
    path.write_text(json.dumps({"format": FORMAT_VERSION + 1, "env_name": "X"}), encoding="utf-8")
    with pytest.raises(SnapshotFormatError, match="Aggiorna DiFFDB"):
        snapshot_io.load(path)


def test_rifiuta_un_json_qualsiasi(tmp_path):
    path = tmp_path / "altro.json"
    path.write_text(json.dumps({"connessioni": []}), encoding="utf-8")
    with pytest.raises(SnapshotFormatError):
        snapshot_io.load(path)


def test_riconosce_i_file_snapshot(tmp_path, live):
    path = snapshot_io.save(live[0], tmp_path / "s.json")
    assert looks_like_snapshot(str(path))
    assert not looks_like_snapshot("sqlite:///qualcosa.json")   # e' un URL
    assert not looks_like_snapshot("COL")                       # e' un nome
    assert not looks_like_snapshot(str(tmp_path / "manca.json"))  # non esiste


# --- tipi ------------------------------------------------------------------


@pytest.mark.parametrize("testo", [
    "VARCHAR(50)", "NUMERIC(10, 2)", "INTEGER", "TEXT", "BIGINT", "BOOLEAN",
    # Tipi di altri dialetti: non sono tipi SQLAlchemy, ma il testo va conservato.
    "VARCHAR2(50)", "NUMBER(10, 2)", "TIMESTAMP(6)", "INTEGER(11)", "BFILE",
])
def test_il_tipo_si_ristampa_identico(testo):
    """Se il tipo cambiasse forma nel round-trip, comparirebbe come 'tipo diverso'."""
    assert str(type_from_text(testo)).upper() == testo.upper()


def test_i_tipi_sconosciuti_restano_grezzi():
    assert isinstance(type_from_text("VARCHAR2(50)"), RawType)
    assert not isinstance(type_from_text("VARCHAR(50)"), RawType)


def test_il_tipo_grezzo_si_compila_nel_ddl():
    from sqlalchemy.dialects import registry

    assert RawType("VARCHAR2(50)").compile(dialect=registry.load("oracle")()) == "VARCHAR2(50)"


# --- dialetto --------------------------------------------------------------


def _snapshot_file(tmp_path, dialect: str) -> Path:
    """Snapshot fittizio di 'clienti' senza la colonna email, nel dialetto dato."""
    payload = {
        "format": FORMAT_VERSION,
        "env_name": "PROD",
        "dialect": dialect,
        "schema": None,
        "tables": {
            "clienti": {
                "columns": [{"name": "id", "type": "INTEGER", "nullable": False,
                             "server_default": None}],
                "primary_key": ["id"],
                "indexes": [], "unique_constraints": [], "foreign_keys": [],
            }
        },
        "views": {}, "sequences": {}, "synonyms": {},
    }
    path = tmp_path / f"prod_{dialect}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("dialect, atteso", [
    ("postgresql", "ALTER TABLE clienti ADD COLUMN email VARCHAR(120);"),
    # Oracle: niente ADD COLUMN, e la lunghezza in caratteri e non in byte.
    ("oracle", "ALTER TABLE clienti ADD email VARCHAR(120 CHAR);"),
    ("mssql", "ALTER TABLE clienti ADD email VARCHAR(120);"),
])
def test_lo_snapshot_riletto_genera_ddl_nel_suo_dialetto(tmp_path, dialect, atteso):
    """Il dialetto si ricostruisce dal nome, senza che il driver sia installato:
    e' quello che rende possibile generare l'allineamento di Oracle da un portatile
    su cui Oracle non c'e'."""
    prod = snapshot_io.load(_snapshot_file(tmp_path, dialect))
    assert prod.dialect == dialect

    # L'ambiente vivo ha una colonna in piu': PROD va allineato.
    url = f"sqlite:///{tmp_path / 'svi.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE clienti (id INTEGER NOT NULL PRIMARY KEY, "
                          "email VARCHAR(120))"))
    engine.dispose()

    diff = compare_snapshots(prod, snapshot_connection("SVI", url))
    assert generate_sql_scripts(diff, "PROD")["tables"] == [atteso]


def test_dialetto_sconosciuto_non_fa_esplodere_la_lettura(tmp_path):
    payload = {"format": FORMAT_VERSION, "env_name": "X", "dialect": "inventato",
               "tables": {}, "views": {}, "sequences": {}, "synonyms": {}}
    path = tmp_path / "x.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert snapshot_io.load(path).dialect == "inventato"


# --- sorgenti --------------------------------------------------------------


def test_ambienti_omonimi_vengono_distinti(live, tmp_path):
    """Il caso della drift detection: 'PROD di gennaio' contro 'PROD' di oggi."""
    snapshot, url = live
    baseline = snapshot_io.save(snapshot, tmp_path / "prod_gennaio.json")

    diff = compare_sources(SnapshotFile.at(baseline), Connection(name="SVI", conn_string=url))

    # Il file prende il nome dal file, la connessione dal suo database: piu'
    # leggibile di un generico "live" quando si rilegge il report mesi dopo.
    assert diff.snapshot1.env_name == "SVI (prod_gennaio)"
    assert diff.snapshot2.env_name == "SVI (svi)"
    assert diff.all == []


def test_confronto_di_due_file_senza_database(live, tmp_path):
    """Confronto offline: nessuna connessione aperta, differenze comunque trovate."""
    snapshot, _ = live
    prima = snapshot_io.save(snapshot, tmp_path / "prima.json")

    dopo_payload = json.loads(prima.read_text(encoding="utf-8"))
    dopo_payload["env_name"] = "DOPO"
    del dopo_payload["tables"]["ordini"]
    dopo = tmp_path / "dopo.json"
    dopo.write_text(json.dumps(dopo_payload), encoding="utf-8")

    diff = compare_sources(SnapshotFile.at(prima), SnapshotFile.at(dopo))

    mancanti = [d for d in diff.tables if d.kind == "table"]
    assert [(d.name, d.missing_in) for d in mancanti] == [("ordini", "DOPO")]
