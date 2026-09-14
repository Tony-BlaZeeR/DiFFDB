"""Snapshot su file: salvataggio, rilettura e confronto senza il database.

Uno Snapshot letto dal vivo vive solo in memoria e muore col processo. Salvarlo
su disco sblocca tre cose che servono davvero:

- **drift detection**: PROD di oggi confrontato con PROD del mese scorso;
- **baseline versionata**: lo schema atteso committato in git, la CI che verifica
  che l'ambiente non se ne sia allontanato;
- **confronto offline**: il DBA esporta lo snapshot di produzione, il confronto
  si fa senza avere accesso di rete a produzione.

Il formato e' JSON leggibile e diffabile a mano, con un numero di versione: un
file scritto da una versione futura viene rifiutato invece di essere frainteso.

Lo snapshot riletto e' un `Snapshot` a tutti gli effetti: si confronta e genera
DDL esattamente come quello letto dal vivo, perche' le tabelle vengono
ricostruite come oggetti SQLAlchemy e non come semplici dizionari.
"""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    text,
    types,
)
from sqlalchemy.dialects import registry

from diffdb import __version__
from diffdb.connections import Connection
from diffdb.diff_DB import DiffResult, compare_snapshots, default_signature
from diffdb.rules import NESSUNA, a_dizionario, da_dizionario
from diffdb.schema_snapshot import (
    RoutineSpec,
    SequenceSpec,
    Snapshot,
    TriggerSpec,
    snapshot_connection,
)
from diffdb.urls import mask_password

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
SNAPSHOT_SUFFIXES = (".json",)


class SnapshotFormatError(ValueError):
    """File non riconoscibile come snapshot DiFFDB."""


# --- sorgenti di un confronto ---------------------------------------------


@dataclass
class SnapshotFile:
    """Uno snapshot salvato, usabile come ambiente al posto di una connessione."""

    path: Path
    name: str

    @classmethod
    def at(cls, path) -> "SnapshotFile":
        path = Path(path)
        return cls(path=path, name=peek_env_name(path))


Source = Connection | SnapshotFile


def snapshot_of(source: Source, regole=NESSUNA, annullabile=None) -> Snapshot:
    """Snapshot di una sorgente: riletto da file o fotografato dal vivo.

    A uno snapshot su file le regole non si riapplicano: quello che c'e' dentro
    e' gia' stato filtrato quando e' stato preso, e rifiltrarlo con regole
    diverse renderebbe il confronto incomparabile con la sua impronta.
    """
    if isinstance(source, SnapshotFile):
        return load(source.path)
    return snapshot_connection(source.name, source.conn_string, source.schema,
                               regole, annullabile)


def source_name(source: Source) -> str:
    """Nome dell'ambiente rappresentato dalla sorgente."""
    return source.name


def compare_sources(source1: Source, source2: Source, regole=NESSUNA,
                    annullabile=None) -> DiffResult:
    """Confronta due sorgenti qualsiasi: live/live, live/file o file/file.

    Le due letture partono insieme: quando sono entrambe dal vivo il tempo si
    dimezza, e quando una e' un file non cambia niente.
    """
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="diffdb-sorgenti") as pool:
        futuri = [pool.submit(snapshot_of, sorgente, regole, annullabile)
                  for sorgente in (source1, source2)]
        snap1, snap2 = futuri[0].result(), futuri[1].result()

    _disambiguate(snap1, source1, snap2, source2)
    return compare_snapshots(snap1, snap2, regole)


def _disambiguate(snap1: Snapshot, source1: Source, snap2: Snapshot, source2: Source) -> None:
    """Rende diversi due ambienti omonimi.

    Il caso tipico e' la drift detection: 'PROD di gennaio' (file) contro 'PROD'
    (dal vivo) portano lo stesso env_name, e il confronto non saprebbe piu' a
    quale dei due appartiene una differenza.
    """
    if snap1.env_name != snap2.env_name:
        return

    base = snap1.env_name
    prima, seconda = _origin(source1), _origin(source2)
    if prima == seconda:
        # Due sorgenti dello stesso tipo e indistinguibili: numerarle e' brutto
        # ma e' meglio di due ambienti che si chiamano uguale.
        prima, seconda = f"{prima} 1", f"{seconda} 2"

    snap1.env_name = f"{base} ({prima})"
    snap2.env_name = f"{base} ({seconda})"
    logger.info("Ambienti omonimi: rinominati in '%s' e '%s'.", snap1.env_name, snap2.env_name)


