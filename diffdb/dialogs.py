"""Dialog di inserimento e modifica di una connessione.

E' una classe e non un insieme di funzioni per due motivi: il test della
connessione ha bisogno di tenersi un thread, e `self.tr()` e' la forma che gli
strumenti di traduzione di Qt sanno riconoscere.
"""

import logging

from diffdb import keystore
from diffdb.connections import Connection, con_riferimento_al_portachiavi
from diffdb.paths import resource_path
from diffdb.qt import QObject, QtCore, QtWidgets, load_ui
from diffdb.urls import password_letterale
from diffdb.worker import TestConnectionWorker

logger = logging.getLogger(__name__)


def ask_connection(parent, connection: Connection | None = None) -> Connection | None:
    """Apre il dialog e restituisce la connessione, o None se l'utente annulla."""
    return DialogoConnessione(parent, connection).chiedi()


class DialogoConnessione(QObject):
    def __init__(self, parent, connection: Connection | None = None):
        super().__init__(parent)
        self.connection = connection
        self.editing = connection is not None
        self.thread = None
        self.worker = None

        nome_ui = "edit_connection.ui" if self.editing else "add_connection.ui"
        self.dialog = load_ui(resource_path("ui", nome_ui), parent)

        pulsante = self.dialog.edit_button if self.editing else self.dialog.add_button
        pulsante.clicked.connect(self.dialog.accept)

        if self.editing:
            self.dialog.conn_name_input.setText(connection.name)
            self.dialog.conn_string_input.setText(connection.conn_string)
            self.dialog.schema_input.setText(connection.schema or "")

        self._costruisci_strumenti()

    # --- ciclo del dialog --------------------------------------------------

    def chiedi(self) -> Connection | None:
        while self.dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            connessione = self._connessione()
            if connessione.name and connessione.conn_string:
                self._avvisa_se_in_chiaro(connessione)
                return connessione

            QtWidgets.QMessageBox.warning(
                self.dialog, self.tr("Dati mancanti"),
                self.tr("Nome e stringa di connessione sono obbligatori."))
            self._aggiorna_stato()

        self._ferma_thread()
        return None

    def _connessione(self) -> Connection:
        return Connection(
            name=self.dialog.conn_name_input.text().strip(),
            conn_string=self.dialog.conn_string_input.text().strip(),
            schema=self.dialog.schema_input.text().strip() or None,
        )

    # --- riga degli strumenti ----------------------------------------------

    def _costruisci_strumenti(self):
        """Test della connessione e portachiavi.

        Stanno qui e non nel file .ui perche' dipendono dalla macchina: il
        portachiavi non c'e' dappertutto, e il test ha bisogno di un thread.
        """
        layout = self.dialog.verticalLayout

        self.stato = QtWidgets.QLabel(self.dialog)
        self.stato.setObjectName("connStatus")
        self.stato.setWordWrap(True)

        self.prova = QtWidgets.QPushButton(self.tr("Testa connessione"), self.dialog)
        self.prova.setToolTip(self.tr("Si collega davvero al database e dice cosa ha trovato."))
        self.prova.clicked.connect(self._testa)

        self.portachiavi = QtWidgets.QPushButton(
            self.tr("Password nel portachiavi..."), self.dialog)
        self.portachiavi.clicked.connect(self._imposta_password)

        riga = QtWidgets.QHBoxLayout()
        riga.addWidget(self.prova)
        riga.addWidget(self.portachiavi)

        self.dialog.conn_name_input.textChanged.connect(lambda _: self._aggiorna_stato())

        layout.insertWidget(layout.count() - 1, self.stato)
        layout.insertLayout(layout.count() - 1, riga)
        self._aggiorna_stato()

    def _aggiorna_stato(self):
        nome = self.dialog.conn_name_input.text().strip()
        if not keystore.disponibile():
            self.portachiavi.setEnabled(False)
            self.portachiavi.setToolTip(self.tr(
                "Portachiavi non disponibile ({0}): usa una variabile d'ambiente."
            ).format(keystore.descrizione()))
            return

        self.portachiavi.setToolTip(self.tr(
            "Salva la password nel portachiavi del sistema operativo. "
            "Nel file resta solo il segnaposto ${keyring}."))
        if nome and keystore.leggi(nome) is not None:
            self.stato.setText(
                self.tr("Password di '{0}' presente nel portachiavi.").format(nome))

    # --- test della connessione --------------------------------------------

    def _testa(self):
        connessione = self._connessione()
        if not connessione.conn_string:
            self.stato.setText(self.tr("Scrivi prima la stringa di connessione."))
            return
        if self.thread is not None:
            return

        self.prova.setEnabled(False)
        self.stato.setText(self.tr("Connessione in corso..."))

        self.thread = QtCore.QThread(self)
        self.worker = TestConnectionWorker(connessione)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._mostra_esito)
        self.worker.failed.connect(self._mostra_errore)
        self.thread.start()

    def _mostra_esito(self, esito):
        """Il messaggio si compone qui: il core non sa in che lingua parlare."""
        messaggio = self.tr("Connessione riuscita: {0} {1}, {2} tabelle visibili.").format(
            esito.dialetto, esito.versione, esito.tabelle)

        if esito.schema_trovato is False:
            messaggio += " " + self.tr("Attenzione: lo schema '{0}' non esiste.").format(
                esito.schema)
        elif esito.schema_trovato and esito.tabelle == 0:
            messaggio += " " + self.tr("Lo schema '{0}' esiste ma e' vuoto.").format(esito.schema)

        self.stato.setText(messaggio)
        self._ferma_thread()

    def _mostra_errore(self, messaggio: str):
        self.stato.setText(self.tr("Connessione fallita: {0}").format(messaggio))
        self._ferma_thread()

    def _ferma_thread(self):
        self.prova.setEnabled(True)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.worker = None

    # --- portachiavi --------------------------------------------------------

    def _imposta_password(self):
        nome = self.dialog.conn_name_input.text().strip()
        if not nome:
            QtWidgets.QMessageBox.warning(
                self.dialog, self.tr("Nome mancante"),
                self.tr("Dai un nome alla connessione: identifica la voce nel portachiavi."))
            return

        password, ok = QtWidgets.QInputDialog.getText(
            self.dialog, self.tr("Password nel portachiavi"),
            self.tr("Password per '{0}':").format(nome),
            QtWidgets.QLineEdit.EchoMode.Password)
        if not ok or not password:
            return

        try:
            keystore.scrivi(nome, password)
        except keystore.KeystoreNonDisponibile as exc:
            QtWidgets.QMessageBox.critical(self.dialog, self.tr("Portachiavi"), str(exc))
            return

        self.dialog.conn_string_input.setText(
            con_riferimento_al_portachiavi(self.dialog.conn_string_input.text().strip()))
        self.stato.setText(self.tr("Password di '{0}' salvata nel portachiavi.").format(nome))

    # --- avvisi -------------------------------------------------------------

    def _avvisa_se_in_chiaro(self, connessione: Connection) -> None:
        """Ultimo avviso prima di scrivere una password in chiaro sul disco."""
        if password_letterale(connessione.conn_string) is None:
            return
        QtWidgets.QMessageBox.warning(
            self.dialog, self.tr("Password in chiaro"),
            self.tr("La connessione '{0}' verra' salvata con la password scritta nel file.\n\n"
                    "Per evitarlo usa il pulsante 'Password nel portachiavi', oppure scrivi "
                    "${keyring} o ${VARIABILE} al posto della password.").format(connessione.name))
