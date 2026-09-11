"""Confronto strutturale fra due ambienti e generazione degli script di allineamento.

Il confronto guarda colonne (nome, tipo, nullability), indici, foreign key,
constraint di unicita' e CHECK, chiavi primarie, viste, sequenze e sinonimi.
Gli script prodotti sono SQL eseguibile, compilato sul dialetto dell'ambiente
da allineare.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import CheckConstraint, MetaData, UniqueConstraint
from sqlalchemy.exc import NoReferencedTableError
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

from diffdb.config.dialectConfig import templates_for
from diffdb.rules import NESSUNA, Regole
from diffdb.schema_snapshot import (
    Snapshot,
    check_signature,
    expand,  # noqa: F401  (ri-esportata: era definita qui)
    fk_signature,
    index_signature,
    normalize_sql,
    snapshot_connection,
    take_snapshot,  # noqa: F401
    type_signature,
    unique_signature,
)

logger = logging.getLogger(__name__)

MISSING = "mancante"
TYPE_MISMATCH = "tipo diverso"
NULLABILITY_MISMATCH = "nullability diversa"
DEFAULT_MISMATCH = "default diverso"
DEFINITION_MISMATCH = "definizione diversa"


@dataclass
class Difference:
    kind: str          # table | column | index | foreign_key | unique | primary_key
                       # | view | sequence | synonym
    name: str
    change: str
    column: str | None = None
    missing_in: str | None = None
    present_in: str | None = None
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
    tables: list[Difference] = field(default_factory=list)
    constraints: list[Difference] = field(default_factory=list)
    views: list[Difference] = field(default_factory=list)
    sequences: list[Difference] = field(default_factory=list)
    synonyms: list[Difference] = field(default_factory=list)
    regole: Regole = field(default_factory=Regole)
    accettate: int = 0        # differenze nascoste perche' gia' accettate

    @property
    def all(self) -> list[Difference]:
        return self.tables + self.constraints + self.views + self.sequences + self.synonyms

    @property
    def is_empty(self) -> bool:
        return not self.all

    @property
    def sections(self) -> dict[str, list["Difference"]]:
        """Differenze raggruppate per categoria (usato dal tab dei risultati)."""
        return {
            "tables": self.tables,
            "constraints": self.constraints,
            "views": self.views,
            "sequences": self.sequences,
            "synonyms": self.synonyms,
        }

    def subset(self, keep) -> "DiffResult":
        """Nuovo DiffResult con le sole differenze in `keep` (per identita').

        Serve all'export selettivo: l'utente spunta cosa vuole e si genera lo
        script solo per quelle differenze.
        """
        ids = {id(d) for d in keep}
        return DiffResult(
            snapshot1=self.snapshot1,
            snapshot2=self.snapshot2,
            regole=self.regole,
            accettate=self.accettate,
            tables=[d for d in self.tables if id(d) in ids],
            constraints=[d for d in self.constraints if id(d) in ids],
            views=[d for d in self.views if id(d) in ids],
            sequences=[d for d in self.sequences if id(d) in ids],
            synonyms=[d for d in self.synonyms if id(d) in ids],
        )

    def snapshot_of(self, env_name: str) -> Snapshot:
        if env_name == self.snapshot1.env_name:
            return self.snapshot1
        if env_name == self.snapshot2.env_name:
            return self.snapshot2
        raise KeyError(f"Ambiente sconosciuto: {env_name}")

    def other_than(self, env_name: str) -> Snapshot:
        return self.snapshot2 if env_name == self.snapshot1.env_name else self.snapshot1


# --- confronto ------------------------------------------------------------


def compare_environments(env1_name, conn_str1, env2_name, conn_str2, schema1=None,
                         schema2=None, regole: Regole = NESSUNA,
                         annullabile=None) -> DiffResult:
    """Confronta due ambienti. Le connection string possono contenere ${VAR} d'ambiente."""
    snap1, snap2 = leggi_in_parallelo(
        (env1_name, conn_str1, schema1), (env2_name, conn_str2, schema2),
        regole=regole, annullabile=annullabile)
    return compare_snapshots(snap1, snap2, regole)


def leggi_in_parallelo(primo, secondo, regole: Regole = NESSUNA, annullabile=None):
    """Fotografa i due ambienti insieme invece che uno dopo l'altro.

    Sono indipendenti, e su uno schema grande la lettura e' quasi tutto il tempo
    del confronto: farla in parallelo lo dimezza. I driver rilasciano il GIL
    mentre aspettano il database, quindi due thread bastano.
    """
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="diffdb-lettura") as pool:
        futuri = [pool.submit(snapshot_connection, nome, conn, schema, regole, annullabile)
                  for nome, conn, schema in (primo, secondo)]
        return futuri[0].result(), futuri[1].result()


