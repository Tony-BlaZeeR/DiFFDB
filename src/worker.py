"""Confronto eseguito fuori dal thread della GUI, che altrimenti si congela."""

import logging

from PyQt5.QtCore import QObject, pyqtSignal

from src.diff_DB import compare_environments

logger = logging.getLogger(__name__)


class CompareWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)   # DiffResult
    failed = pyqtSignal(str)

    def __init__(self, env1, conn_str1, env2, conn_str2, schema1=None, schema2=None):
        super().__init__()
        self.env1, self.conn_str1 = env1, conn_str1
        self.env2, self.conn_str2 = env2, conn_str2
        self.schema1, self.schema2 = schema1, schema2

    def run(self):
        try:
            self.progress.emit(f"Lettura della struttura di {self.env1} e {self.env2}...")
            diff = compare_environments(
                self.env1, self.conn_str1, self.env2, self.conn_str2,
                self.schema1, self.schema2,
            )
            self.finished.emit(diff)
        except Exception as exc:  # anche URL malformati, driver mancanti, timeout
            logger.exception("Confronto fallito")
            self.failed.emit(str(exc))
