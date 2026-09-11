"""Lavoro lento eseguito fuori dal thread della GUI, che altrimenti si congela.

Ogni worker segue lo stesso contratto: `run()` non solleva mai, ed emette
`finished` con il risultato oppure `failed` con il messaggio d'errore.
"""

import logging

from diffdb.qt import QObject, Signal
from diffdb.rules import NESSUNA
from diffdb.schema_snapshot import Annullabile, verifica_connessione
from diffdb.snapshot_io import compare_sources, save, snapshot_of, source_name
from diffdb.urls import sanitize

logger = logging.getLogger(__name__)


class CompareWorker(QObject):
    """Confronta due sorgenti (connessione dal vivo o snapshot da file)."""

    progress = Signal(str)
    finished = Signal(object)   # DiffResult
    failed = Signal(str)
    annullato = Signal()

    def __init__(self, source1, source2, regole=NESSUNA):
        super().__init__()
        self.source1 = source1
        self.source2 = source2
        self.regole = regole
        self.annullabile = Annullabile()

    def annulla(self):
        """Chiude le connessioni: la lettura in corso fallisce e il thread esce."""
        self.annullabile.annulla()

    def run(self):
        try:
            self.progress.emit(
                f"Lettura della struttura di {source_name(self.source1)} "
                f"e {source_name(self.source2)}..."
            )
            diff = compare_sources(self.source1, self.source2, self.regole, self.annullabile)
        except Exception as exc:  # URL malformati, driver mancanti, timeout, permessi
            if self.annullabile.annullato:
                # L'errore e' la conseguenza dell'annullamento, non un guasto.
                self.annullato.emit()
                return
            logger.exception("Confronto fallito")
            self.failed.emit(sanitize(str(exc)))
            return

        if self.annullabile.annullato:
            self.annullato.emit()
        else:
            self.finished.emit(diff)


class TestConnectionWorker(QObject):
    """Prova una connessione senza bloccare la finestra.

    Un host irraggiungibile impiega decine di secondi ad arrendersi: farlo sul
    thread della GUI congelerebbe il dialog.
    """

    progress = Signal(str)
    finished = Signal(object)   # EsitoConnessione
    failed = Signal(str)

    def __init__(self, connection):
        super().__init__()
        self.connection = connection

    def run(self):
        try:
            self.finished.emit(verifica_connessione(
                self.connection.name, self.connection.conn_string, self.connection.schema))
        except Exception as exc:
            logger.info("Test della connessione '%s' fallito", self.connection.name)
            self.failed.emit(sanitize(str(exc)))


class SnapshotWorker(QObject):
    """Fotografa un ambiente e ne salva lo snapshot su file."""

    progress = Signal(str)
    finished = Signal(object)   # percorso scritto
    failed = Signal(str)

    def __init__(self, source, path, regole=NESSUNA):
        super().__init__()
        self.source = source
        self.path = path
        self.regole = regole
        self.annullabile = Annullabile()

    def annulla(self):
        self.annullabile.annulla()

    def run(self):
        try:
            self.progress.emit(f"Lettura della struttura di {source_name(self.source)}...")
            snapshot = snapshot_of(self.source, self.regole, self.annullabile)
            origin = getattr(self.source, "conn_string", None)
            self.finished.emit(str(save(snapshot, self.path, source=origin)))
        except Exception as exc:
            logger.exception("Salvataggio dello snapshot fallito")
            self.failed.emit(sanitize(str(exc)))