def _origin(source: Source) -> str:
    """Come distinguere una sorgente dall'altra quando l'ambiente ha lo stesso nome."""
    if isinstance(source, SnapshotFile):
        return source.path.stem

    # Per una connessione dal vivo, il nome del database dice piu' di "live".
    try:
        from sqlalchemy.engine import make_url

        database = make_url(source.conn_string).database
    except Exception:  # URL non analizzabile: si ripiega su un'etichetta generica
        database = None
    return Path(database).stem if database else "live"


def looks_like_snapshot(token: str) -> bool:
    """Vero se il token indica un file snapshot invece di una connessione.

    Serve alla CLI per accettare `diffdb prod.json COL` senza flag aggiuntivi.
    """
    if "://" in token:
        return False
    path = Path(token)
    return path.suffix.lower() in SNAPSHOT_SUFFIXES and path.is_file()


# --- scrittura -------------------------------------------------------------


def save(snapshot: Snapshot, path, source: str | None = None) -> Path:
    """Scrive lo snapshot in JSON. `source` viene salvato senza password."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_dict(snapshot, source), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Snapshot di '%s' salvato in '%s'.", snapshot.env_name, path)
    return path


# Chiavi che descrivono la *struttura*: l'impronta si calcola solo su queste.
# Restano fuori il nome dell'ambiente, l'istante e l'origine: rinominare un
# ambiente o rifare lo snapshot un minuto dopo non e' un cambiamento di schema.
#
# I filtri ci sono dentro di proposito. Senza, uno snapshot preso escludendo le
# tabelle temporanee e uno preso senza filtri avrebbero la stessa impronta pur
# descrivendo insiemi diversi, e `--verify` direbbe "tutto a posto" su uno
# script generato con altre regole.
CHIAVI_STRUTTURA = ("dialect", "schema", "tables", "views", "sequences", "synonyms",
                    "triggers", "routines", "regole")


def fingerprint(snapshot: Snapshot) -> str:
    """Impronta della struttura di un ambiente.

    Serve a dire, guardando uno script generato ieri, se l'ambiente nel
    frattempo e' cambiato: se l'impronta non torna, lo script non e' piu' valido.
    """
    return impronta_di(to_dict(snapshot))


def impronta_di(payload: dict) -> str:
    dati = {chiave: payload.get(chiave) for chiave in CHIAVI_STRUTTURA}
    canonico = json.dumps(dati, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def to_dict(snapshot: Snapshot, source: str | None = None) -> dict:
    payload = {
        "format": FORMAT_VERSION,
        "diffdb_version": __version__,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "env_name": snapshot.env_name,
        "dialect": snapshot.dialect,
        "schema": snapshot.schema,
        # Mai la password: lo snapshot e' fatto per finire in git o in allegato a un ticket.
        "source": mask_password(source) if source else None,
        "tables": {name: _table_to_dict(table, snapshot.dialect_impl)
                   for name, table in sorted(snapshot.tables.items())},
        "views": dict(sorted(snapshot.views.items())),
        "sequences": {
            name: {
                "start": spec.start,
                "increment": spec.increment,
                "minvalue": spec.minvalue,
                "maxvalue": spec.maxvalue,
                "cycle": spec.cycle,
            }
            for name, spec in sorted(snapshot.sequences.items())
        },
        "synonyms": dict(sorted(snapshot.synonyms.items())),
        "triggers": {
            name: {"table": spec.table, "definition": spec.definition}
            for name, spec in sorted(snapshot.triggers.items())
        },
        "routines": {
            key: {"name": spec.name, "kind": spec.kind, "definition": spec.definition,
                 "drop_args": spec.drop_args}
            for key, spec in sorted(snapshot.routines.items())
        },
        "regole": _filtri(snapshot.regole),
    }
    payload["fingerprint"] = impronta_di(payload)
    return payload


def _filtri(regole) -> dict | None:
    """I soli filtri, senza le differenze accettate.

    Si salvano per esteso e non come impronta: uno snapshot deve poter dire da
    solo cosa e' stato escluso quando e' stato preso. Se non ci sono filtri si
    salva None, cosi' l'impronta resta identica a quella degli snapshot presi
    prima che le regole esistessero.
    """
    if regole.firma() is None:
        return None
    filtri = a_dizionario(regole)
    filtri.pop("accettate", None)
    return filtri


def _tipo_ddl(column, dialect_impl) -> str | None:
    """Come il dialetto scrive davvero questo tipo in un DDL.

    Serve solo quando differisce dalla forma generica: il confronto usa `type`,
    la generazione usa questo. Tenerli separati e' l'unico modo di avere insieme
    un confronto stabile e un DDL che il server accetta.
    """
    if dialect_impl is None:
        return None
    try:
        reso = column.type.compile(dialect=dialect_impl)
    except Exception:      # tipo che quel dialetto non sa rendere
        return None
    return reso if reso != str(column.type) else None


def _table_to_dict(table: Table, dialect_impl=None) -> dict:
    return {
        "columns": [
            {
                "name": column.name,
                "type": str(column.type),
                # Il tipo come lo scrive il *suo* dialetto, quando non coincide
                # con la forma generica. Su SQL Server str() rende
                # 'VARCHAR(120) COLLATE "..."', con le virgolette, che in un
                # ALTER TABLE il server rifiuta.
                "type_ddl": _tipo_ddl(column, dialect_impl),
                "nullable": bool(column.nullable),
                "server_default": _server_default(column),
                # Senza questo flag SQLAlchemy, ricostruendo la tabella, decide
                # da se' che un intero in chiave primaria e' auto-incrementante e
                # lo riemette come SERIAL: la tabella creata avrebbe una sequenza
                # e un default che l'originale non ha.
                "autoincrement": column.autoincrement,
            }
            for column in table.columns
        ],
        "primary_key": [c.name for c in table.primary_key.columns],
        "indexes": sorted(
            (
                {
                    "name": index.name,
                    "columns": [c.name for c in index.columns],
                    "unique": bool(index.unique),
                }
                for index in table.indexes
            ),
            key=lambda i: (i["columns"], i["name"] or ""),
        ),
        "unique_constraints": sorted(
            (
                {"name": c.name, "columns": [col.name for col in c.columns]}
                for c in table.constraints
                if isinstance(c, UniqueConstraint)
            ),
            key=lambda u: (u["columns"], u["name"] or ""),
        ),
        "foreign_keys": sorted(
            (
                {
                    "name": fk.name,
                    "columns": [c.name for c in fk.columns],
                    "refers_to": [e.target_fullname for e in fk.elements],
                }
                for fk in table.foreign_key_constraints
            ),
            key=lambda f: (f["columns"], f["refers_to"]),
        ),
        # Vuoto e non assente sulle tabelle SQLite: la riflessione dei CHECK
        # e' inaffidabile su quel dialetto (vedi Snapshot.check_constraints),
        # quindi table.constraints non ne contiene mai di corretti da salvare.
        "check_constraints": sorted(
            (
                {"name": c.name, "sqltext": str(c.sqltext)}
                for c in table.constraints
                if isinstance(c, CheckConstraint)
            ),
            key=lambda c: (c["sqltext"], c["name"] or ""),
        ),
    }


def _server_default(column) -> str | None:
    """Testo del default lato server, nella stessa forma usata dal confronto."""
    return default_signature(column) or None


# --- lettura ---------------------------------------------------------------


def load(path) -> Snapshot:
    """Rilegge uno snapshot. Solleva SnapshotFormatError se il file non e' valido."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotFormatError(f"{path}: non e' un JSON valido ({exc})") from exc
    return from_dict(payload, origin=str(path))


