"""Confronto strutturale fra due ambienti e generazione degli script di allineamento.

Il confronto guarda colonne (nome, tipo, nullability), indici, foreign key,
constraint di unicita', chiavi primarie, viste, sequenze e sinonimi.
Gli script prodotti sono SQL eseguibile, compilato sul dialetto dell'ambiente
da allineare.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import MetaData, UniqueConstraint, create_engine
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

from config.dialectConfig import templates_for
from src.schema_snapshot import (
    Snapshot,
    fk_signature,
    index_signature,
    take_snapshot,
    type_signature,
    unique_signature,
)

logger = logging.getLogger(__name__)

MISSING = "mancante"
TYPE_MISMATCH = "tipo diverso"
NULLABILITY_MISMATCH = "nullability diversa"
DEFINITION_MISMATCH = "definizione diversa"


@dataclass
class Difference:
    kind: str          # table | column | index | foreign_key | unique | primary_key
                       # | view | sequence | synonym
    name: str
    change: str
    column: Optional[str] = None
    missing_in: Optional[str] = None
    present_in: Optional[str] = None
    detail: str = ""

    def as_row(self) -> dict:
        return {
            "Oggetto": self.name,
            "Tipo": self.kind,
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
    constraints: List[Difference] = field(default_factory=list)
    views: List[Difference] = field(default_factory=list)
    sequences: List[Difference] = field(default_factory=list)
    synonyms: List[Difference] = field(default_factory=list)

    @property
    def all(self) -> List[Difference]:
        return self.tables + self.constraints + self.views + self.sequences + self.synonyms

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


# --- confronto ------------------------------------------------------------


def compare_environments(env1_name, conn_str1, env2_name, conn_str2, schema1=None, schema2=None) -> DiffResult:
    """Confronta due ambienti. Le connection string possono contenere ${VAR} d'ambiente."""
    engine1 = create_engine(expand(conn_str1))
    engine2 = create_engine(expand(conn_str2))
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
        result.constraints.extend(_compare_constraints(table, snap1, snap2))

    result.views = _compare_names("view", set(snap1.views), set(snap2.views), e1, e2)
    result.sequences = _compare_sequences(snap1, snap2)
    result.synonyms = _compare_synonyms(snap1, snap2)
    return result


def _compare_columns(table: str, snap1: Snapshot, snap2: Snapshot) -> List[Difference]:
    diffs = []
    e1, e2 = snap1.env_name, snap2.env_name
    cols1, cols2 = snap1.columns(table), snap2.columns(table)

    for col in sorted(set(cols2) - set(cols1)):
        diffs.append(Difference("column", table, MISSING, column=col, missing_in=e1,
                                present_in=e2, detail=type_signature(cols2[col])))
    for col in sorted(set(cols1) - set(cols2)):
        diffs.append(Difference("column", table, MISSING, column=col, missing_in=e2,
                                present_in=e1, detail=type_signature(cols1[col])))

    for col in sorted(set(cols1) & set(cols2)):
        type1, type2 = type_signature(cols1[col]), type_signature(cols2[col])
        if type1 != type2:
            diffs.append(Difference("column", table, TYPE_MISMATCH, column=col,
                                    detail=f"{e1}: {type1} | {e2}: {type2}"))
        if cols1[col].nullable != cols2[col].nullable:
            diffs.append(Difference(
                "column", table, NULLABILITY_MISMATCH, column=col,
                detail=f"{e1}: {_null(cols1[col])} | {e2}: {_null(cols2[col])}",
            ))

    return diffs


def _compare_constraints(table: str, snap1: Snapshot, snap2: Snapshot) -> List[Difference]:
    """Indici, foreign key, unique e chiave primaria."""
    diffs = []
    e1, e2 = snap1.env_name, snap2.env_name

    for kind, getter in (
        ("index", Snapshot.indexes),
        ("foreign_key", Snapshot.foreign_keys),
        ("unique", Snapshot.unique_constraints),
    ):
        items1, items2 = getter(snap1, table), getter(snap2, table)
        for signature in sorted(set(items2) - set(items1)):
            diffs.append(Difference(kind, table, MISSING, missing_in=e1, present_in=e2,
                                    detail=signature))
        for signature in sorted(set(items1) - set(items2)):
            diffs.append(Difference(kind, table, MISSING, missing_in=e2, present_in=e1,
                                    detail=signature))

    pk1, pk2 = snap1.primary_key(table), snap2.primary_key(table)
    if pk1 != pk2:
        diffs.append(Difference(
            "primary_key", table, DEFINITION_MISMATCH,
            detail=f"{e1}: ({','.join(pk1) or '-'}) | {e2}: ({','.join(pk2) or '-'})",
        ))

    return diffs


def _compare_sequences(snap1: Snapshot, snap2: Snapshot) -> List[Difference]:
    e1, e2 = snap1.env_name, snap2.env_name
    diffs = _compare_names("sequence", set(snap1.sequences), set(snap2.sequences), e1, e2)

    for name in sorted(set(snap1.sequences) & set(snap2.sequences)):
        spec1, spec2 = snap1.sequences[name], snap2.sequences[name]
        if spec1.signature() != spec2.signature():
            diffs.append(Difference("sequence", name, DEFINITION_MISMATCH,
                                    detail=f"{e1}: {spec1.signature()} | {e2}: {spec2.signature()}"))
    return diffs


