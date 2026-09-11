"""Intestazione di tracciabilita' degli script generati.

Lo script `.sql` che DiFFDB produce e' un *change* che finira' in produzione.
Fra sei mesi, con quel file in mano, si deve poter rispondere a: chi l'ha
generato, quando, confrontando cosa con cosa, e con quale versione di DiFFDB.

Quest'ultima e' la ragione meno ovvia e la piu' importante: quando esce una
correzione al generatore, senza la versione nell'intestazione non si sa quali
script prodotti in passato ne siano affetti, e si finisce per sospettare di tutti.

L'impronta degli ambienti rende lo script **verificabile prima di eseguirlo**:
se lo schema e' cambiato dopo la generazione, `--verify` se ne accorge.
"""

import getpass
import json
import logging
import platform
import re
from datetime import datetime, timezone
from pathlib import Path

from diffdb import __version__
from diffdb.diff_DB import DiffResult
from diffdb.snapshot_io import fingerprint
from diffdb.urls import mask_password

logger = logging.getLogger(__name__)

# Riga a lettura automatica: l'intestazione leggibile puo' cambiare forma senza
# rompere --verify. JSON perche' i nomi degli ambienti contengono spazi.
PREFISSO_META = "-- diffdb-meta: "
_RIGA_META = re.compile(r"^--\s*diffdb-meta:\s*(\{.*\})\s*$", re.MULTILINE)


def intestazione(diff: DiffResult, target_env: str, origine: str | None = None,
                 incluse: int | None = None, totali: int | None = None) -> str:
    """Le righe di commento in cima allo script di allineamento."""
    target = diff.snapshot_of(target_env)
    sorgente = diff.other_than(target_env)

    meta = {
        "versione_diffdb": __version__,
        "generato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generato_da": _chi(),
        "target": target.env_name,
        "impronta_target": fingerprint(target),
        "sorgente": sorgente.env_name,
        "impronta_sorgente": fingerprint(sorgente),
    }
    if origine:
        meta["origine_target"] = mask_password(origine)

    regole = diff.regole
    if not regole.vuote:
        # Chi legge lo script deve sapere che non e' stato guardato tutto.
        meta["filtri"] = regole.firma()
        meta["differenze_accettate"] = diff.accettate

    righe = [
        f"-- DiFFDB {__version__} - script di allineamento",
        f"-- Ambiente da allineare : {target.env_name} ({target.dialect}"
        + (f", schema {target.schema}" if target.schema else "") + ")",
        f"-- Allineato a           : {sorgente.env_name}",
        f"-- Generato il           : {meta['generato']}",
        f"-- Generato da           : {meta['generato_da']}",
        f"-- Impronta di {sorgente.env_name} : {meta['impronta_sorgente']}",
        f"-- Impronta di {target.env_name} : {meta['impronta_target']}",
    ]
    if incluse is not None and totali is not None and incluse != totali:
        righe.append(f"-- Differenze incluse    : {incluse} di {totali} (export selettivo)")
    if not regole.vuote:
        righe.append(f"-- Regole applicate      : {regole.descrizione()}")
        if diff.accettate:
            righe.append(
                f"-- Differenze accettate  : {diff.accettate}, non incluse in questo script")

    righe += [
        "--",
        "-- Verifica che l'ambiente non sia cambiato dopo la generazione:",
        f'--   python -m diffdb.cli --verify <questo file> "{target.env_name}"',
        "-- DiFFDB propone, non applica: rileggere prima di eseguire in produzione.",
        PREFISSO_META + json.dumps(meta, ensure_ascii=False, sort_keys=True),
        "",
    ]
    return "\n".join(righe)


def leggi_meta(percorso) -> dict:
    """Rilegge i dati di tracciabilita' da uno script generato."""
    testo = Path(percorso).read_text(encoding="utf-8")
    trovato = _RIGA_META.search(testo)
    if not trovato:
        raise ValueError(
            f"{percorso}: manca la riga 'diffdb-meta'. "
            f"Lo script e' stato generato da una versione di DiFFDB precedente alla 1.2, "
            f"o modificato a mano."
        )
    try:
        return json.loads(trovato.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{percorso}: riga 'diffdb-meta' illeggibile ({exc})") from exc


def _chi() -> str:
    """Utente e macchina, per rispondere alla domanda che fa sempre l'auditor."""
    try:
        utente = getpass.getuser()
    except Exception:  # pragma: no cover - ambienti senza utente definito
        utente = "sconosciuto"
    return f"{utente}@{platform.node() or 'sconosciuto'}"
