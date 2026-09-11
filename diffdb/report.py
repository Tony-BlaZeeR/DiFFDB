"""Scrittura degli output. Nessuna dipendenza da Qt: la usano sia la GUI sia la CLI.

Ogni file prodotto porta con se' da dove viene: lo script SQL ha l'intestazione
di tracciabilita' (vedi src/audit.py), l'Excel ha il foglio "Informazioni".
"""

import logging
import os
import re

from diffdb.audit import intestazione
from diffdb.config.dialectConfig import templates_for
from diffdb.diff_DB import DiffResult, generate_rollback_scripts, generate_sql_scripts
from diffdb.snapshot_io import fingerprint

logger = logging.getLogger(__name__)

SECTION_TITLES = {
    "tables": "Tabelle e colonne",
    "constraints": "Indici, chiavi e vincoli",
    "views": "Viste",
    "sequences": "Sequenze",
    "synonyms": "Sinonimi",
}

COLONNE = ["Oggetto", "Tipo", "Campo", "Differenza", "Presente in", "Mancante in", "Dettaglio"]


def write_excel(diff, output_dir: str) -> str:
    """Solo il report Excel. Restituisce il percorso scritto."""
    os.makedirs(output_dir, exist_ok=True)
    excel_path = os.path.join(output_dir, "differenze_ambienti.xlsx")
    generate_excel_report(diff, excel_path)
    return excel_path


def write_sql(diff, output_dir: str, totali=None):
    """Per ogni direzione: lo script di allineamento e quello per disfarlo.

    L'annullamento serve soprattutto dove il database non sa annullare un DDL —
    Oracle e MySQL fanno commit a ogni istruzione — ma anche altrove: una
    transazione protegge dentro l'esecuzione, non dal pentimento del giorno dopo.
    """
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for target in (diff.snapshot1.env_name, diff.snapshot2.env_name):
        scripts = generate_sql_scripts(diff, target)
        if not any(scripts.values()):
            continue

        sql_path = os.path.join(output_dir, f"allinea_{slug(target)}.sql")
        write_sql_script(scripts, sql_path, target, diff, totali=totali)
        written.append(sql_path)

        annullamento = generate_rollback_scripts(diff, target)
        if any(annullamento.values()):
            rollback_path = os.path.join(output_dir, f"annulla_{slug(target)}.sql")
            write_sql_script(annullamento, rollback_path, target, diff,
                             totali=totali, annullamento=True)
            written.append(rollback_path)
    return written


class ExcelNonDisponibile(RuntimeError):
    """pandas e openpyxl non sono installati."""


def write_outputs(diff, output_dir: str, totali=None):
    """Report Excel piu' gli script SQL (usato dalla CLI).

    L'Excel e' un extra: in pipeline serve lo script, non il foglio di calcolo,
    e pandas pesa. Se manca si scrivono comunque gli script invece di far
    fallire tutto il comando.
    """
    prodotti = []
    try:
        prodotti.append(write_excel(diff, output_dir))
    except ExcelNonDisponibile as exc:
        logger.warning("%s", exc)
    return prodotti + write_sql(diff, output_dir, totali=totali)


def write_sql_script(scripts, filename: str, target_env: str,
                     diff: DiffResult = None, totali=None,
                     annullamento: bool = False) -> None:
    templates = templates_for(diff.snapshot_of(target_env).dialect) if diff else None

    # Disfare vuol dire percorrere all'indietro: le viste e i vincoli prima
    # delle tabelle, o si prova a togliere una tabella che qualcuno usa ancora.
    sezioni = list(reversed(list(scripts))) if annullamento else list(scripts)

    with open(filename, "w", encoding="utf-8") as f:
        if diff is not None:
            f.write(intestazione(diff, target_env, incluse=len(diff.all), totali=totali,
                                 annullamento=annullamento))
            f.write("\n")
        if annullamento:
            f.write(_avviso_annullamento())
        if templates:
            f.write(_apertura_transazione(templates))

        for section in sezioni:
            statements = scripts[section]
            if not statements:
                continue
            f.write(f"-- === {SECTION_TITLES[section]} ===\n")
            f.write("\n".join(statements))
            f.write("\n\n")

        if templates and templates["commit"]:
            f.write(templates["commit"] + "\n")

    logger.info("Script SQL salvato in '%s'.", filename)


def _avviso_annullamento() -> str:
    """Questo script cancella. Va detto prima, non in fondo."""
    return ("-- ATTENZIONE: questo script ELIMINA gli oggetti creati dall'allineamento.\n"
            "-- Vale solo se eseguito sull'ambiente allineato e prima di altre modifiche.\n"
            "-- I dati scritti nelle colonne e nelle tabelle nuove vengono persi.\n\n")


def _apertura_transazione(templates: dict) -> str:
    """Apre la transazione, oppure spiega perche' non c'e'.

    Oracle e MySQL fanno commit implicito a ogni DDL: avvolgerli in BEGIN/COMMIT
    darebbe l'illusione di poter annullare, che e' peggio che non averla.
    """
    if templates["begin"]:
        return ("-- Tutto o niente: se un'istruzione fallisce non resta niente a meta'.\n"
                + templates["begin"] + "\n\n")
    return ("-- Attenzione: su questo database ogni istruzione DDL fa commit da sola.\n"
            "-- Se lo script si ferma a meta', quello che e' gia' passato resta.\n"
            "-- Conviene eseguirlo un blocco alla volta, controllando fra uno e l'altro.\n\n")


def generate_excel_report(diff: DiffResult, filename: str) -> None:
    try:
        import pandas as pd
    except ImportError as exc:
        raise ExcelNonDisponibile(
            "Report Excel non disponibile: manca pandas. "
            "Installalo con: pip install 'diffdb[report]'") from exc

    sections = {
        "Tabelle": diff.tables,
        "Vincoli": diff.constraints,
        "Viste": diff.views,
        "Sequenze": diff.sequences,
        "Sinonimi": diff.synonyms,
    }

    with pd.ExcelWriter(filename) as writer:
        _foglio_informazioni(diff).to_excel(writer, sheet_name="Informazioni", index=False)
        for sheet, diffs in sections.items():
            rows = [d.as_row() for d in diffs]
            pd.DataFrame(rows, columns=COLONNE).to_excel(writer, sheet_name=sheet, index=False)

    logger.info("Report Excel salvato in '%s'.", filename)


def _foglio_informazioni(diff: DiffResult):
    """Da dove viene questo report: e' il foglio che si guarda fra sei mesi."""
    from datetime import datetime, timezone

    import pandas as pd

    from diffdb import __version__
    from diffdb.audit import _chi

    righe = [
        ("Generato da", f"DiFFDB {__version__}"),
        ("Generato il", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("Utente", _chi()),
        ("Ambiente 1", f"{diff.snapshot1.env_name} ({diff.snapshot1.dialect})"),
        ("Ambiente 2", f"{diff.snapshot2.env_name} ({diff.snapshot2.dialect})"),
        (f"Impronta {diff.snapshot1.env_name}", fingerprint(diff.snapshot1)),
        (f"Impronta {diff.snapshot2.env_name}", fingerprint(diff.snapshot2)),
        ("Differenze totali", len(diff.all)),
    ]
    return pd.DataFrame(righe, columns=["Voce", "Valore"])


def slug(text: str) -> str:
    """Nome di file sicuro. Gli ambienti possono contenere spazi e parentesi
    (es. 'PROD (baseline)'), che non devono diventare underscore doppi."""
    cleaned = "".join(c if c.isalnum() else "_" for c in text)
    return re.sub(r"_+", "_", cleaned).strip("_").lower() or "target"
