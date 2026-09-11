"""Lettura/scrittura dell'elenco connessioni.

Formato: JSON, cosi' lo schema puo' essere salvato accanto alla connection string
e le virgole nelle URL (SQL Server usa `host,1433`) non sono piu' un problema.
I vecchi file di testo `nome,connection_string` vengono migrati al primo avvio.

Nel file non ci va mai una password, ma un riferimento a dove sta davvero:

    postgresql+psycopg2://app:${keyring}@host:5432/db      portachiavi di sistema
    postgresql+psycopg2://app:${PROD_DB_PWD}@host:5432/db  variabile d'ambiente

La risoluzione e la policy stanno in src/urls.py.
"""

import json
import logging
from dataclasses import asdict, dataclass

from diffdb.paths import connections_file, legacy_text_files
from diffdb.urls import KEYRING_TOKEN

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    name: str
    conn_string: str
    schema: str | None = None  # su Oracle di solito coincide con l'utente


def load_connections() -> list[Connection]:
    path = connections_file()
    if path.exists():
        return _parse_json(path.read_text(encoding="utf-8"))

    for legacy in legacy_text_files():
        if legacy.exists():
            logger.info("Migrazione delle connessioni da %s a %s", legacy, path)
            connections = parse_text(legacy.read_text(encoding="utf-8").splitlines())
            if connections:
                save_connections(connections)
            return connections

    return []


def save_connections(connections: list[Connection]) -> None:
    payload = [asdict(c) for c in connections]
    connections_file().write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def find(connections: list[Connection], name: str) -> Connection | None:
    return next((c for c in connections if c.name == name), None)


def usa_portachiavi(connection: Connection) -> bool:
    """Vero se la password di questa connessione sta nel portachiavi."""
    return KEYRING_TOKEN in (connection.conn_string or "")


def con_riferimento_al_portachiavi(conn_string: str) -> str:
    """Sostituisce la password scritta nell'URL con il segnaposto ${keyring}.

    Serve quando l'utente imposta la password nel portachiavi: quello che resta
    sul disco e' un riferimento, non un segreto.
    """
    if not conn_string or "://" not in conn_string or "@" not in conn_string:
        return conn_string
    scheme, rest = conn_string.split("://", 1)
    credentials, host = rest.split("@", 1)
    utente = credentials.split(":", 1)[0]
    return f"{scheme}://{utente}:{KEYRING_TOKEN}@{host}"


def _parse_json(raw: str) -> list[Connection]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        logger.error("File connessioni illeggibile (%s): si riparte da un elenco vuoto", exc)
        return []

    connections = []
    for entry in payload:
        name = (entry.get("name") or "").strip()
        conn_string = (entry.get("conn_string") or "").strip()
        if not name or not conn_string:
            logger.warning("Connessione senza nome o senza URL, ignorata: %r", entry)
            continue
        schema = (entry.get("schema") or "").strip() or None
        connections.append(Connection(name=name, conn_string=conn_string, schema=schema))
    return connections


def parse_text(lines) -> list[Connection]:
    """Vecchio formato `nome,connection_string`: letto solo per migrare."""
    connections = []
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            logger.warning("Riga %d ignorata, manca la virgola: %r", number, line)
            continue
        name, conn_string = line.split(",", 1)  # la conn string puo' contenere virgole
        name, conn_string = name.strip(), conn_string.strip()
        if not name or not conn_string:
            logger.warning("Riga %d ignorata: nome o URL vuoti", number)
            continue
        connections.append(Connection(name=name, conn_string=conn_string))
    return connections