def compare_snapshots(snap1: Snapshot, snap2: Snapshot,
                      regole: Regole | None = None) -> DiffResult:
    if regole is None:
        regole = snap1.regole if not snap1.regole.vuote else snap2.regole
    result = DiffResult(snapshot1=snap1, snapshot2=snap2, regole=regole)
    e1, e2 = snap1.env_name, snap2.env_name

    tables1, tables2 = set(snap1.tables), set(snap2.tables)
    for table in sorted(tables2 - tables1):
        result.tables.append(Difference("table", table, MISSING, missing_in=e1, present_in=e2))
    for table in sorted(tables1 - tables2):
        result.tables.append(Difference("table", table, MISSING, missing_in=e2, present_in=e1))

    for table in sorted(tables1 & tables2):
        result.tables.extend(_compare_columns(table, snap1, snap2))
        result.constraints.extend(_compare_constraints(table, snap1, snap2))

    result.views = _compare_views(snap1, snap2)
    result.sequences = _compare_sequences(snap1, snap2)
    result.synonyms = _compare_synonyms(snap1, snap2)
    return _applica_regole(result, regole)


def _applica_regole(result: DiffResult, regole: Regole) -> DiffResult:
    """Toglie le categorie spente e le differenze gia' accettate.

    Le accettate si tolgono qui e non durante la lettura: restano comunque
    contate, e chi vuole vederle lancia il confronto senza baseline.
    """
    if regole.vuote:
        return result

    for categoria in ("tables", "constraints", "views", "sequences", "synonyms"):
        differenze = getattr(result, categoria)
        if not regole.categoria_inclusa(categoria):
            setattr(result, categoria, [])
            continue
        rimaste = [d for d in differenze if not regole.accettata(d)]
        result.accettate += len(differenze) - len(rimaste)
        setattr(result, categoria, rimaste)

    if result.accettate:
        logger.info("%d differenze gia' accettate non vengono mostrate.", result.accettate)
    return result


def _compare_columns(table: str, snap1: Snapshot, snap2: Snapshot) -> list[Difference]:
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
        def1, def2 = default_signature(cols1[col]), default_signature(cols2[col])
        if normalize_sql(def1) != normalize_sql(def2):
            diffs.append(Difference(
                "column", table, DEFAULT_MISMATCH, column=col,
                detail=f"{e1}: {def1 or '(nessuno)'} | {e2}: {def2 or '(nessuno)'}",
            ))

    return diffs