def _compare_synonyms(snap1: Snapshot, snap2: Snapshot) -> List[Difference]:
    e1, e2 = snap1.env_name, snap2.env_name
    diffs = _compare_names("synonym", set(snap1.synonyms), set(snap2.synonyms), e1, e2)

    for name in sorted(set(snap1.synonyms) & set(snap2.synonyms)):
        if snap1.synonyms[name] != snap2.synonyms[name]:
            diffs.append(Difference("synonym", name, DEFINITION_MISMATCH,
                                    detail=f"{e1}: {snap1.synonyms[name]} | {e2}: {snap2.synonyms[name]}"))
    return diffs


def _compare_names(kind, names1, names2, env1, env2) -> List[Difference]:
    diffs = []
    for name in sorted(set(names2) - set(names1)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env1, present_in=env2))
    for name in sorted(set(names1) - set(names2)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env2, present_in=env1))
    return diffs


def _null(column) -> str:
    return "NULL" if column.nullable else "NOT NULL"


# --- generazione SQL ------------------------------------------------------


def generate_sql_scripts(diff: DiffResult, target_env: str) -> Dict[str, List[str]]:
    """Script da eseguire su `target_env` per allinearlo all'altro ambiente."""
    target = diff.snapshot_of(target_env)
    source = diff.other_than(target_env)
    templates = templates_for(target.dialect)
    quote = target.dialect_impl.identifier_preparer.quote
    portable = _portable_metadata(source, target)

    scripts = {"tables": [], "constraints": [], "views": [], "sequences": [], "synonyms": []}

    for d in diff.tables:
        if d.kind == "table" and d.missing_in == target_env:
            table = _portable_table(portable, d.name, target.schema)
            scripts["tables"].append(_compile(CreateTable(table), target))
            # CREATE TABLE non porta con se' gli indici: vanno emessi a parte.
            scripts["constraints"].extend(
                _compile(CreateIndex(index), target) for index in table.indexes)
        elif d.kind == "column" and d.change == MISSING and d.missing_in == target_env:
            column = source.columns(d.name)[d.column]
            scripts["tables"].append(templates["add"].format(
                table=quote(d.name), column=quote(d.column), type=_column_type(column, target)))
        elif d.kind == "column" and d.change == TYPE_MISMATCH:
            column = source.columns(d.name)[d.column]
            scripts["tables"].append(templates["modify"].format(
                table=quote(d.name), column=quote(d.column), type=_column_type(column, target)))
        elif d.kind == "column" and d.change == NULLABILITY_MISMATCH:
            scripts["tables"].append(
                f"-- {d.name}.{d.column}: nullability diversa ({d.detail}). "
                f"Va valutata a mano: su tabelle popolate un NOT NULL puo' fallire."
            )

    for d in diff.constraints:
        if d.missing_in != target_env:
            if d.kind == "primary_key" and d.change == DEFINITION_MISMATCH:
                scripts["constraints"].append(
                    f"-- Chiave primaria diversa su {d.name} ({d.detail}). "
                    f"Cambiarla e' un'operazione distruttiva: va valutata a mano."
                )
            continue

        if d.kind in ("foreign_key", "unique") and not templates["alter_add_constraint"]:
            scripts["constraints"].append(
                f"-- {target.dialect} non sa aggiungere vincoli a una tabella esistente: "
                f"il vincolo {d.kind} {d.detail} su {d.name} va creato ricreando la tabella"
            )
            continue

        ddl = _constraint_ddl(d, portable, target)
        if ddl:
            scripts["constraints"].append(ddl)

    for d in diff.views:
        if d.missing_in == target_env:
            definition = source.views.get(d.name) or ""
            if definition.strip():
                scripts["views"].append(_create_view_ddl(d.name, definition, quote))
            else:
                scripts["views"].append(
                    f"-- Definizione della vista {d.name} non leggibile da "
                    f"{source.env_name}: va copiata a mano"
                )

    for d in diff.sequences:
        if not templates["sequences"]:
            scripts["sequences"].append(
                f"-- {target.dialect} non supporta le sequenze: {d.name} non e' replicabile")
            continue
        if d.missing_in == target_env:
            scripts["sequences"].append(_create_sequence_ddl(source.sequences[d.name], quote))
        elif d.change == DEFINITION_MISMATCH:
            template = templates["alter_sequence"]
            spec = source.sequences[d.name]
            scripts["sequences"].append(
                template.format(name=quote(d.name), start=spec.start, increment=spec.increment)
                if template else f"-- Sequenza {d.name} disallineata ({d.detail})"
            )

    for d in diff.synonyms:
        if d.missing_in != target_env:
            continue
        template = templates["create_synonym"]
        if template is None:
            scripts["synonyms"].append(
                f"-- {target.dialect} non supporta i sinonimi: {d.name} non e' replicabile")
        else:
            scripts["synonyms"].append(template.format(
                name=quote(d.name), target=source.synonyms.get(d.name, "?")))

    return scripts