def peek_env_name(path) -> str:
    """Nome dell'ambiente contenuto nel file, senza ricostruire tutto lo schema."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotFormatError(f"{path}: snapshot illeggibile ({exc})") from exc
    return str(payload.get("env_name") or path.stem)


def from_dict(payload: dict, origin: str = "snapshot") -> Snapshot:
    if not isinstance(payload, dict) or "format" not in payload:
        raise SnapshotFormatError(f"{origin}: non e' uno snapshot DiFFDB")

    version = payload.get("format")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise SnapshotFormatError(
            f"{origin}: formato {version}, questa versione di DiFFDB arriva al {FORMAT_VERSION}. "
            f"Aggiorna DiFFDB per rileggerlo."
        )

    dialect = payload.get("dialect") or "sqlite"
    schema = payload.get("schema") or None

    snapshot = Snapshot(
        env_name=payload.get("env_name") or origin,
        dialect=dialect,
        schema=schema,
        dialect_impl=_dialect_impl(dialect),
        metadata=MetaData(),
    )

    for name, table in (payload.get("tables") or {}).items():
        _table_from_dict(snapshot.metadata, name, table, schema)

    snapshot.views = dict(payload.get("views") or {})
    snapshot.sequences = {
        name: SequenceSpec(
            name=name,
            start=int(spec.get("start", 1)),
            increment=int(spec.get("increment", 1)),
            minvalue=spec.get("minvalue"),
            maxvalue=spec.get("maxvalue"),
            cycle=bool(spec.get("cycle", False)),
        )
        for name, spec in (payload.get("sequences") or {}).items()
    }
    snapshot.synonyms = dict(payload.get("synonyms") or {})
    snapshot.triggers = {
        name: TriggerSpec(name=name, table=spec.get("table"), definition=spec.get("definition", ""))
        for name, spec in (payload.get("triggers") or {}).items()
    }
    snapshot.routines = {
        key: RoutineSpec(name=spec.get("name", ""), kind=spec.get("kind", "function"),
                         definition=spec.get("definition", ""), drop_args=spec.get("drop_args", ""))
        for key, spec in (payload.get("routines") or {}).items()
    }

    # Le regole tornano indietro per intero: `fingerprint()` le ricalcola, e
    # senza di loro l'impronta del file e quella dello snapshot riletto
    # divergerebbero.
    filtri = payload.get("regole")
    if filtri:
        snapshot.regole = da_dizionario(filtri, origine=origin)
    return snapshot


def _dialect_impl(name: str):
    """Istanza del dialetto, per compilare DDL nella sintassi giusta.

    Il dialetto si carica dal registro SQLAlchemy senza che il driver sia
    installato: serve solo a compilare, non a connettersi.
    """
    try:
        return registry.load(name)()
    except Exception as exc:  # dialetto sconosciuto o pacchetto assente
        logger.warning("Dialetto '%s' non caricabile (%s): uso quello generico.", name, exc)
        from sqlalchemy.engine.default import DefaultDialect

        return DefaultDialect()


def _table_from_dict(metadata: MetaData, name: str, payload: dict, schema) -> Table:
    columns = [
        Column(
            c["name"],
            type_from_text(c.get("type") or "", c.get("type_ddl")),
            nullable=bool(c.get("nullable", True)),
            # text(): il default e' SQL da riemettere tale e quale. Passandolo come
            # stringa, SQLAlchemy lo tratterebbe come letterale e scriverebbe DEFAULT '0'.
            server_default=text(c["server_default"]) if c.get("server_default") else None,
            # In assenza del flag si sceglie False: meglio una colonna normale
            # che una SERIAL inventata dal nulla.
            autoincrement=c.get("autoincrement", False),
        )
        for c in payload.get("columns") or []
    ]

    args = list(columns)
    primary_key = payload.get("primary_key") or []
    if primary_key:
        # Vincolo esplicito e non `primary_key=True` sulle colonne: cosi' si
        # conserva l'ordine delle colonne nella chiave composta.
        args.append(PrimaryKeyConstraint(*primary_key))
    for unique in payload.get("unique_constraints") or []:
        args.append(UniqueConstraint(*unique["columns"], name=unique.get("name")))
    for fk in payload.get("foreign_keys") or []:
        args.append(ForeignKeyConstraint(fk["columns"], fk["refers_to"], name=fk.get("name")))
    for check in payload.get("check_constraints") or []:
        args.append(CheckConstraint(check["sqltext"], name=check.get("name")))

    table = Table(name, metadata, *args, schema=schema)

    for index in payload.get("indexes") or []:
        missing = [c for c in index["columns"] if c not in table.c]
        if missing:  # indice su espressione: non ricostruibile come indice di colonne
            logger.warning(
                "Indice %s su %s ignorato: colonne non presenti (%s)",
                index.get("name"), name, ", ".join(missing),
            )
            continue
        Index(index.get("name"), *[table.c[c] for c in index["columns"]],
              unique=bool(index.get("unique")))

    return table


# --- tipi ------------------------------------------------------------------

# Tipi ricostruibili come tipo SQLAlchemy vero, con il significato dei loro
# argomenti. Gli altri diventano RawType: il testo si conserva comunque.
_SIZED_TYPES = ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "VARBINARY", "BINARY",
                "TEXT", "BLOB", "CLOB", "NTEXT")
_PRECISION_TYPES = ("NUMERIC", "DECIMAL", "FLOAT", "REAL", "DOUBLE", "DOUBLE_PRECISION")
_PLAIN_TYPES = ("INTEGER", "INT", "BIGINT", "SMALLINT", "BOOLEAN", "DATE", "DATETIME",
                "TIME", "TIMESTAMP", "JSON", "UUID")


class RawType(types.UserDefinedType):
    """Tipo che non corrisponde a un tipo SQLAlchemy noto (VARCHAR2, NUMBER, ...).

    Conserva due forme, che non sempre coincidono: quella generica, con cui il
    confronto decide se una colonna e' cambiata, e quella con cui il dialetto la
    scrive in un DDL. Su SQL Server la prima e'
    `VARCHAR(120) COLLATE "SQL_Latin1_General_CP1_CI_AS"` e il server la rifiuta;
    la seconda e' quella buona.
    """

    cache_ok = True

    def __init__(self, text: str, ddl: str | None = None):
        self.text = text
        self.ddl = ddl or text

    def get_col_spec(self, **kw) -> str:
        return self.ddl

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"RawType({self.text!r}, ddl={self.ddl!r})"


def type_from_text(text: str, ddl: str | None = None):
    """Ricostruisce il tipo dal testo salvato.

    Prova con un tipo SQLAlchemy vero (che sa ricompilarsi su un altro dialetto)
    e lo accetta solo se si ristampa identico all'originale: cosi' il round-trip
    non puo' cambiare la firma di una colonna e inventare differenze.

    `ddl` e' la forma che usa il dialetto di origine, quando differisce.
    """
    text = (text or "").strip()
    if not text:
        return RawType("")

    # Con una forma DDL propria serve il tipo grezzo: un tipo SQLAlchemy la
    # ricalcolerebbe a modo suo e si tornerebbe al punto di partenza.
    if ddl:
        return RawType(text, ddl)

    candidate = _structured_type(text)
    if candidate is not None and str(candidate).upper() == text.upper():
        return candidate
    return RawType(text)


def _structured_type(text: str):
    name, args = _split_type(text)
    if name is None:
        return None

    factory = getattr(types, name, None)
    if not isinstance(factory, type) or not issubclass(factory, types.TypeEngine):
        return None

    try:
        if name in _PLAIN_TYPES:
            return factory() if not args else None
        if name in _SIZED_TYPES:
            return factory(*(int(a) for a in args[:1]))
        if name in _PRECISION_TYPES:
            return factory(*(int(a) for a in args[:2]))
    except (TypeError, ValueError):
        return None
    return None


def _split_type(text: str):
    """'NUMERIC(10, 2)' -> ('NUMERIC', ['10', '2']); 'VARCHAR2(50)' -> ('VARCHAR2', ['50'])."""
    head, _, tail = text.partition("(")
    name = head.strip().upper().replace(" ", "_")
    if not name.isidentifier():
        return None, []
    if not tail:
        return name, []
    if not tail.rstrip().endswith(")"):
        return None, []
    inner = tail.rstrip()[:-1].strip()
    args = [a.strip() for a in inner.split(",")] if inner else []
    return name, args