def _compare_constraints(table: str, snap1: Snapshot, snap2: Snapshot) -> list[Difference]:
    """Indici, foreign key, unique, check e chiave primaria."""
    diffs = []
    e1, e2 = snap1.env_name, snap2.env_name

    for kind, getter in (
        ("index", Snapshot.indexes),
        ("foreign_key", Snapshot.foreign_keys),
        ("unique", Snapshot.unique_constraints),
        ("check", Snapshot.check_constraints),
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


def _compare_sequences(snap1: Snapshot, snap2: Snapshot) -> list[Difference]:
    e1, e2 = snap1.env_name, snap2.env_name
    diffs = _compare_names("sequence", set(snap1.sequences), set(snap2.sequences), e1, e2)

    for name in sorted(set(snap1.sequences) & set(snap2.sequences)):
        spec1, spec2 = snap1.sequences[name], snap2.sequences[name]
        if spec1.signature() != spec2.signature():
            diffs.append(Difference(
                "sequence", name, DEFINITION_MISMATCH,
                detail=f"{e1}: {spec1.signature()} | {e2}: {spec2.signature()}"))
    return diffs


def _compare_views(snap1: Snapshot, snap2: Snapshot) -> list[Difference]:
    e1, e2 = snap1.env_name, snap2.env_name
    diffs = _compare_names("view", set(snap1.views), set(snap2.views), e1, e2)

    # Viste presenti in entrambi: confronto il corpo della definizione.
    # Il confronto e' affidabile fra ambienti dello stesso dialetto (il caso reale
    # SVI vs PRE), dove il database normalizza il testo allo stesso modo.
    for name in sorted(set(snap1.views) & set(snap2.views)):
        body1, body2 = snap1.views[name], snap2.views[name]
        if normalize_sql(body1) != normalize_sql(body2):
            diffs.append(Difference("view", name, DEFINITION_MISMATCH,
                                    detail="il corpo della vista e' diverso nei due ambienti"))
    return diffs


def _compare_synonyms(snap1: Snapshot, snap2: Snapshot) -> list[Difference]:
    e1, e2 = snap1.env_name, snap2.env_name
    diffs = _compare_names("synonym", set(snap1.synonyms), set(snap2.synonyms), e1, e2)

    for name in sorted(set(snap1.synonyms) & set(snap2.synonyms)):
        if snap1.synonyms[name] != snap2.synonyms[name]:
            diffs.append(Difference(
                "synonym", name, DEFINITION_MISMATCH,
                detail=f"{e1}: {snap1.synonyms[name]} | "
                       f"{e2}: {snap2.synonyms[name]}"))
    return diffs


def _compare_names(kind, names1, names2, env1, env2) -> list[Difference]:
    diffs = []
    for name in sorted(set(names2) - set(names1)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env1, present_in=env2))
    for name in sorted(set(names1) - set(names2)):
        diffs.append(Difference(kind, name, MISSING, missing_in=env2, present_in=env1))
    return diffs


def _null(column) -> str:
    return "NULL" if column.nullable else "NOT NULL"


def default_signature(column) -> str:
    """Testo del default lato server, o stringa vuota se la colonna non ne ha."""
    server_default = column.server_default
    if server_default is None:
        return ""
    arg = getattr(server_default, "arg", None)
    if arg is None:
        return ""
    text = getattr(arg, "text", arg)  # DefaultClause.arg puo' essere un TextClause
    return str(text).strip()


# --- generazione SQL ------------------------------------------------------


