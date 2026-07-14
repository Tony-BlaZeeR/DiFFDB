"""Confronto strutturale fra due ambienti e generazione degli script di allineamento.

Il confronto guarda nomi *e* tipi delle colonne; gli script prodotti sono SQL
eseguibile, compilato sul dialetto dell'ambiente da allineare.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import MetaData, create_engine
from sqlalchemy.schema import CreateTable

from config.dialectConfig import templates_for
from src.schema_snapshot import Snapshot, take_snapshot, type_signature

logger = logging.getLogger(__name__)

MISSING = "mancante"
TYPE_MISMATCH = "tipo diverso"
NULLABILITY_MISMATCH = "nullability diversa"


@dataclass
class Difference:
    kind: str                       # table | column | view | sequence | synonym
    name: str
    change: str                     # MISSING | TYPE_MISMATCH | NULLABILITY_MISMATCH
    column: Optional[str] = None
    missing_in: Optional[str] = None
    present_in: Optional[str] = None
    detail: str = ""

    def as_row(self) -> dict:
        return {
            "Oggetto": self.name,
            "Campo": self.column or "",
            "Differenza": self.change,
            "Presente in": self.present_in or "",
            "Mancante in": self.missing_in or "",
            "Dettaglio": self.detail,
        }


@dataclass
class DiffResult:
    snapshot1: Snapshot
    snapshot2: Snapshot
    tables: List[Difference] = field(default_factory=list)
    views: List[Difference] = field(default_factory=list)
    sequences: List[Difference] = field(default_factory=list)
    synonyms: List[Difference] = field(default_factory=list)

    @property
    def all(self) -> List[Difference]:
        return self.tables + self.views + self.sequences + self.synonyms

    @property
    def is_empty(self) -> bool:
        return not self.all

    def snapshot_of(self, env_name: str) -> Snapshot:
        if env_name == self.snapshot1.env_name:
            return self.snapshot1
        if env_name == self.snapshot2.env_name:
            return self.snapshot2
        raise KeyError(f"Ambiente sconosciuto: {env_name}")

    def other_than(self, env_name: str) -> Snapshot:
        return self.snapshot2 if env_name == self.snapshot1.env_name else self.snapshot1


def compare_environments(env1_name, conn_str1, env2_name, conn_str2, schema1=None, schema2=None) -> DiffResult:
    """Confronta due ambienti. Le connection string possono contenere ${VAR} d'ambiente."""
    engine1 = create_engine(_expand(conn_str1))
    engine2 = create_engine(_expand(conn_str2))
    try:
        snap1 = take_snapshot(env1_name, engine1, schema1)
        snap2 = take_snapshot(env2_name, engine2, schema2)
        return compare_snapshots(snap1, snap2)
    finally:
        engine1.dispose()
        engine2.dispose()


def compare_snapshots(snap1: Snapshot, snap2: Snapshot) -> DiffResult:
    result = DiffResult(snapshot1=snap1, snapshot2=snap2)
    e1, e2 = snap1.env_name, snap2.env_name

    tables1, tables2 = set(snap1.tables), set(snap2.tables)

    for table in sorted(tables2 - tables1):
        result.tables.append(Difference("table", table, MISSING, missing_in=e1, present_in=e2))
    for table in sorted(tables1 - tables2):
        result.tables.append(Difference("table", table, MISSING, missing_in=e2, present_in=e1))

    for table in sorted(tables1 & tables2):
        result.tables.extend(_compare_columns(table, snap1, snap2))

    result.views = _compare_named(
        "view", set(snap1.views), set(snap2.views), e1, e2
    )
    result.sequences = _compare_named("sequence", snap1.sequences, snap2.sequences, e1, e2)
    result.synonyms = _compare_named("synonym", set(snap1.synonyms), set(snap2.synonyms), e1, e2)

    for name in sorted(set(snap1.synonyms) & set(snap2.synonyms)):
        if snap1.synonyms[name] != snap2.synonyms[name]:
            result.synonyms.append(
                Difference(
                    "synonym", name, TYPE_MISMATCH,
                    detail=f"{e1}: {snap1.synonyms[name]} | {e2}: {snap2.synonyms[name]}",
                )
            )

    return result


def _compare_columns(table: str, snap1: Snapshot, snap2: Snapshot) -> List[Difference]:
    diffs = []
    e1, e2 = snap1.env_name, snap2.env_name
    cols1, cols2 = snap1.columns(table), snap2.columns(table)

    for col in sorted(set(cols2) - set(cols1)):
        diffs.append(Difference(
            "column", table, MISSING, column=col, missing_in=e1, present_in=e2,
            detail=type_signature(cols2[col]),
        ))
    for col in sorted(set(cols1) - set(cols2)):
        diffs.append(Difference(
            "column", table, MISSING, column=col, missing_in=e2, present_in=e1,
            detail=type_signature(cols1[col]),
        ))

    for col in sorted(set(cols1) & set(cols2)):
        type1, type2 = type_signature(cols1[col]), type_signature(cols2[col])
        if type1 != type2:
            diffs.append(Difference(
                "column", table, TYPE_MISMATCH, column=col,
                detail=f"{e1}: {type1} | {e2}: {type2}",
            ))
        if cols1[col].nullable != cols2[col].nullable:
            diffs.append(Difference(
                "column", table, NULLABILITY_MISMATCH, column=col,
                detail=f"{e1}: {'NULL' if cols1[col].nullable else 'NOT NULL'} | "
                       f"{e2}: {'NULL' if cols2[col].nullable else 'NOT NULL'}",
            ))

    return diffs


