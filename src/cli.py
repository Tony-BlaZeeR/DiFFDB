"""Interfaccia a riga di comando: serve a mettere DiFFDB in pipeline.

    python -m src.cli --list
    python -m src.cli SVI COL --out ./report
    python -m src.cli SVI COL --fail-on-diff        # esce con 1 se ci sono differenze

Gli ambienti si indicano per nome (come in connections.json) oppure passando
direttamente due URL SQLAlchemy.
"""

import argparse
import logging
import sys

from src.connections import Connection, find, load_connections
from src.diff_DB import compare_environments
from src.report import write_outputs

logger = logging.getLogger("diffdb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffdb", description="Confronta la struttura di due database.")
    parser.add_argument("env1", nargs="?", help="Nome della connessione (o URL SQLAlchemy)")
    parser.add_argument("env2", nargs="?", help="Nome della connessione (o URL SQLAlchemy)")
    parser.add_argument("--schema1", help="Schema del primo ambiente")
    parser.add_argument("--schema2", help="Schema del secondo ambiente")
    parser.add_argument("--out", default=".", help="Cartella di output (default: quella corrente)")
    parser.add_argument("--fail-on-diff", action="store_true",
                        help="Esce con codice 1 se ci sono differenze (per la CI)")
    parser.add_argument("--quiet", action="store_true", help="Stampa solo le differenze")
    parser.add_argument("--list", action="store_true", help="Elenca le connessioni configurate")
    return parser


def resolve(token: str, schema, connections) -> Connection:
    """Un nome dal file connessioni, oppure direttamente un URL SQLAlchemy."""
    if "://" in token:
        return Connection(name=token.split("://")[0], conn_string=token, schema=schema)

    connection = find(connections, token)
    if connection is None:
        known = ", ".join(c.name for c in connections) or "nessuna"
        raise SystemExit(f"Connessione '{token}' non trovata. Configurate: {known}")
    if schema:
        connection.schema = schema
    return connection


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")

    connections = load_connections()

    if args.list:
        if not connections:
            print("Nessuna connessione configurata.")
        for connection in connections:
            schema = f" [schema: {connection.schema}]" if connection.schema else ""
            print(f"{connection.name}{schema}")
        return 0

    if not args.env1 or not args.env2:
        build_parser().print_help()
        return 2

    conn1 = resolve(args.env1, args.schema1, connections)
    conn2 = resolve(args.env2, args.schema2, connections)

    diff = compare_environments(
        conn1.name, conn1.conn_string, conn2.name, conn2.conn_string,
        conn1.schema, conn2.schema,
    )

    if diff.is_empty:
        print(f"Nessuna differenza fra {conn1.name} e {conn2.name}.")
        return 0

    for d in diff.all:
        target = f" (manca in {d.missing_in})" if d.missing_in else ""
        field = f".{d.column}" if d.column else ""
        detail = f" - {d.detail}" if d.detail else ""  # ASCII: la console Windows non e' UTF-8
        print(f"[{d.change}] {d.kind} {d.name}{field}{target}{detail}")

    for path in write_outputs(diff, args.out):
        print(f"Scritto: {path}")

    print(f"\n{len(diff.all)} differenze fra {conn1.name} e {conn2.name}.")
    return 1 if args.fail_on_diff else 0


if __name__ == "__main__":
    sys.exit(main())