def generate_sql_scripts(diff: DiffResult, target_env: str) -> dict[str, list[str]]:
    """Script da eseguire su `target_env` per allinearlo all'altro ambiente."""
    if diff.snapshot1.env_name == diff.snapshot2.env_name:
        # Il confronto regge due omonimi, la generazione no: gli ambienti si
        # identificano per nome, e non si saprebbe quale dei due allineare.
        raise ValueError(
            f"I due ambienti si chiamano entrambi '{target_env}': "
            f"per generare lo script servono due nomi diversi."
        )

    target = diff.snapshot_of(target_env)
    source = diff.other_than(target_env)
    templates = templates_for(target.dialect)
    quote = target.dialect_impl.identifier_preparer.quote
    portable = _portable_metadata(source, target)

    def qualify(name: str) -> str:
        """Nome qualificato con lo schema del target.

        Senza questo, un ALTER TABLE generato per lo schema APP finirebbe sulla
        tabella omonima dello schema di default dell'utente connesso. Il DDL
        compilato da SQLAlchemy (CREATE TABLE, CREATE INDEX) lo fa gia' da se'.
        """
        return f"{quote(target.schema)}.{quote(name)}" if target.schema else quote(name)

    scripts = {"tables": [], "constraints": [], "views": [], "sequences": [], "synonyms": []}

    # Le tabelle nuove vanno create prima di quelle che le referenziano: le
    # foreign key sono dentro il CREATE TABLE, e in ordine alfabetico uno script
    # con 'ordini' prima di 'clienti' fallisce a meta'.
    for table in _in_ordine_di_dipendenza(
            [d.name for d in diff.tables
             if d.kind == "table" and d.missing_in == target_env],
            portable, target, scripts):
        try:
            scripts["tables"].append(_compile(CreateTable(table), target))
        except NoReferencedTableError as exc:
            # Capita con uno snapshot scritto a mano in cui una foreign key
            # punta a una tabella che nel file non c'e'. Meglio dirlo che
            # fermare la generazione di tutto lo script.
            logger.warning("Tabella %s non generabile: %s", table.name, exc)
            scripts["tables"].append(
                f"-- Tabella {table.name} non generata: una sua foreign key punta a "
                f"una tabella che non e' nel confronto ({exc.table_name}). "
                f"Controlla i filtri o lo snapshot.")
            continue
        # CREATE TABLE non porta con se' gli indici: vanno emessi a parte.
        scripts["constraints"].extend(
            _compile(CreateIndex(index), target) for index in table.indexes)

    for d in diff.tables:
        if d.kind == "table":
            continue                      # gia' emesse, in ordine di dipendenza
        if d.kind == "column" and d.change == MISSING and d.missing_in == target_env:
            column = source.columns(d.name)[d.column]
            scripts["tables"].append(templates["add"].format(
                table=qualify(d.name), column=quote(d.column), type=_column_type(column, target)))
        elif d.kind == "column" and d.change == TYPE_MISMATCH:
            column = source.columns(d.name)[d.column]
            nullability = _nullability_suffix(
                column, target.columns(d.name).get(d.column), templates["modify_nullability"])
            scripts["tables"].append(templates["modify"].format(
                table=qualify(d.name), column=quote(d.column),
                type=_column_type(column, target, nullability)))
        elif d.kind == "column" and d.change == NULLABILITY_MISMATCH:
            scripts["tables"].append(
                f"-- {d.name}.{d.column}: nullability diversa ({d.detail}). "
                f"Va valutata a mano: su tabelle popolate un NOT NULL puo' fallire."
            )
        elif d.kind == "column" and d.change == DEFAULT_MISMATCH:
            scripts["tables"].append(_default_ddl(d, source, target, templates, qualify, quote))

    for d in diff.constraints:
        if d.missing_in != target_env:
            if d.kind == "primary_key" and d.change == DEFINITION_MISMATCH:
                scripts["constraints"].append(
                    f"-- Chiave primaria diversa su {d.name} ({d.detail}). "
                    f"Cambiarla e' un'operazione distruttiva: va valutata a mano."
                )
            continue

        if d.kind in ("foreign_key", "unique", "check") and not templates["alter_add_constraint"]:
            scripts["constraints"].append(
                f"-- {target.dialect} non sa aggiungere vincoli a una tabella esistente: "
                f"il vincolo {d.kind} {d.detail} su {d.name} va creato ricreando la tabella"
            )
            continue

        ddl = _constraint_ddl(d, portable, target)
        if ddl:
            scripts["constraints"].append(ddl)

    for d in diff.views:
        if d.missing_in != target_env and d.change != DEFINITION_MISMATCH:
            continue  # la vista manca nell'altro ambiente, non nel target: niente da fare qui
        definition = source.views.get(d.name) or ""
        if not definition.strip():
            scripts["views"].append(
                f"-- Definizione della vista {d.name} non leggibile da "
                f"{source.env_name}: va copiata a mano"
            )
        elif d.change == DEFINITION_MISMATCH:
            scripts["views"].append(_replace_view_ddl(d.name, definition, templates, qualify))
        else:
            scripts["views"].append(_create_view_ddl(d.name, definition, qualify))

    for d in diff.sequences:
        if not templates["sequences"]:
            scripts["sequences"].append(
                f"-- {target.dialect} non supporta le sequenze: {d.name} non e' replicabile")
            continue
        if d.missing_in == target_env:
            scripts["sequences"].append(_create_sequence_ddl(source.sequences[d.name], qualify))
        elif d.change == DEFINITION_MISMATCH:
            template = templates["alter_sequence"]
            spec = source.sequences[d.name]
            scripts["sequences"].append(
                template.format(name=qualify(d.name), start=spec.start, increment=spec.increment)
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
                name=qualify(d.name), target=source.synonyms.get(d.name, "?")))

    return scripts