def _compare_named(kind, names1, names2, env1, env2) -> List[Difference]:
    diffs = []
    for name in sorted(set(names2) - set(names1)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env1, present_in=env2))
    for name in sorted(set(names1) - set(names2)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env2, present_in=env1))
    return diffs


def generate_sql_scripts(diff: DiffResult, target_env: str) -> Dict[str, List[str]]:
    """Script da eseguire su `target_env` per allinearlo all'altro ambiente.

    Il dialetto e' quello del target: niente da indovinare, niente segnaposto.
    """
    target = diff.snapshot_of(target_env)
    source = diff.other_than(target_env)
    templates = templates_for(target.dialect)
    quote = target.dialect_impl.identifier_preparer.quote

    scripts = {"tables": [], "views": [], "sequences": [], "synonyms": []}

    for d in diff.tables:
        if d.kind == "table" and d.missing_in == target_env:
            scripts["tables"].append(_create_table_ddl(source.tables[d.name], target))
        elif d.kind == "column" and d.change == MISSING and d.missing_in == target_env:
            column = source.columns(d.name)[d.column]
            scripts["tables"].append(templates["add"].format(
                table=quote(d.name), column=quote(d.column), type=_column_type(column, target),
            ))
        elif d.kind == "column" and d.change == TYPE_MISMATCH:
            # Si allinea il target al tipo dell'altro ambiente.
            column = source.columns(d.name)[d.column]
            scripts["tables"].append(templates["modify"].format(
                table=quote(d.name), column=quote(d.column), type=_column_type(column, target),
            ))

    for d in diff.views:
        if d.missing_in == target_env:
            definition = source.views.get(d.name) or ""
            if definition.strip():
                scripts["views"].append(_create_view_ddl(d.name, definition, quote))
            else:
                scripts["views"].append(
                    f"-- Definizione della vista {d.name} non leggibile da {source.env_name}: va copiata a mano"
                )

    for d in diff.sequences:
        if d.missing_in == target_env:
            template = templates["create_sequence"]
            if template is None:
                scripts["sequences"].append(
                    f"-- {target.dialect} non supporta le sequenze: {d.name} non e' replicabile"
                )
            else:
                scripts["sequences"].append(template.format(name=quote(d.name)))

    for d in diff.synonyms:
        if d.missing_in == target_env:
            template = templates["create_synonym"]
            if template is None:
                scripts["synonyms"].append(
                    f"-- {target.dialect} non supporta i sinonimi: {d.name} non e' replicabile"
                )
            else:
                scripts["synonyms"].append(template.format(
                    name=quote(d.name), target=source.synonyms.get(d.name, "..."),
                ))

    return scripts


VIEW_HEADER = re.compile(r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(TEMP\w*\s+)?VIEW\b", re.IGNORECASE)


def _create_view_ddl(name, definition: str, quote) -> str:
    """Alcuni dialetti (SQLite, MySQL) restituiscono gia' il CREATE VIEW completo,
    altri (PostgreSQL, Oracle) solo il corpo della SELECT."""
    body = definition.strip().rstrip(";")
    if VIEW_HEADER.match(body):
        return f"{body};"
    return f"CREATE VIEW {quote(name)} AS\n{body};"


def _create_table_ddl(table, target: Snapshot) -> str:
    """CREATE TABLE completo, con colonne e tipi, compilato sul dialetto del target."""
    portable = table.to_metadata(MetaData(), schema=target.schema)
    ddl = str(CreateTable(portable).compile(dialect=target.dialect_impl)).strip()
    return f"{ddl};"


def _column_type(column, target: Snapshot) -> str:
    """Tipo della colonna reso nel dialetto del target."""
    try:
        rendered = column.type.compile(dialect=target.dialect_impl)
    except Exception as exc:  # tipo specifico di un altro dialetto
        logger.warning("Tipo %s non compilabile su %s: %s", column.type, target.dialect, exc)
        rendered = str(column.type)

    if column.server_default is not None and column.server_default.arg is not None:
        rendered += f" DEFAULT {column.server_default.arg}"
    if not column.nullable and column.server_default is not None:
        rendered += " NOT NULL"  # NOT NULL senza default farebbe fallire l'ALTER su tabelle popolate
    return rendered


def write_sql_script(scripts: Dict[str, List[str]], filename: str, target_env: str) -> None:
    titles = {"tables": "Tabelle", "views": "Viste", "sequences": "Sequenze", "synonyms": "Sinonimi"}
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"-- Script di allineamento per l'ambiente: {target_env}\n")
        f.write("-- Generato da DiFFDB. Rileggere prima di eseguire in produzione.\n\n")
        for section, statements in scripts.items():
            if not statements:
                continue
            f.write(f"-- === {titles[section]} ===\n")
            f.write("\n".join(statements))
            f.write("\n\n")
    logger.info("Script SQL salvato in '%s'.", filename)


def generate_excel_report(diff: DiffResult, filename: str) -> None:
    import pandas as pd

    sections = {
        "Tabelle": diff.tables,
        "Viste": diff.views,
        "Sequenze": diff.sequences,
        "Sinonimi": diff.synonyms,
    }
    columns = ["Oggetto", "Campo", "Differenza", "Presente in", "Mancante in", "Dettaglio"]

    with pd.ExcelWriter(filename) as writer:
        for sheet, diffs in sections.items():
            rows = [d.as_row() for d in diffs]
            pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name=sheet, index=False)

    logger.info("Report Excel salvato in '%s'.", filename)


def _expand(conn_str: str) -> str:
    """Espande le variabili d'ambiente: permette di tenere le password fuori dal file."""
    import os

    return os.path.expandvars(conn_str.strip())
