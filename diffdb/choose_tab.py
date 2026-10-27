"""Scheda della scelta: quali due ambienti confrontare, e in che verso.

La schermata deve rispondere a tre domande prima che si prema qualcosa:
*quali* due ambienti, in *che direzione*, e *cosa sono davvero* (dialetto, host,
schema). Scambiare collaudo con produzione e' un clic, e il solo nome della
connessione non basta a impedirlo.

La disposizione e' orizzontale — riferimento a sinistra, ambiente da allineare a
destra — perche' e' il verso in cui si legge la direzione del confronto.
"""

import logging

from diffdb.connections import Connection
from diffdb.qt import Qt, QtGui, QtWidgets, Signal
from diffdb.urls import descrizione
from diffdb.widgets import Riquadro

logger = logging.getLogger(__name__)


class ChooseTab(QtWidgets.QWidget):
    confronta = Signal()
    salva_snapshot = Signal()
    confronta_con_file = Signal()
    annulla_operazione = Signal()
    riprova = Signal()
    modifica_connessione = Signal()

    # Indici delle pagine impilate.
    PAGINA_SCELTA, PAGINA_AVANZAMENTO, PAGINA_ERRORE = range(3)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connessioni: list[Connection] = []
        self._costruisci()

    # --- costruzione --------------------------------------------------------

    def _costruisci(self):
        radice = QtWidgets.QVBoxLayout(self)
        radice.setContentsMargins(0, 0, 0, 0)
        self._stack = QtWidgets.QStackedWidget()
        radice.addWidget(self._stack)

        self._stack.addWidget(self._pagina_scelta())
        self._stack.addWidget(self._pagina_avanzamento())
        self._stack.addWidget(self._pagina_errore())

        self._scorciatoie()
        # L'ordine di tabulazione segue la lettura: riferimento, inverti,
        # ambiente da allineare, confronta.
        for prima, dopo in ((self.comboBox1, self.swap_button),
                            (self.swap_button, self.comboBox2),
                            (self.comboBox2, self.compare_button),
                            (self.compare_button, self.save_snapshot_button),
                            (self.save_snapshot_button, self.compare_file_button)):
            QtWidgets.QWidget.setTabOrder(prima, dopo)

    def _pagina_scelta(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(pagina)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)

        titolo = QtWidgets.QLabel(self.tr("Confronta la struttura di due ambienti"))
        titolo.setProperty("ruolo", "titolo")
        layout.addWidget(titolo)

        layout.addWidget(self._riquadro_ambienti())

        self.compare_button = QtWidgets.QPushButton(self.tr("Confronta"))
        self.compare_button.setProperty("ruolo", "primario")
        self.compare_button.setMinimumWidth(220)
        self.compare_button.setDefault(True)   # Invio lo aziona
        self.compare_button.clicked.connect(self.confronta)

        # Compare solo mentre si sta leggendo: un pulsante Annulla sempre spento
        # e' rumore, e finora non c'era modo di fermare un confronto partito.
        self.cancel_button = QtWidgets.QPushButton(self.tr("Annulla"))
        self.cancel_button.clicked.connect(self.annulla_operazione)
        self.cancel_button.setVisible(False)

        riga_azione = QtWidgets.QHBoxLayout()
        riga_azione.addStretch()
        riga_azione.addWidget(self.compare_button)
        riga_azione.addWidget(self.cancel_button)
        riga_azione.addStretch()
        layout.addLayout(riga_azione)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setProperty("ruolo", "sottotitolo")
        layout.addWidget(self.status_label)

        # Lo spazio in eccesso si accumula qui: sopra resta tutto compatto
        # invece di galleggiare al centro della finestra.
        layout.addStretch()

        layout.addWidget(self._separatore())
        layout.addLayout(self._riga_snapshot())
        return pagina

    # --- pagina Avanzamento -------------------------------------------------

    def _pagina_avanzamento(self) -> QtWidgets.QWidget:
        """Mostrata mentre il confronto gira: titolo, barra e testo di stato."""
        pagina = QtWidgets.QWidget()
        esterno = QtWidgets.QVBoxLayout(pagina)
        esterno.addStretch()

        card = Riquadro()
        card.setMaximumWidth(560)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        titolo = QtWidgets.QLabel(self.tr("Confronto in corso"))
        titolo.setProperty("ruolo", "titolo")
        layout.addWidget(titolo)

        self.avanz_bar = QtWidgets.QProgressBar()
        self.avanz_bar.setRange(0, 0)        # indeterminata: non sappiamo quanti oggetti
        self.avanz_bar.setTextVisible(False)
        self.avanz_bar.setFixedHeight(6)
        layout.addWidget(self.avanz_bar)

        self.avanz_label = QtWidgets.QLabel("")
        self.avanz_label.setProperty("ruolo", "sottotitolo")
        self.avanz_label.setWordWrap(True)
        layout.addWidget(self.avanz_label)

        riga = QtWidgets.QHBoxLayout()
        riga.addStretch()
        annulla = QtWidgets.QPushButton(self.tr("Annulla"))
        annulla.clicked.connect(self.annulla_operazione)
        riga.addWidget(annulla)
        layout.addLayout(riga)

        riga_card = QtWidgets.QHBoxLayout()
        riga_card.addStretch()
        riga_card.addWidget(card)
        riga_card.addStretch()
        esterno.addLayout(riga_card)
        esterno.addStretch()
        return pagina

    # --- pagina Errore ------------------------------------------------------

    def _pagina_errore(self) -> QtWidgets.QWidget:
        """Mostrata quando il confronto fallisce: messaggio e azioni di recupero."""
        pagina = QtWidgets.QWidget()
        esterno = QtWidgets.QVBoxLayout(pagina)
        esterno.addStretch()

        card = Riquadro()
        card.setObjectName("ErrorCard")
        card.setMaximumWidth(560)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        titolo = QtWidgets.QLabel(self.tr("Impossibile completare il confronto"))
        titolo.setProperty("ruolo", "titolo")
        layout.addWidget(titolo)

        self.err_messaggio = QtWidgets.QLabel("")
        self.err_messaggio.setWordWrap(True)
        self.err_messaggio.setProperty("pastiglia", "allarme")
        layout.addWidget(self.err_messaggio)

        riga = QtWidgets.QHBoxLayout()
        torna = QtWidgets.QPushButton(self.tr("Torna alla scelta"))
        torna.clicked.connect(self.mostra_scelta)
        modifica = QtWidgets.QPushButton(self.tr("Modifica connessione"))
        modifica.clicked.connect(self.modifica_connessione)
        riprova = QtWidgets.QPushButton(self.tr("Riprova"))
        riprova.setProperty("ruolo", "primario")
        riprova.clicked.connect(self.riprova)
        riga.addWidget(torna)
        riga.addStretch()
        riga.addWidget(modifica)
        riga.addWidget(riprova)
        layout.addLayout(riga)

        riga_card = QtWidgets.QHBoxLayout()
        riga_card.addStretch()
        riga_card.addWidget(card)
        riga_card.addStretch()
        esterno.addLayout(riga_card)
        esterno.addStretch()
        return pagina

    # --- cambio pagina ------------------------------------------------------

    def mostra_scelta(self):
        self._stack.setCurrentIndex(self.PAGINA_SCELTA)

    def mostra_avanzamento(self, testo: str = ""):
        self.avanz_label.setText(testo or self.tr("Lettura della struttura in corso..."))
        self._stack.setCurrentIndex(self.PAGINA_AVANZAMENTO)

    def avanza(self, testo: str):
        """Aggiorna sia lo stato compatto sia la pagina di avanzamento."""
        self.status_label.setText(testo)
        self.avanz_label.setText(testo)

    def mostra_errore(self, messaggio: str):
        self.err_messaggio.setText(messaggio)
        self._stack.setCurrentIndex(self.PAGINA_ERRORE)

    def _scorciatoie(self):
        for sequenza, azione in (("Ctrl+Return", self._confronta_se_pronto),
                                 ("Ctrl+Enter", self._confronta_se_pronto),
                                 ("Ctrl+I", self.inverti)):
            scorciatoia = QtGui.QShortcut(QtGui.QKeySequence(sequenza), self)
            scorciatoia.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            scorciatoia.activated.connect(azione)

    def _confronta_se_pronto(self):
        if self.compare_button.isEnabled():
            self.confronta.emit()

    def _riquadro_ambienti(self) -> QtWidgets.QFrame:
        riquadro = Riquadro(self.tr("Ambienti"))
        griglia = QtWidgets.QGridLayout(riquadro)
        griglia.setContentsMargins(18, 16, 18, 16)
        griglia.setHorizontalSpacing(18)
        griglia.setVerticalSpacing(6)

        etichetta1 = QtWidgets.QLabel(self.tr("Riferimento"))
        etichetta2 = QtWidgets.QLabel(self.tr("Da allineare"))
        for etichetta in (etichetta1, etichetta2):
            etichetta.setProperty("ruolo", "didascalia")

        self.comboBox1 = QtWidgets.QComboBox()
        self.comboBox2 = QtWidgets.QComboBox()
        for combo in (self.comboBox1, self.comboBox2):
            combo.setMinimumWidth(200)
            combo.currentIndexChanged.connect(self._aggiorna)

        self.swap_button = QtWidgets.QPushButton("⇄")
        self.swap_button.setToolTip(self.tr("Inverti la direzione del confronto") + " (Ctrl+I)")
        # Il simbolo da solo non e' un nome: un lettore di schermo direbbe
        # "pulsante freccia" o niente.
        self.swap_button.setAccessibleName(self.tr("Inverti la direzione del confronto"))
        self.swap_button.setFixedWidth(38)
        self.swap_button.clicked.connect(self.inverti)

        self.dettaglio1 = QtWidgets.QLabel("")
        self.dettaglio2 = QtWidgets.QLabel("")
        for dettaglio in (self.dettaglio1, self.dettaglio2):
            dettaglio.setProperty("ruolo", "didascalia")
            dettaglio.setWordWrap(True)

        griglia.addWidget(etichetta1, 0, 0)
        griglia.addWidget(etichetta2, 0, 2)
        griglia.addWidget(self.comboBox1, 1, 0)
        griglia.addWidget(self.swap_button, 1, 1)
        griglia.addWidget(self.comboBox2, 1, 2)
        griglia.addWidget(self.dettaglio1, 2, 0)
        griglia.addWidget(self.dettaglio2, 2, 2)
        griglia.setColumnStretch(0, 1)
        griglia.setColumnStretch(2, 1)
        return riquadro

    def _riga_snapshot(self) -> QtWidgets.QHBoxLayout:
        riga = QtWidgets.QHBoxLayout()
        etichetta = QtWidgets.QLabel(self.tr("Snapshot:"))
        etichetta.setProperty("ruolo", "didascalia")

        self.save_snapshot_button = QtWidgets.QPushButton(self.tr("Salva su file..."))
        self.save_snapshot_button.setToolTip(self.tr(
            "Salva la struttura dell'ambiente di riferimento su file, "
            "per confrontarla piu' avanti."))
        self.save_snapshot_button.clicked.connect(self.salva_snapshot)

        self.compare_file_button = QtWidgets.QPushButton(self.tr("Confronta con un file..."))
        self.compare_file_button.setToolTip(self.tr(
            "Confronta l'ambiente da allineare con uno snapshot salvato in precedenza."))
        self.compare_file_button.clicked.connect(self.confronta_con_file)

        riga.addWidget(etichetta)
        riga.addWidget(self.save_snapshot_button)
        riga.addWidget(self.compare_file_button)
        riga.addStretch()
        return riga

    def _separatore(self) -> QtWidgets.QFrame:
        linea = QtWidgets.QFrame()
        linea.setProperty("ruolo", "separatore")
        linea.setFixedHeight(1)
        return linea

    # --- dati ---------------------------------------------------------------

    def imposta_connessioni(self, connessioni: list[Connection]):
        """Riempie le tendine, conservando la scelta dell'utente se ancora valida."""
        self._connessioni = list(connessioni)
        precedenti = [self.comboBox1.currentData(), self.comboBox2.currentData()]

        for combo in (self.comboBox1, self.comboBox2):
            combo.blockSignals(True)
            combo.clear()
            for connessione in self._connessioni:
                combo.addItem(connessione.name, connessione.name)

        for combo, precedente, predefinito in zip(
                (self.comboBox1, self.comboBox2), precedenti, (0, 1), strict=True):
            indice = combo.findData(precedente) if precedente else -1
            if indice < 0:
                # Due ambienti diversi: partire con lo stesso da entrambe le parti
                # significa aprire l'applicazione in uno stato non valido.
                indice = min(predefinito, combo.count() - 1)
            combo.setCurrentIndex(indice)
            combo.blockSignals(False)

        self._aggiorna()

    def selezionate(self) -> tuple[Connection | None, Connection | None]:
        per_nome = {c.name: c for c in self._connessioni}
        return (per_nome.get(self.comboBox1.currentData()),
                per_nome.get(self.comboBox2.currentData()))

    def inverti(self):
        """Scambia riferimento e ambiente da allineare."""
        primo, secondo = self.comboBox1.currentIndex(), self.comboBox2.currentIndex()
        for combo, indice in ((self.comboBox1, secondo), (self.comboBox2, primo)):
            combo.blockSignals(True)
            combo.setCurrentIndex(indice)
            combo.blockSignals(False)
        self._aggiorna()

    # --- stato --------------------------------------------------------------

    def _aggiorna(self):
        conn1, conn2 = self.selezionate()
        for dettaglio, connessione in ((self.dettaglio1, conn1), (self.dettaglio2, conn2)):
            dettaglio.setText(
                descrizione(connessione.conn_string, connessione.schema) if connessione else "")

        pronto = conn1 is not None and conn2 is not None and conn1.name != conn2.name
        self.compare_button.setEnabled(pronto)

        if conn1 and conn2 and conn1.name == conn2.name:
            self.compare_button.setText(self.tr("Confronta"))
            self.status_label.setText(self.tr("Sono lo stesso ambiente: scegline due diversi."))
        elif pronto:
            self.compare_button.setText(self.tr("Confronta {0} con {1}").format(
                conn1.name, conn2.name))
            self.status_label.setText("")
        else:
            self.compare_button.setText(self.tr("Confronta"))
            self.status_label.setText(self.tr(
                "Configura almeno due connessioni nella scheda Configurazione."))

    def imposta_stato(self, testo: str):
        self.status_label.setText(testo)

    def imposta_occupato(self, occupato: bool):
        for pulsante in (self.compare_button, self.save_snapshot_button,
                         self.compare_file_button, self.swap_button):
            pulsante.setEnabled(not occupato)
        self.cancel_button.setVisible(occupato)
        if not occupato:
            self._aggiorna()