def generate_rollback_scripts(diff: DiffResult, target_env: str) -> dict[str, list[str]]:
    """Come disfare quello che `generate_sql_scripts` ha appena fatto.

    Serve dove il database non sa annullare un DDL — Oracle e MySQL fanno commit
    a ogni istruzione — cioe' proprio dove una transazione non c'e'. Ma serve
    anche altrove: una transazione protegge dentro l'esecuzione, non dal
    pentimento del giorno dopo.

    Si ricava dalle stesse Difference dello script di andata, non invertendo il
    testo SQL: leggere all'indietro delle stringhe sarebbe fragile, e qui gli
    errori sono distruttivi.

    Non annulla tutto: quello che l'allineamento ha lasciato come commento resta
    un commento anche qui, e cio' che non e' reversibile in modo univoco viene
    detto invece che indovinato.
    """
    target = diff.snapshot_of(target_env)
    source = diff.other_than(target_env)
    templates = templates_for(target.dialect)
    quote = target.dialect_impl.identifier_preparer.quote
    portable = _portable_metadata(source, target)

    def qualify(name: str) -> str:
        return f"{quote(target.schema)}.{quote(name)}" if target.schema else quote(name)

    scripts = {"tables": [], "constraints": [], "views": [], "sequences": [], "synonyms": []}

    # Prima i vincoli e gli indici, poi le tabelle: l'ordine inverso
    # dell'andata, o si prova a togliere una tabella che qualcuno referenzia.
    for d in diff.constraints:
        if d.missing_in != target_env:
            continue
        scripts["constraints"].append(
            _annulla_vincolo(d, portable, target, templates, qualify, quote))

    da_eliminare = [d.name for d in diff.tables
                    if d.kind == "table" and d.missing_in == target_env]
    for table in reversed(_in_ordine_di_dipendenza(da_eliminare, portable, target, scripts)):
        scripts["tables"].append(templates["drop_table"].format(table=qualify(table.name)))

    for d in diff.tables:
        if d.kind != "column":
            continue
        if d.change == MISSING and d.missing_in == target_env:
            # La colonna non c'era: toglierla riporta indietro, ma i dati messi
            # nel frattempo se ne vanno. Va detto, non nascosto.
            scripts["tables"].append(
                f"-- Attenzione: {d.name}.{d.column} e' stata aggiunta dall'allineamento. "
                f"Toglierla cancella i dati scritti da allora.")
            scripts["tables"].append(templates["drop"].format(
                table=qualify(d.name), column=quote(d.column)))
        elif d.change == TYPE_MISMATCH:
            scripts["tables"].append(_ripristina_tipo(d, target, templates, qualify, quote))
        elif d.change == DEFAULT_MISMATCH:
            scripts["tables"].append(_ripristina_default(d, target, templates, qualify, quote))

    for d in diff.views:
        if d.missing_in == target_env and templates["drop_view"]:
            scripts["views"].append(templates["drop_view"].format(name=qualify(d.name)))
        elif d.change == DEFINITION_MISMATCH:
            definizione = target.views.get(d.name) or ""
            scripts["views"].append(
                _replace_view_ddl(d.name, definizione, templates, qualify) if definizione.strip()
                else f"-- La vista {d.name} e' stata riscritta: il corpo precedente non "
                     f"e' leggibile da qui, va ripreso a mano.")

    for d in diff.sequences:
        if d.missing_in == target_env and templates["sequences"] and templates["drop_sequence"]:
            scripts["sequences"].append(templates["drop_sequence"].format(name=qualify(d.name)))

    for d in diff.synonyms:
        if d.missing_in == target_env and templates["drop_synonym"]:
            scripts["synonyms"].append(templates["drop_synonym"].format(name=qualify(d.name)))

    return {sezione: [i for i in istruzioni if i] for sezione, istruzioni in scripts.items()}


