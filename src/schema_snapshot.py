"""Fotografia della struttura di un database.

Riflette lo schema con SQLAlchemy e tiene in memoria gli oggetti Table
riflessi: servono a generare DDL reale (CREATE TABLE completo) invece di
segnaposto.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# I sinonimi esistono solo su Oracle e SQL Server: si leggono dai cataloghi.
SYNONYM_QUERIES = {
    "oracle": (
        "SELECT synonym_name, table_owner || '.' || table_name AS target "
        "FROM all_synonyms WHERE owner = NVL(:schema, USER)"
    ),
    "mssql": (
        "SELECT name AS synonym_name, base_object_name AS target FROM sys.synonyms"
    ),
}


@dataclass
class Snapshot:
    """Struttura di un ambiente in un dato momento."""

    env_name: str
    dialect: str
    schema: Optional[str] = None
    dialect_impl: object = None  # engine.dialect: serve a compilare DDL per questo ambiente
    metadata: MetaData = field(default_factory=MetaData)
    views: Dict[str, str] = field(default_factory=dict)      # nome -> definizione
    sequences: Set[str] = field(default_factory=set)
    synonyms: Dict[str, str] = field(default_factory=dict)   # nome -> oggetto puntato

    @property
    def tables(self) -> Dict[str, object]:
        """Tabelle riflesse, indicizzate per nome semplice (senza schema)."""
        return {t.name: t for t in self.metadata.tables.values()}

    def columns(self, table_name: str) -> Dict[str, object]:
        table = self.tables.get(table_name)
        return {} if table is None else {c.name: c for c in table.columns}


def take_snapshot(env_name: str, engine: Engine, schema: Optional[str] = None) -> Snapshot:
    """Riflette tabelle, viste, sequenze e sinonimi dell'ambiente."""
    snapshot = Snapshot(
        env_name=env_name,
        dialect=engine.dialect.name,
        schema=schema,
        dialect_impl=engine.dialect,
    )

    snapshot.metadata.reflect(bind=engine, schema=schema, views=False)

    inspector = inspect(engine)

    for view in inspector.get_view_names(schema=schema):
        try:
            snapshot.views[view] = inspector.get_view_definition(view, schema=schema) or ""
        except (NotImplementedError, SQLAlchemyError) as exc:
            logger.warning("Definizione della vista '%s' non leggibile: %s", view, exc)
            snapshot.views[view] = ""

    try:
        snapshot.sequences = set(inspector.get_sequence_names(schema=schema))
    except (NotImplementedError, SQLAlchemyError) as exc:
        logger.info("Sequenze non supportate su %s: %s", snapshot.dialect, exc)

    snapshot.synonyms = _fetch_synonyms(engine, schema)
    return snapshot


def _fetch_synonyms(engine: Engine, schema: Optional[str]) -> Dict[str, str]:
    """Sinonimi reali dal catalogo. Vuoto sui dialetti che non li hanno."""
    query = SYNONYM_QUERIES.get(engine.dialect.name)
    if query is None:
        return {}

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(query), {"schema": schema} if ":schema" in query else {})
            return {row[0]: row[1] for row in rows}
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei sinonimi fallita: %s", exc)
        return {}


def type_signature(column) -> str:
    """Firma del tipo, confrontabile tra ambienti (VARCHAR(50), INTEGER, ...)."""
    return str(column.type).upper()
