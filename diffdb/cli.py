"""Interfaccia a riga di comando: serve a mettere DiFFDB in pipeline.

    python -m diffdb.cli --list
    python -m diffdb.cli SVI COL --out ./report
    python -m diffdb.cli SVI COL --fail-on-diff        # esce con 1 se ci sono differenze

Gli ambienti si indicano per nome (come in connections.json), passando
direttamente due URL SQLAlchemy, oppure indicando uno snapshot salvato:

    python -m diffdb.cli PROD --snapshot baseline/prod.json   # fotografa e salva
    python -m diffdb.cli baseline/prod.json PROD              # drift dalla baseline
    python -m diffdb.cli baseline/prod.json baseline/pre.json # confronto offline
"""

import argparse
import getpass
import logging
import sys
from pathlib import Path

from diffdb import audit, keystore, log, rules
from diffdb.connections import (
    Connection,
    con_riferimento_al_portachiavi,
    find,
    load_connections,
    save_connections,
)
from diffdb.paths import config_dir
from diffdb.report import write_outputs
from diffdb.snapshot_io import (
    SnapshotFile,
    compare_sources,
    fingerprint,
    looks_like_snapshot,
    save,
    snapshot_of,
)
from diffdb.urls import mask_password, sanitize

logger = logging.getLogger("diffdb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffdb", description="Confronta la struttura di due database.")
    parser.add_argument("env1", nargs="?",
                        help="Connessione, URL SQLAlchemy o snapshot .json")
    parser.add_argument("env2", nargs="?",
                        help="Connessione, URL SQLAlchemy o snapshot .json")
    parser.add_argument("--schema1", help="Schema del primo ambiente")
    parser.add_argument("--schema2", help="Schema del secondo ambiente")
    parser.add_argument("--out", default=".", help="Cartella di output (default: quella corrente)")
    parser.add_argument("--snapshot", metavar="FILE",
                        help="Salva lo snapshot di env1 in FILE invece di confrontare")
    parser.add_argument("--fail-on-diff", action="store_true",
                        help="Esce con codice 1 se ci sono differenze (per la CI)")
    parser.add_argument("--quiet", action="store_true", help="Stampa solo le differenze")
    parser.add_argument("--list", action="store_true", help="Elenca le connessioni configurate")
    parser.add_argument("--set-password", metavar="NOME",
                        help="Salva nel portachiavi di sistema la password di NOME")
    parser.add_argument("--verify", metavar="SCRIPT",
                        help="Verifica che env1 non sia cambiato da quando\n"
                             "SCRIPT e' stato generato")
    parser.add_argument("--rules", metavar="FILE",
                        help=f"Regole di confronto (default: {rules.NOME_PREDEFINITO} "
                             f"nella cartella corrente o in quella di configurazione)")
    parser.add_argument("--no-rules", action="store_true",
                        help="Ignora il file delle regole e mostra tutto")
    parser.add_argument("--accept", action="store_true",
                        help="Aggiunge le differenze trovate alle accettate, e non le "
                             "mostra piu' finche' non cambiano")
    return parser


def carica_regole(args) -> rules.Regole:
    """Le regole indicate, o quelle trovate accanto alla configurazione.

    Il file va versionato col progetto: le esclusioni sono decisioni di squadra,
    non preferenze di chi lancia il comando.
    """
    if args.no_rules:
        return rules.NESSUNA

    percorso = Path(args.rules) if args.rules else rules.cerca([Path.cwd(), config_dir()])
    if percorso is None:
        return rules.NESSUNA

    regole = rules.carica(percorso)
    logger.info("Regole da '%s': %s", percorso, regole.descrizione() or "nessun filtro")
    return regole


def accetta(diff, args, regole: rules.Regole) -> int:
    """Registra le differenze trovate come accettate.

    Da qui in poi il confronto e' verde finche' non cambia qualcosa: e' quello
    che rende `--fail-on-diff` utilizzabile in pipeline su uno schema che parte
    gia' con differenze note."""
    percorso = Path(args.rules) if args.rules else (
        rules.cerca([Path.cwd(), config_dir()]) or Path.cwd() / rules.NOME_PREDEFINITO)

    nuove = {rules.chiave(d) for d in diff.all}
    aggiunte = nuove - regole.accettate
    regole.accettate |= nuove
    rules.salva(regole, percorso)

    print(f"{len(aggiunte)} differenze aggiunte alle accettate in {percorso}.")
    print(f"Totale accettate: {len(regole.accettate)}.")
    return 0


def resolve(token: str, schema, connections):
    """Una sorgente di confronto: snapshot su file, URL al volo o nome configurato."""
    if looks_like_snapshot(token):
        return SnapshotFile.at(token)

    if "://" in token:
        return Connection(name=token.split("://")[0], conn_string=token, schema=schema)

    connection = find(connections, token)
    if connection is None:
        known = ", ".join(c.name for c in connections) or "nessuna"
        raise SystemExit(f"Connessione '{token}' non trovata. Configurate: {known}")
    if schema:
        connection.schema = schema
    return connection