def _annulla_vincolo(d: Difference, portable: MetaData, target: Snapshot, templates: dict,
                     qualify, quote) -> str | None:
    """DROP dell'indice o del vincolo che l'allineamento ha aggiunto."""
    if d.kind == "index":
        table = _portable_table(portable, d.name, target.schema)
        nome = next((i.name for i in (table.indexes if table is not None else [])
                     if index_signature(i) == d.detail), None)
        if not nome:
            return f"-- Indice {d.detail} su {d.name}: non se ne ricava il nome, va tolto a mano."
        return templates["drop_index"].format(index=quote(nome), table=qualify(d.name))

    if d.kind in ("foreign_key", "unique", "check"):
        if not templates["alter_add_constraint"]:
            return None          # non era stato aggiunto: niente da togliere
        nome = _nome_vincolo(d, portable, target)
        if not nome:
            return (f"-- Vincolo {d.kind} {d.detail} su {d.name}: non se ne ricava il nome, "
                    f"va tolto a mano.")
        # Ogni categoria puo' avere il suo modo di togliersi (MySQL usa DROP
        # CHECK per i check e DROP FOREIGN KEY per le foreign key, non il
        # generico DROP CONSTRAINT): si prova la voce specifica, poi quella
        # generale.
        specifico = templates.get(f"drop_{d.kind}")
        modello = specifico if specifico else templates["drop_constraint"]
        if not modello:
            return f"-- {target.dialect} non sa togliere un {d.kind} da una tabella esistente."
        return modello.format(table=qualify(d.name), name=quote(nome))

    return None


def _nome_vincolo(d: Difference, portable: MetaData, target: Snapshot) -> str | None:
    table = _portable_table(portable, d.name, target.schema)
    if table is None:
        return None
    if d.kind == "foreign_key":
        return next((fk.name for fk in table.foreign_key_constraints
                     if fk_signature(fk) == d.detail), None)
    if d.kind == "check":
        return next((c.name for c in table.constraints
                     if isinstance(c, CheckConstraint) and check_signature(c) == d.detail), None)
    return next((c.name for c in table.constraints
                 if isinstance(c, UniqueConstraint) and unique_signature(c) == d.detail), None)


def _ripristina_tipo(d: Difference, target: Snapshot, templates: dict, qualify, quote) -> str:
    """Rimette il tipo che la colonna aveva prima dell'allineamento.

    Lo sappiamo con certezza: e' quello letto dall'ambiente da allineare.
    """
    colonna = target.columns(d.name).get(d.column)
    if colonna is None:
        return f"-- {d.name}.{d.column}: tipo precedente non ricavabile, va rimesso a mano."
    return templates["modify"].format(
        table=qualify(d.name), column=quote(d.column),
        type=_column_type(colonna, target,
                          _nullability_suffix(colonna, colonna, templates["modify_nullability"])))


def _ripristina_default(d: Difference, target: Snapshot, templates: dict, qualify, quote) -> str:
    colonna = target.columns(d.name).get(d.column)
    precedente = default_signature(colonna) if colonna is not None else ""
    modello = templates["set_default"] if precedente else templates["drop_default"]
    if modello is None:
        return (f"-- {target.dialect}: il default di {d.name}.{d.column} va rimesso a mano "
                f"({precedente or 'nessuno'}).")
    if precedente:
        return modello.format(table=qualify(d.name), column=quote(d.column), default=precedente)
    return modello.format(table=qualify(d.name), column=quote(d.column))


