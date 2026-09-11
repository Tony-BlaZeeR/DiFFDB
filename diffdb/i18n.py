"""Lingua dell'interfaccia.

La lingua sorgente del progetto e' l'italiano: le stringhe nel codice sono gia'
in italiano, e i cataloghi (`diffdb/translations/diffdb_<lingua>.qm`) contengono le traduzioni
verso le altre. Per l'italiano quindi non serve nessun traduttore.

Serve pero' quello di Qt (`qtbase_it`): senza, i pulsanti dei dialog di sistema
restano in inglese dentro un'interfaccia italiana.
"""

import logging
from pathlib import Path

from diffdb import preferences
from diffdb.paths import resource_path
from diffdb.qt import QtCore

logger = logging.getLogger(__name__)

LINGUA_SORGENTE = "it"

# Riferimenti tenuti in vita: un QTranslator raccolto dal garbage collector
# smette silenziosamente di tradurre.
_traduttori = []


def lingua_effettiva() -> str:
    """La lingua da usare: quella scelta, o quella del sistema operativo."""
    scelta = preferences.lingua()
    if scelta != preferences.LINGUA_AUTOMATICA:
        return scelta
    return QtCore.QLocale.system().name().split("_")[0]


def installa(app) -> str:
    """Installa i traduttori sull'applicazione. Restituisce la lingua attiva."""
    codice = lingua_effettiva()

    _installa_qt(app, codice)

    if codice != LINGUA_SORGENTE:
        percorso = Path(resource_path("translations", f"diffdb_{codice}.qm"))
        if not _installa(app, str(percorso)):
            logger.warning("Traduzione '%s' non trovata in %s: resto in %s.",
                           codice, percorso, LINGUA_SORGENTE)
            return LINGUA_SORGENTE

    logger.info("Lingua dell'interfaccia: %s", codice)
    return codice


def _installa_qt(app, codice: str) -> None:
    """Traduzioni di Qt: i pulsanti dei dialog standard (Si'/No, Annulla...)."""
    cartella = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath)
    _installa(app, str(Path(cartella) / f"qtbase_{codice}.qm"))


def _installa(app, percorso: str) -> bool:
    traduttore = QtCore.QTranslator(app)
    if not traduttore.load(percorso):
        return False
    app.installTranslator(traduttore)
    _traduttori.append(traduttore)
    return True


def lingue_disponibili() -> dict:
    """Codice -> nome leggibile, per il selettore nell'interfaccia.

    Si elencano solo le lingue per cui esiste davvero un catalogo compilato,
    piu' l'italiano che e' la lingua sorgente.
    """
    disponibili = {
        preferences.LINGUA_AUTOMATICA: preferences.LINGUE[preferences.LINGUA_AUTOMATICA],
        LINGUA_SORGENTE: preferences.LINGUE[LINGUA_SORGENTE],
    }
    cartella = Path(resource_path("translations"))
    if cartella.is_dir():
        for catalogo in sorted(cartella.glob("diffdb_*.qm")):
            codice = catalogo.stem.removeprefix("diffdb_")
            disponibili[codice] = preferences.LINGUE.get(codice, codice)
    return disponibili
