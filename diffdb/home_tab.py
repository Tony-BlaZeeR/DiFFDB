"""Schermata iniziale.

Prima era un titolo, una frase e il logo in mezzo al vuoto: occupava il primo
posto nella navigazione senza dire niente. Ora risponde alle domande che ci si
fa aprendo l'applicazione — cos'ho confrontato l'ultima volta, come stanno le
mie connessioni, da dove ricomincio — e ogni riga porta a un'azione.
"""

import logging

from diffdb.connections import Connection, usa_portachiavi
from diffdb.paths import resource_path
from diffdb.qt import Qt, QtCore, QtGui, QtWidgets, Signal
from diffdb.urls import password_letterale

logger = logging.getLogger(__name__)


class HomeTab(QtWidgets.QWidget):
    vai_al_confronto = Signal()
    vai_alle_connessioni = Signal()
    ripeti_confronto = Signal(str, str)   # riferimento, da allineare

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ultimo = None
        self._costruisci()

    def _costruisci(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addLayout(self._intestazione())
        layout.addWidget(self._riquadro_ultimo_confronto())
        layout.addWidget(self._riquadro_connessioni())
        layout.addStretch()
        layout.addLayout(self._azioni())

    def _intestazione(self) -> QtWidgets.QHBoxLayout:
        riga = QtWidgets.QHBoxLayout()
        riga.setSpacing(14)

        logo = QtWidgets.QLabel()
        logo.setPixmap(QtGui.QPixmap(resource_path("images", "logo.png")).scaled(
            56, 56, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

        testi = QtWidgets.QVBoxLayout()
        testi.setSpacing(2)
        titolo = QtWidgets.QLabel("DiFFDB")
        titolo.setProperty("ruolo", "titolo")
        sottotitolo = QtWidgets.QLabel(self.tr(
            "Confronta la struttura di due database e genera lo script per allinearli."))
        sottotitolo.setProperty("ruolo", "sottotitolo")
        # Senza questo la frase veniva tagliata dal bordo della finestra.
        sottotitolo.setWordWrap(True)
        testi.addWidget(titolo)
        testi.addWidget(sottotitolo)

        riga.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        riga.addLayout(testi, 1)
        return riga

    def _riquadro_ultimo_confronto(self) -> QtWidgets.QFrame:
        self.riquadro_ultimo = QtWidgets.QFrame()
        self.riquadro_ultimo.setProperty("ruolo", "riquadro")
        layout = QtWidgets.QVBoxLayout(self.riquadro_ultimo)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        intestazione = QtWidgets.QLabel(self.tr("Ultimo confronto"))
        intestazione.setProperty("ruolo", "didascalia")

        self.ultimo_ambienti = QtWidgets.QLabel("")
        self.ultimo_dettaglio = QtWidgets.QLabel("")
        self.ultimo_dettaglio.setProperty("ruolo", "didascalia")

        self.ripeti_button = QtWidgets.QPushButton(self.tr("Ripeti"))
        self.ripeti_button.clicked.connect(self._ripeti)

        riga = QtWidgets.QHBoxLayout()
        colonna = QtWidgets.QVBoxLayout()
        colonna.setSpacing(2)
        colonna.addWidget(self.ultimo_ambienti)
        colonna.addWidget(self.ultimo_dettaglio)
        riga.addLayout(colonna, 1)
        riga.addWidget(self.ripeti_button, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(intestazione)
        layout.addLayout(riga)
        return self.riquadro_ultimo

    def _riquadro_connessioni(self) -> QtWidgets.QFrame:
        riquadro = QtWidgets.QFrame()
        riquadro.setProperty("ruolo", "riquadro")
        layout = QtWidgets.QVBoxLayout(riquadro)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        intestazione = QtWidgets.QLabel(self.tr("Connessioni"))
        intestazione.setProperty("ruolo", "didascalia")

        self.riga_pastiglie = QtWidgets.QHBoxLayout()
        self.riga_pastiglie.setSpacing(6)
        self.riga_pastiglie.addStretch()

        layout.addWidget(intestazione)
        layout.addLayout(self.riga_pastiglie)
        return riquadro

    def _azioni(self) -> QtWidgets.QHBoxLayout:
        riga = QtWidgets.QHBoxLayout()

        confronta = QtWidgets.QPushButton(self.tr("Confronta due ambienti"))
        confronta.setProperty("ruolo", "primario")
        confronta.clicked.connect(self.vai_al_confronto)

        connessioni = QtWidgets.QPushButton(self.tr("Gestisci le connessioni"))
        connessioni.clicked.connect(self.vai_alle_connessioni)

        riga.addStretch()
        riga.addWidget(connessioni)
        riga.addWidget(confronta)
        return riga

    # --- aggiornamento ------------------------------------------------------

    def aggiorna(self, connessioni: list[Connection], ultimo_confronto=None):
        self._mostra_ultimo(ultimo_confronto)
        self._mostra_connessioni(connessioni)

    def _mostra_ultimo(self, ultimo):
        self._ultimo = ultimo
        if not ultimo:
            self.ultimo_ambienti.setText(self.tr("Nessun confronto ancora eseguito."))
            self.ultimo_dettaglio.setText("")
            self.ripeti_button.setVisible(False)
            return

        self.ultimo_ambienti.setText(
            f"{ultimo['riferimento']}  →  {ultimo['da_allineare']}")
        self.ultimo_dettaglio.setText(" · ".join(filter(None, [
            self.tr("nessuna differenza") if ultimo["differenze"] == 0
            else self.tr("{0} differenze").format(ultimo["differenze"]),
            _quando_leggibile(ultimo.get("quando")),
        ])))
        self.ripeti_button.setVisible(True)

    def _mostra_connessioni(self, connessioni: list[Connection]):
        _svuota(self.riga_pastiglie)

        totale = len(connessioni)
        nel_portachiavi = sum(1 for c in connessioni if usa_portachiavi(c))
        in_chiaro = sum(1 for c in connessioni if password_letterale(c.conn_string))

        self.riga_pastiglie.addWidget(_pastiglia(
            self.tr("{0} configurate").format(totale) if totale != 1
            else self.tr("1 configurata"), "neutra"))
        if nel_portachiavi:
            self.riga_pastiglie.addWidget(_pastiglia(
                self.tr("{0} nel portachiavi").format(nel_portachiavi), "buona"))
        if in_chiaro:
            # E' l'unica cosa che vale la pena far notare da questa schermata.
            self.riga_pastiglie.addWidget(_pastiglia(
                self.tr("{0} con password in chiaro").format(in_chiaro), "allarme"))
        self.riga_pastiglie.addStretch()

    def _ripeti(self):
        if self._ultimo:
            self.ripeti_confronto.emit(self._ultimo["riferimento"], self._ultimo["da_allineare"])


def _pastiglia(testo: str, tipo: str) -> QtWidgets.QLabel:
    etichetta = QtWidgets.QLabel(testo)
    etichetta.setProperty("pastiglia", tipo)
    return etichetta


def _svuota(layout):
    while layout.count():
        voce = layout.takeAt(0)
        widget = voce.widget()
        if widget is not None:
            widget.deleteLater()


def _quando_leggibile(iso: str) -> str:
    """La data nel formato locale: un ISO con la Z non lo legge nessuno."""
    if not iso:
        return ""
    istante = QtCore.QDateTime.fromString(iso, QtCore.Qt.DateFormat.ISODate)
    if not istante.isValid():
        return iso
    return istante.toLocalTime().toString("d MMMM yyyy, HH:mm")