def _in_ordine_di_dipendenza(nomi, portable: MetaData, target: Snapshot,
                             scripts: dict[str, list[str]]) -> list:
    """Le tabelle da creare, ordinate perche' ogni foreign key trovi il suo bersaglio.

    Se fra le tabelle c'e' un ciclo (A punta a B e B punta ad A) nessun ordine
    funziona: si avvisa e si lascia l'ordine alfabetico, perche' meta' script
    eseguito e' meglio di uno script che sembra a posto e non lo e'.
    """
    volute = {}
    for nome in nomi:
        tabella = _portable_table(portable, nome, target.schema)
        if tabella is not None:
            volute[tabella.key] = tabella

    if not volute:
        return []

    ordine, ciclo = _ordine_topologico(volute)
    if ciclo:
        # Con un ciclo (A punta a B e B punta ad A) nessun ordine funziona.
        # Va detto: meta' script eseguito e' meglio di uno che sembra a posto.
        logger.warning("Ciclo di foreign key fra le tabelle da creare: %s", ", ".join(ciclo))
        scripts["tables"].append(
            "-- Attenzione: fra le tabelle da creare c'e' un ciclo di foreign key "
            f"({', '.join(ciclo)}). Nessun ordine le soddisfa tutte: crea prima le "
            "tabelle e aggiungi a mano i vincoli che restano.")

    return [volute[chiave] for chiave in ordine]


def _ordine_topologico(volute: dict[str, object]):
    """Ordina per dipendenza. Restituisce (ordine, tabelle_in_ciclo).

    Si guardano solo le dipendenze *fra le tabelle da creare*: una foreign key
    verso una tabella che esiste gia' nel target non vincola niente.
    """
    dipendenze = {}
    for chiave, tabella in volute.items():
        riferite = set()
        for fk in tabella.foreign_key_constraints:
            for elemento in fk.elements:
                # target_fullname e' "schema.tabella.colonna" oppure "tabella.colonna":
                # la chiave della tabella e' tutto tranne l'ultimo pezzo. Si legge
                # dalla stringa per non forzare la risoluzione della foreign key.
                bersaglio = ".".join(elemento.target_fullname.split(".")[:-1])
                if bersaglio in volute and bersaglio != chiave:
                    riferite.add(bersaglio)   # l'auto-riferimento non e' un ciclo
        dipendenze[chiave] = riferite

    ordine, rimaste = [], dict(dipendenze)
    while rimaste:
        # A parita' di vincoli si va in ordine alfabetico: due esecuzioni dello
        # stesso confronto devono produrre lo stesso file.
        pronte = sorted(chiave for chiave, deps in rimaste.items() if not deps)
        if not pronte:
            in_ciclo = sorted(rimaste)
            return ordine + in_ciclo, in_ciclo
        for chiave in pronte:
            ordine.append(chiave)
            del rimaste[chiave]
        for deps in rimaste.values():
            deps.difference_update(pronte)

    return ordine, []


def _constraint_ddl(d: Difference, portable: MetaData, target: Snapshot) -> str | None:
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
            if (isinstance(constraint, UniqueConstraint)
                    and unique_signature(constraint) == d.detail):
                return _compile(AddConstraint(constraint), target)

    elif d.kind == "check":
        for constraint in table.constraints:
            if (isinstance(constraint, CheckConstraint)
                    and check_signature(constraint) == d.detail):
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


def _portable_table(portable: MetaData, name: str, schema: str | None):
    return portable.tables.get(f"{schema}.{name}" if schema else name)


def _compile(ddl_element, target: Snapshot) -> str:
    return str(ddl_element.compile(dialect=target.dialect_impl)).strip().rstrip(";") + ";"


# MySQL restituisce la definizione completa con le sue clausole in mezzo:
#   CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`%` SQL SECURITY DEFINER VIEW x AS ...
# Senza riconoscerle, la definizione veniva avvolta in un secondo CREATE VIEW e
# il risultato non era SQL valido.
VIEW_HEADER = re.compile(
    r"^\s*CREATE\s+"
    r"(?:(?:OR\s+REPLACE|TEMP\w*|ALGORITHM\s*=\s*\S+|DEFINER\s*=\s*\S+"
    r"|SQL\s+SECURITY\s+\w+)\s+)*"
    r"VIEW\b",
    re.IGNORECASE)


def _create_view_ddl(name, definition: str, qualify) -> str:
    """Alcuni dialetti (SQLite, MySQL) restituiscono gia' il CREATE VIEW completo,
    altri (PostgreSQL, Oracle) solo il corpo della SELECT."""
    body = definition.strip().rstrip(";")
    if VIEW_HEADER.match(body):
        return f"{body};"
    return f"CREATE VIEW {qualify(name)} AS\n{body};"