def imposta_password(nome: str, connections) -> int:
    """Chiede la password e la mette nel portachiavi, non nel file."""
    if not keystore.disponibile():
        print(f"Portachiavi non utilizzabile su questa macchina: {keystore.descrizione()}.")
        print("Dove non c'e' un portachiavi (CI, container) usa ${VARIABILE} d'ambiente.")
        return 2

    password = getpass.getpass(f"Password per '{nome}' (non viene mostrata): ")
    if not password:
        print("Password vuota: non ho salvato niente.")
        return 2

    keystore.scrivi(nome, password)
    print(f"Password di '{nome}' salvata nel portachiavi ({keystore.descrizione()}).")

    # Se la connessione esiste ed ha ancora la password nel file, la si sostituisce
    # col segnaposto: e' il punto di tutta l'operazione.
    connessione = find(connections, nome)
    if connessione is not None:
        aggiornata = con_riferimento_al_portachiavi(connessione.conn_string)
        if aggiornata != connessione.conn_string:
            connessione.conn_string = aggiornata
            save_connections(connections)
            print(f"Nel file ora c'e' il segnaposto: {aggiornata}")
    return 0


def verifica(percorso_script: str, token: str, schema, connections,
             regole=rules.NESSUNA) -> int:
    """Lo script e' ancora valido, o l'ambiente e' cambiato nel frattempo?

    Le regole servono anche qui: se lo script e' stato generato con dei filtri,
    l'impronta da confrontare va ricalcolata con gli stessi, altrimenti non
    tornera' mai."""
    try:
        meta = audit.leggi_meta(percorso_script)
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 2

    sorgente = resolve(token, schema, connections)
    attesa = meta.get("impronta_target")
    try:
        attuale = fingerprint(snapshot_of(sorgente, regole))
    except Exception as exc:
        # Sanificato: il messaggio del driver contiene l'URL completo.
        print(f"Impossibile leggere {mask_password(token)}: {sanitize(str(exc))}")
        return 2

    print(f"Script generato il {meta.get('generato')} da {meta.get('generato_da')} "
          f"con DiFFDB {meta.get('versione_diffdb')}")
    print(f"  impronta attesa su {meta.get('target')}")
    print(f"    {attesa}")
    print(f"  impronta attuale di {mask_password(token)}")
    print(f"    {attuale}")

    if attesa == attuale:
        print("\nL'ambiente non e' cambiato: lo script e' ancora valido.")
        return 0

    print("\nL'ambiente e' CAMBIATO dopo la generazione dello script.")
    print("Eseguirlo cosi' com'e' e' rischioso: rigeneralo.")
    return 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    log.configure(level=logging.WARNING if args.quiet else logging.INFO)

    connections = load_connections()

    if args.set_password:
        return imposta_password(args.set_password, connections)

    if args.verify:
        if not args.env1:
            print("Serve l'ambiente da verificare: diffdb --verify allinea_prod.sql PROD")
            return 2
        return verifica(args.verify, args.env1, args.schema1, connections,
                        carica_regole(args))

    if args.list:
        if not connections:
            print("Nessuna connessione configurata.")
        for connection in connections:
            schema = f" [schema: {connection.schema}]" if connection.schema else ""
            print(f"{connection.name}{schema}")
        return 0

    if args.snapshot:
        if not args.env1:
            print("Serve l'ambiente da fotografare: diffdb PROD --snapshot prod.json")
            return 2
        source = resolve(args.env1, args.schema1, connections)
        snapshot = snapshot_of(source, carica_regole(args))
        path = save(snapshot, args.snapshot, source=getattr(source, "conn_string", None))
        print(f"Snapshot di {snapshot.env_name} salvato in {path}")
        return 0

    if not args.env1 or not args.env2:
        build_parser().print_help()
        return 2

    regole = carica_regole(args)
    source1 = resolve(args.env1, args.schema1, connections)
    source2 = resolve(args.env2, args.schema2, connections)
    diff = compare_sources(source1, source2, regole)
    env1, env2 = diff.snapshot1.env_name, diff.snapshot2.env_name

    if args.accept:
        return accetta(diff, args, regole)

    if diff.is_empty:
        print(f"Nessuna differenza fra {env1} e {env2}."
              + (f" ({diff.accettate} gia' accettate)" if diff.accettate else ""))
        return 0

    for d in diff.all:
        target = f" (manca in {d.missing_in})" if d.missing_in else ""
        field = f".{d.column}" if d.column else ""
        detail = f" - {d.detail}" if d.detail else ""  # ASCII: la console Windows non e' UTF-8
        print(f"[{d.change}] {d.kind} {d.name}{field}{target}{detail}")

    for path in write_outputs(diff, args.out):
        print(f"Scritto: {path}")

    coda = f" ({diff.accettate} gia' accettate)" if diff.accettate else ""
    print(f"\n{len(diff.all)} differenze fra {env1} e {env2}.{coda}")
    return 1 if args.fail_on_diff else 0


if __name__ == "__main__":
    sys.exit(main())
