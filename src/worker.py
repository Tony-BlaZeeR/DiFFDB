"""Confronto eseguito fuori dal thread della GUI, che altrimenti si congela."""

import logging

from src.diff_DB import compare_environments
from src.qt import QObject, Signal

logger = logging.getLogger(__name__)


class CompareWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)   # DiffResult
    failed = Signal(str)

    def __init__(self, conn1, conn2):
        super().__init__()
        self.conn1 = conn1      # src.connections.Connection
        self.conn2 = conn2

    def run(self):
        try:
            self.progress.emit(
                f"Lettura della struttura di {self.conn1.name} e {self.conn2.name}..."
            )
            diff = compare_environments(
                self.conn1.name, self.conn1.conn_string,
                self.conn2.name, self.conn2.conn_string,
                self.conn1.schema, self.conn2.schema,
            )
            self.finished.emit(diff)
        except Exception as exc:  # URL malformati, driver mancanti, timeout, permessi
            logger.exception("Confronto fallito")
            self.failed.emit(str(exc))