def _replace_view_ddl(name, definition: str, templates: dict, qualify) -> str:
    """Riscrive una vista gia' esistente ma con corpo diverso.

    Dove c'e' CREATE OR REPLACE lo si usa; altrimenti (SQL Server, SQLite) si fa
    DROP + CREATE.
    """
    create = _create_view_ddl(name, definition, qualify)
    if templates["view_or_replace"]:
        gia_or_replace = re.match(r"^\s*CREATE\s+OR\s+REPLACE", create, re.IGNORECASE)
        if VIEW_HEADER.match(create) and not gia_or_replace:
            return re.sub(r"^\s*CREATE\s+VIEW", "CREATE OR REPLACE VIEW", create,
                          count=1, flags=re.IGNORECASE)
        return create
    return f"DROP VIEW {qualify(name)};\n{create}"


def _default_ddl(d: Difference, source: Snapshot, target: Snapshot, templates: dict,
                 qualify, quote) -> str:
    """ALTER per allineare il default di una colonna al valore dell'altro ambiente."""
    wanted = default_signature(source.columns(d.name)[d.column])
    if wanted:
        template = templates["set_default"]
        if template is None:
            return (f"-- {target.dialect}: il default di {d.name}.{d.column} "
                    f"va cambiato a mano ({d.detail})")
        return template.format(table=qualify(d.name), column=quote(d.column), default=wanted)

    template = templates["drop_default"]
    if template is None:
        return (f"-- {target.dialect}: il default di {d.name}.{d.column} "
                f"va rimosso a mano ({d.detail})")
    return template.format(table=qualify(d.name), column=quote(d.column))


def _create_sequence_ddl(spec, qualify) -> str:
    parts = [f"CREATE SEQUENCE {qualify(spec.name)}",
             f"START WITH {spec.start}",
             f"INCREMENT BY {spec.increment}"]
    if spec.minvalue is not None:
        parts.append(f"MINVALUE {spec.minvalue}")
    if spec.maxvalue is not None:
        parts.append(f"MAXVALUE {spec.maxvalue}")
    if spec.cycle:
        parts.append("CYCLE")
    return " ".join(parts) + ";"


def _column_type(column, target: Snapshot, nullability: str | None = None) -> str:
    """Tipo della colonna reso nel dialetto del target.

    `nullability` e' la clausola NULL/NOT NULL da accodare. Se non viene passata
    (caso ADD COLUMN) si usa la regola prudente: NOT NULL solo insieme a un
    default, perche' altrimenti fallisce su una tabella gia' popolata.
    """
    try:
        rendered = column.type.compile(dialect=target.dialect_impl)
    except Exception as exc:  # tipo specifico di un altro dialetto
        logger.warning("Tipo %s non compilabile su %s: %s", column.type, target.dialect, exc)
        rendered = str(column.type)

    arg = getattr(column.server_default, "arg", None)
    if column.server_default is not None and arg is not None:
        rendered += f" DEFAULT {arg}"
    if nullability is None:
        senza_rischio = not column.nullable and column.server_default is not None
        nullability = " NOT NULL" if senza_rischio else ""
    return rendered + nullability


def _nullability_suffix(column, target_column, mode: str) -> str:
    """Clausola NULL/NOT NULL da riaffermare in un ALTER che cambia il tipo.

    MySQL e SQL Server riscrivono la colonna da capo: quello che non si ripete
    va perso, e una colonna NOT NULL tornerebbe silenziosamente nullable.
    Oracle invece conserva gli attributi, e ripetere un NOT NULL gia' presente
    e' un errore (ORA-01442): li' si riafferma solo quando cambia davvero.
    PostgreSQL non accetta proprio la clausola in ALTER COLUMN ... TYPE.
    """
    if mode == "never":
        return ""
    if mode == "when_changed":
        if target_column is None or bool(target_column.nullable) == bool(column.nullable):
            return ""
        return " NULL" if column.nullable else " NOT NULL"
    return "" if column.nullable else " NOT NULL"  # "always"
