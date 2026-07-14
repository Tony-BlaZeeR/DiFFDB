"""Lettura/scrittura dell'elenco connessioni.

Formato: JSON, cosi' lo schema puo' essere salvato accanto alla connection string
e le virgole nelle URL (SQL Server usa `host,1433`) non sono piu' un problema.
I vecchi file di testo `nome,connection_string` vengono migrati al primo avvio.

Le password possono restare fuori dal file usando le variabili d'ambiente:
    postgresql+psycopg2://app:${PROD_DB_PWD}@host:5432/db
"""

import json
import logging
from dataclasses import asdict, dataclass
from typing import List, Optional

from src.paths import connections_file, legacy_text_files

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    name: str
    conn_string: str
    schema: Optional[str] = None  # su Oracle di solito coincide con l'utente


def load_connections() -> List[Connection]:
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


def save_connections(connections: List[Connection]) -> None:
    payload = [asdict(c) for c in connections]
    connections_file().write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def find(connections: List[Connection], name: str) -> Optional[Connection]:
    return next((c for c in connections if c.name == name), None)


def _parse_json(raw: str) -> List[Connection]:
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


def parse_text(lines) -> List[Connection]:
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
