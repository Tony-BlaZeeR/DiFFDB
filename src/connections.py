"""Lettura/scrittura dell'elenco connessioni.

Formato: una riga per connessione, `nome,connection_string`. Si divide sul
primo separatore soltanto, perche' le connection string possono contenere
virgole (es. SQL Server `host,1433`).

Le password possono essere tenute fuori dal file usando variabili d'ambiente:
    prod,postgresql+psycopg2://app:${PROD_DB_PWD}@host:5432/db
"""

import logging
from dataclasses import dataclass
from typing import List

from src.paths import connections_file, legacy_connections_file

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    name: str
    conn_string: str


def load_connections() -> List[Connection]:
    path = connections_file()
    if not path.exists():
        legacy = legacy_connections_file()
        if legacy.exists():
            logger.info("Migrazione delle connessioni da %s a %s", legacy, path)
            connections = _parse(legacy.read_text(encoding="utf-8").splitlines())
            save_connections(connections)
            return connections
        return []

    return _parse(path.read_text(encoding="utf-8").splitlines())


def save_connections(connections: List[Connection]) -> None:
    lines = [f"{c.name},{c.conn_string}" for c in connections]
    connections_file().write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse(lines) -> List[Connection]:
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
            logger.warning("Riga %d ignorata, nome o connection string vuoti", number)
            continue
        connections.append(Connection(name=name, conn_string=conn_string))
    return connections