def _constraint_ddl(d: Difference, portable: MetaData, target: Snapshot) -> Optional[str]:
    """CREATE INDEX / ALTER TABLE ADD CONSTRAINT, compilati sul dialetto del target."""
    table = _portable_table(portable, d.name, target.schema)
    if table is None:
        return None

    if d.kind == "index":
        for index in table.indexes:
            if index_signature(index) == d.detail:
                return _compile(CreateIndex(index), target)

    elif d.kind == "foreign_key":
        for fk in table.foreign_key_constraints:
            if fk_signature(fk) == d.detail:
                return _compile(AddConstraint(fk), target)

    elif d.kind == "unique":
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and unique_signature(constraint) == d.detail:
                return _compile(AddConstraint(constraint), target)

    return None


def _portable_metadata(source: Snapshot, target: Snapshot) -> MetaData:
    """Copia di *tutte* le tabelle sullo schema del target.

    Vanno copiate tutte insieme: una foreign key non si compila se la tabella
    referenziata non e' nella stessa MetaData.
    """
    metadata = MetaData()
    for table in source.metadata.tables.values():
        table.to_metadata(metadata, schema=target.schema)
    return metadata


def _portable_table(portable: MetaData, name: str, schema: Optional[str]):
    return portable.tables.get(f"{schema}.{name}" if schema else name)


def _compile(ddl_element, target: Snapshot) -> str:
    return str(ddl_element.compile(dialect=target.dialect_impl)).strip().rstrip(";") + ";"


VIEW_HEADER = re.compile(r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(TEMP\w*\s+)?VIEW\b", re.IGNORECASE)


def _create_view_ddl(name, definition: str, quote) -> str:
    """Alcuni dialetti (SQLite, MySQL) restituiscono gia' il CREATE VIEW completo,
    altri (PostgreSQL, Oracle) solo il corpo della SELECT."""
    body = definition.strip().rstrip(";")
    if VIEW_HEADER.match(body):
        return f"{body};"
    return f"CREATE VIEW {quote(name)} AS\n{body};"


def _create_sequence_ddl(spec, quote) -> str:
    parts = [f"CREATE SEQUENCE {quote(spec.name)}",
             f"START WITH {spec.start}",
             f"INCREMENT BY {spec.increment}"]
    if spec.minvalue is not None:
        parts.append(f"MINVALUE {spec.minvalue}")
    if spec.maxvalue is not None:
        parts.append(f"MAXVALUE {spec.maxvalue}")
    if spec.cycle:
        parts.append("CYCLE")
    return " ".join(parts) + ";"


def _column_type(column, target: Snapshot) -> str:
    """Tipo della colonna reso nel dialetto del target."""
    try:
        rendered = column.type.compile(dialect=target.dialect_impl)
    except Exception as exc:  # tipo specifico di un altro dialetto
        logger.warning("Tipo %s non compilabile su %s: %s", column.type, target.dialect, exc)
        rendered = str(column.type)

    if column.server_default is not None and getattr(column.server_default, "arg", None) is not None:
        rendered += f" DEFAULT {column.server_default.arg}"
    if not column.nullable and column.server_default is not None:
        rendered += " NOT NULL"  # NOT NULL senza default fallisce su tabelle popolate
    return rendered


# --- output ---------------------------------------------------------------


SECTION_TITLES = {
    "tables": "Tabelle e colonne",
    "constraints": "Indici, chiavi e vincoli",
    "views": "Viste",
    "sequences": "Sequenze",
    "synonyms": "Sinonimi",
}


def write_sql_script(scripts: Dict[str, List[str]], filename: str, target_env: str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"-- Script di allineamento per l'ambiente: {target_env}\n")
        f.write("-- Generato da DiFFDB. Rileggere prima di eseguire in produzione.\n\n")
        for section, statements in scripts.items():
            if not statements:
                continue
            f.write(f"-- === {SECTION_TITLES[section]} ===\n")
            f.write("\n".join(statements))
            f.write("\n\n")
    logger.info("Script SQL salvato in '%s'.", filename)


def generate_excel_report(diff: DiffResult, filename: str) -> None:
    import pandas as pd

    sections = {
        "Tabelle": diff.tables,
        "Vincoli": diff.constraints,
        "Viste": diff.views,
        "Sequenze": diff.sequences,
        "Sinonimi": diff.synonyms,
    }
    columns = ["Oggetto", "Tipo", "Campo", "Differenza", "Presente in", "Mancante in", "Dettaglio"]

    with pd.ExcelWriter(filename) as writer:
        for sheet, diffs in sections.items():
            rows = [d.as_row() for d in diffs]
            pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name=sheet, index=False)

    logger.info("Report Excel salvato in '%s'.", filename)


def expand(conn_str: str) -> str:
    """Espande le variabili d'ambiente: permette di tenere le password fuori dal file."""
    return os.path.expandvars(conn_str.strip())
