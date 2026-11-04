"""Dialog "Informazioni": versione, link al progetto e controllo aggiornamenti.

Il controllo e' sempre su richiesta (pulsante), mai automatico, se non quando
l'utente accende l'opzione "all'avvio" - spenta di default. Vedi updates.py per
il perche': DiFFDB gira anche su reti chiuse.
"""

import logging

from diffdb import __version__, preferences
from diffdb.qt import QObject, Qt, QtCore, QtWidgets
from diffdb.updates import PAGINA_RELEASE, REPO, e_piu_recente
from diffdb.widgets import logo_pixmap
from diffdb.worker import UpdateCheckWorker

logger = logging.getLogger(__name__)


def mostra_info(parent):
    """Apre il dialog Info modale."""
    DialogoInfo(parent).esegui()


class DialogoInfo(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self.dialog = QtWidgets.QDialog(parent)
        self.dialog.setWindowTitle(self.tr("Informazioni su DiFFDB"))
        self.dialog.setMinimumWidth(420)
        self._costruisci()

    def esegui(self):
        self.dialog.exec()
        self._ferma_thread()

    # --- costruzione --------------------------------------------------------

    def _costruisci(self):
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        intestazione = QtWidgets.QHBoxLayout()
        logo = QtWidgets.QLabel()
        logo.setPixmap(logo_pixmap(56))
        intestazione.addWidget(logo)

        testo = QtWidgets.QVBoxLayout()
        testo.setSpacing(2)
        titolo = QtWidgets.QLabel("DiFFDB")
        titolo.setProperty("ruolo", "titolo")
        self.versione_label = QtWidgets.QLabel(self.tr("Versione {0}").format(__version__))
        self.versione_label.setProperty("ruolo", "sottotitolo")
        testo.addWidget(titolo)
        testo.addWidget(self.versione_label)
        intestazione.addLayout(testo)
        intestazione.addStretch()
        layout.addLayout(intestazione)

        descrizione = QtWidgets.QLabel(self.tr(
            "Confronta la struttura di due database e genera lo script di allineamento."))
        descrizione.setWordWrap(True)
        descrizione.setProperty("ruolo", "didascalia")
        layout.addWidget(descrizione)

        link = QtWidgets.QLabel(f'<a href="https://github.com/{REPO}">github.com/{REPO}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(link)

        layout.addSpacing(4)

        riga = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton(self.tr("Controlla aggiornamenti"))
        self.check_button.clicked.connect(self._controlla)
        riga.addWidget(self.check_button)
        riga.addStretch()
        layout.addLayout(riga)

        self.esito = QtWidgets.QLabel("")
        self.esito.setWordWrap(True)
        self.esito.setOpenExternalLinks(True)
        self.esito.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(self.esito)

        self.auto = QtWidgets.QCheckBox(self.tr("Controlla aggiornamenti all'avvio"))
        self.auto.setChecked(preferences.controlla_aggiornamenti_avvio())
        self.auto.setToolTip(self.tr(
            "Spento, DiFFDB non contatta mai la rete da solo. Acceso, all'avvio "
            "chiede a GitHub se c'e' una versione piu' nuova."))
        self.auto.toggled.connect(preferences.imposta_controlla_aggiornamenti_avvio)
        layout.addWidget(self.auto)

        pulsanti = QtWidgets.QHBoxLayout()
        pulsanti.addStretch()
        chiudi = QtWidgets.QPushButton(self.tr("Chiudi"))
        chiudi.setDefault(True)
        chiudi.clicked.connect(self.dialog.accept)
        pulsanti.addWidget(chiudi)
        layout.addLayout(pulsanti)

    # --- controllo aggiornamenti -------------------------------------------

    def _controlla(self):
        if self.thread is not None:
            return
        self.check_button.setEnabled(False)
        self.esito.setText(self.tr("Controllo in corso..."))

        self.thread = QtCore.QThread(self.dialog)
        self.worker = UpdateCheckWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._esito_ok)
        self.worker.failed.connect(self._esito_errore)
        self.thread.start()

    def _esito_ok(self, tag: str):
        if e_piu_recente(tag):
            self.esito.setText(
                self.tr("Disponibile la versione {0}.").format(tag)
                + f' <a href="{PAGINA_RELEASE}">' + self.tr("Scarica") + "</a>")
        else:
            self.esito.setText(self.tr("Hai gia' l'ultima versione."))
        self._ferma_thread()

    def _esito_errore(self, _messaggio: str):
        self.esito.setText(self.tr("Impossibile controllare ora (rete non raggiungibile?)."))
        self._ferma_thread()

    def _ferma_thread(self):
        self.check_button.setEnabled(True)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.worker = None
