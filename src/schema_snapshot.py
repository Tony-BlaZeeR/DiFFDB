"""Fotografia della struttura di un database.

Riflette lo schema con SQLAlchemy e conserva gli oggetti Table riflessi: servono
a generare DDL reale (CREATE TABLE, CREATE INDEX, ADD CONSTRAINT) invece di
segnaposto. Sequenze e sinonimi si leggono dai cataloghi di sistema, perche'
SQLAlchemy non li espone in modo uniforme.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy import MetaData, UniqueConstraint, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# I sinonimi esistono solo su Oracle e SQL Server.
SYNONYM_QUERIES = {
    "oracle": (
        "SELECT synonym_name, table_owner || '.' || table_name AS target "
        "FROM all_synonyms WHERE owner = NVL(:schema, USER)"
    ),
    "mssql": "SELECT name, base_object_name FROM sys.synonyms",
}

# Valori reali delle sequenze: senza questi si ricreerebbero tutte con START WITH 1.
SEQUENCE_QUERIES = {
    "postgresql": (
        "SELECT sequencename, start_value, increment_by, min_value, max_value, cycle "
        "FROM pg_sequences WHERE schemaname = COALESCE(:schema, current_schema())"
    ),
    "oracle": (
        "SELECT sequence_name, last_number, increment_by, min_value, max_value, "
        "CASE WHEN cycle_flag = 'Y' THEN 1 ELSE 0 END "
        "FROM all_sequences WHERE sequence_owner = NVL(:schema, USER)"
    ),
    "mssql": (
        "SELECT name, CAST(start_value AS BIGINT), CAST(increment AS BIGINT), "
        "CAST(minimum_value AS BIGINT), CAST(maximum_value AS BIGINT), "
        "CAST(is_cycling AS INT) FROM sys.sequences"
    ),
}


@dataclass
class SequenceSpec:
    name: str
    start: int = 1
    increment: int = 1
    minvalue: Optional[int] = None
    maxvalue: Optional[int] = None
    cycle: bool = False

    def signature(self) -> str:
        return f"START {self.start} INCREMENT {self.increment} CYCLE {int(self.cycle)}"


@dataclass
class Snapshot:
    """Struttura di un ambiente in un dato momento."""

    env_name: str
    dialect: str
    schema: Optional[str] = None
    dialect_impl: object = None  # engine.dialect: serve a compilare il DDL
    metadata: MetaData = field(default_factory=MetaData)
    views: Dict[str, str] = field(default_factory=dict)        # nome -> definizione
    sequences: Dict[str, SequenceSpec] = field(default_factory=dict)
    synonyms: Dict[str, str] = field(default_factory=dict)     # nome -> oggetto puntato

    @property
    def tables(self) -> Dict[str, object]:
        return {t.name: t for t in self.metadata.tables.values()}

    def table(self, name: str):
        return self.tables.get(name)

    def columns(self, table_name: str) -> Dict[str, object]:
        table = self.table(table_name)
        return {} if table is None else {c.name: c for c in table.columns}

    def indexes(self, table_name: str) -> Dict[str, object]:
        """Indici per firma (colonne + unicita'), non per nome: i nomi cambiano."""
        table = self.table(table_name)
        return {} if table is None else {index_signature(i): i for i in table.indexes}

    def foreign_keys(self, table_name: str) -> Dict[str, object]:
        table = self.table(table_name)
        if table is None:
            return {}
        return {fk_signature(fk): fk for fk in table.foreign_key_constraints}

    def unique_constraints(self, table_name: str) -> Dict[str, object]:
        table = self.table(table_name)
        if table is None:
            return {}
        return {
            unique_signature(c): c
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }

    def primary_key(self, table_name: str):
        table = self.table(table_name)
        if table is None:
            return ()
        return tuple(c.name for c in table.primary_key.columns)


def take_snapshot(env_name: str, engine: Engine, schema: Optional[str] = None) -> Snapshot:
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

    snapshot.sequences = _fetch_sequences(engine, schema, inspector)
    snapshot.synonyms = _fetch_synonyms(engine, schema)
    return snapshot


def _fetch_sequences(engine, schema, inspector) -> Dict[str, SequenceSpec]:
    """Sequenze con i valori reali; se il catalogo non risponde, almeno i nomi."""
    query = SEQUENCE_QUERIES.get(engine.dialect.name)
    if query:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query), {"schema": schema})
                return {
                    row[0]: SequenceSpec(
                        name=row[0],
                        start=int(row[1] or 1),
                        increment=int(row[2] or 1),
                        minvalue=None if row[3] is None else int(row[3]),
                        maxvalue=None if row[4] is None else int(row[4]),
                        cycle=bool(row[5]),
                    )
                    for row in rows
                }
        except SQLAlchemyError as exc:
            logger.warning("Lettura dei valori delle sequenze fallita: %s", exc)

    try:
        return {n: SequenceSpec(name=n) for n in inspector.get_sequence_names(schema=schema)}
    except (NotImplementedError, SQLAlchemyError) as exc:
        logger.info("Sequenze non supportate su %s: %s", engine.dialect.name, exc)
        return {}


def _fetch_synonyms(engine: Engine, schema: Optional[str]) -> Dict[str, str]:
    query = SYNONYM_QUERIES.get(engine.dialect.name)
    if query is None:
        return {}

    try:
        with engine.connect() as conn:
            params = {"schema": schema} if ":schema" in query else {}
            return {row[0]: row[1] for row in conn.execute(text(query), params)}
    except SQLAlchemyError as exc:
        logger.warning("Lettura dei sinonimi fallita: %s", exc)
        return {}


def type_signature(column) -> str:
    """Firma del tipo, confrontabile fra ambienti (VARCHAR(50), INTEGER, ...)."""
    return str(column.type).upper()


def index_signature(index) -> str:
    columns = ",".join(c.name for c in index.columns)
    return f"{'UNIQUE ' if index.unique else ''}({columns})"


def fk_signature(fk) -> str:
    """Identifica una FK dalle colonne, non dal nome: i nomi autogenerati cambiano."""
    columns = ",".join(c.name for c in fk.columns)
    targets = ",".join(e.target_fullname for e in fk.elements)
    return f"({columns}) -> ({targets})"


def unique_signature(constraint) -> str:
    return "(" + ",".join(c.name for c in constraint.columns) + ")"
