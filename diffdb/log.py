"""Configurazione del logging.

Due cose che mancavano:

- **un file**. `logging.basicConfig` scrive su stderr, che dentro un eseguibile
  GUI significa nel nulla: al primo problema in produzione non c'e' niente da
  guardare. Il file sta accanto alla configurazione, con rotazione.
- **la sanificazione**. I driver mettono l'URL completo, password inclusa, nei
  messaggi d'errore e nei traceback. Un segreto custodito bene e poi finito in
  un log e' un segreto perso.

La sanificazione e' nel formatter e non in un filtro perche' cosi' passa anche
il traceback delle eccezioni, non solo il messaggio.
"""

import logging
import logging.handlers
from pathlib import Path

from diffdb.urls import sanitize

NOME_FILE = "diffdb.log"
BYTE_MASSIMI = 2 * 1024 * 1024
COPIE = 3

FORMATO_FILE = "%(asctime)s %(levelname)s %(name)s: %(message)s"
FORMATO_CONSOLE = "%(message)s"


class FormatterSanificante(logging.Formatter):
    """Maschera le connection string in tutto quello che viene scritto."""

    def format(self, record: logging.LogRecord) -> str:
        return sanitize(super().format(record))


def configure(level=logging.INFO, su_file: bool = True,
              formato_console: str = FORMATO_CONSOLE) -> Path | None:
    """Prepara console e file di log. Restituisce il percorso del file, se c'e'."""
    root = logging.getLogger()
    root.setLevel(level)
    for vecchio in list(root.handlers):
        root.removeHandler(vecchio)

    console = logging.StreamHandler()
    console.setFormatter(FormatterSanificante(formato_console))
    root.addHandler(console)

    if not su_file:
        return None

    try:
        from diffdb.paths import config_dir

        percorso = config_dir() / NOME_FILE
        file_handler = logging.handlers.RotatingFileHandler(
            percorso, maxBytes=BYTE_MASSIMI, backupCount=COPIE, encoding="utf-8")
        file_handler.setFormatter(FormatterSanificante(FORMATO_FILE))
        root.addHandler(file_handler)
        return percorso
    except OSError as exc:  # cartella non scrivibile: meglio senza file che senza avvio
        root.warning("File di log non disponibile: %s", exc)
        return None
