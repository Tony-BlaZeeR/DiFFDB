"""Editor dei filtri di confronto (il file ``diffdb.rules.json``) dalla GUI.

I filtri esistono da sempre nel motore e dalla CLI, ma finora si scrivevano solo
a mano nel JSON: chi usa l'interfaccia non aveva modo di dire "confronta solo le
tabelle che combaciano con ``*T_UTENTE*``". Questo dialog scrive e rilegge lo
stesso file, cosi' resta versionabile e valido anche per la CLI e la CI.

Le *differenze accettate* (la baseline) non si toccano qui: si modificano solo i
filtri per modello di nome e le categorie da ignorare, e l'elenco di accettate
dell'oggetto ``Regole`` di partenza viene conservato tale e quale.
"""

import re

from diffdb.qt import QObject, QtWidgets
from diffdb.rules import CATEGORIE, Regole
from diffdb.widgets import Riquadro

_SEPARATORI = re.compile(r"[,\s;]+")


def pattern_da_testo(testo: str) -> list[str]:
    """Spezza un campo di testo in modelli, separati da virgola, spazio o a capo.

    L'ordine di inserimento si conserva e i doppioni si rimuovono: un elenco con
    lo stesso modello due volte non cambia il confronto, ma sporca il file.
    """
    visti: list[str] = []
    for pezzo in _SEPARATORI.split(testo or ""):
        pezzo = pezzo.strip()
        if pezzo and pezzo not in visti:
            visti.append(pezzo)
    return visti


def testo_da_pattern(modelli) -> str:
    """Un modello per riga: e' il verso in cui si leggono e si modificano."""
    return "\n".join(modelli or [])


def regole_aggiornate(base: Regole, *, solo_tabelle, escludi_tabelle, escludi_viste,
                      escludi_sequenze, escludi_sinonimi, categorie_ignorate) -> Regole:
    """Nuove ``Regole`` con i filtri indicati, conservando la baseline accettata."""
    return Regole(
        escludi_tabelle=list(escludi_tabelle),
        escludi_viste=list(escludi_viste),
        escludi_sequenze=list(escludi_sequenze),
        escludi_sinonimi=list(escludi_sinonimi),
        solo_tabelle=list(solo_tabelle),
        categorie_ignorate=set(categorie_ignorate),
        accettate=set(base.accettate),
        origine=base.origine,
    )


def modifica_filtri(parent, regole: Regole) -> Regole | None:
    """Apre il dialog e restituisce le nuove regole, o None se si annulla."""
    return DialogoFiltri(parent, regole).chiedi()


class DialogoFiltri(QObject):
    def __init__(self, parent, regole: Regole):
        super().__init__(parent)
        self.regole = regole
        self.dialog = QtWidgets.QDialog(parent)
        self.dialog.setWindowTitle(self.tr("Filtri di confronto"))
        self.dialog.setMinimumWidth(560)
        self._costruisci()
        self._riempi(regole)
        self._aggiorna_riepilogo()

    # --- costruzione --------------------------------------------------------

    def _costruisci(self):
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        titolo = QtWidgets.QLabel(self.tr("Cosa entra nel confronto"))
        titolo.setProperty("ruolo", "titolo")
        layout.addWidget(titolo)

        sottotitolo = QtWidgets.QLabel(self.tr(
            "Modelli di nome in stile glob: * e ? valgono, maiuscole e minuscole "
            "non contano (Oracle e PostgreSQL scrivono i nomi in modo diverso). "
            "Esempio: *T_UTENTE* prende solo le tabelle che contengono T_UTENTE."))
        sottotitolo.setProperty("ruolo", "sottotitolo")
        sottotitolo.setWordWrap(True)
        layout.addWidget(sottotitolo)

        # Includi solo
        includi, gi = self._riquadro(self.tr("Includi solo"))
        self.solo_tabelle = QtWidgets.QLineEdit()
        self.solo_tabelle.setPlaceholderText("*T_UTENTE*, APP_*")
        gi.addWidget(self.solo_tabelle)
        didascalia = QtWidgets.QLabel(self.tr(
            "Se compilato, si confrontano solo le tabelle che combaciano. Vuoto = tutte."))
        didascalia.setProperty("ruolo", "didascalia")
        didascalia.setWordWrap(True)
        gi.addWidget(didascalia)
        layout.addWidget(includi)

        # Escludi
        escludi, ve = self._riquadro(self.tr("Escludi"))
        ge = QtWidgets.QGridLayout()
        ge.setHorizontalSpacing(14)
        ge.setVerticalSpacing(8)
        self.escludi_tabelle = QtWidgets.QLineEdit()
        self.escludi_tabelle.setPlaceholderText("TMP_*, *_BACKUP")
        self.escludi_viste = QtWidgets.QLineEdit()
        self.escludi_sequenze = QtWidgets.QLineEdit()
        self.escludi_sinonimi = QtWidgets.QLineEdit()
        for riga, (etichetta, campo) in enumerate((
                (self.tr("Tabelle"), self.escludi_tabelle),
                (self.tr("Viste"), self.escludi_viste),
                (self.tr("Sequenze"), self.escludi_sequenze),
                (self.tr("Sinonimi"), self.escludi_sinonimi))):
            lbl = QtWidgets.QLabel(etichetta)
            lbl.setProperty("ruolo", "didascalia")
            ge.addWidget(lbl, riga, 0)
            ge.addWidget(campo, riga, 1)
        ge.setColumnStretch(1, 1)
        ve.addLayout(ge)
        layout.addWidget(escludi)

        # Categorie da ignorare
        categorie, vc = self._riquadro(self.tr("Categorie da ignorare"))
        gc = QtWidgets.QGridLayout()
        gc.setHorizontalSpacing(14)
        gc.setVerticalSpacing(6)
        # Letterali e non una tabella: lupdate estrae solo le stringhe scritte
        # dentro self.tr(), non quelle passate da una variabile.
        etichette = {
            "tables": self.tr("Tabelle"),
            "constraints": self.tr("Chiavi e vincoli"),
            "views": self.tr("Viste"),
            "sequences": self.tr("Sequenze"),
            "synonyms": self.tr("Sinonimi"),
            "triggers": self.tr("Trigger"),
            "routines": self.tr("Routine"),
        }
        self.caselle_categorie: dict[str, QtWidgets.QCheckBox] = {}
        for indice, chiave in enumerate(CATEGORIE):
            casella = QtWidgets.QCheckBox(etichette.get(chiave, chiave))
            self.caselle_categorie[chiave] = casella
            gc.addWidget(casella, indice // 2, indice % 2)
        vc.addLayout(gc)
        layout.addWidget(categorie)

        # Riepilogo live
        self.riepilogo = QtWidgets.QLabel("")
        self.riepilogo.setProperty("ruolo", "sottotitolo")
        self.riepilogo.setWordWrap(True)
        layout.addWidget(self.riepilogo)

        # Pulsanti
        riga = QtWidgets.QHBoxLayout()
        pulisci = QtWidgets.QPushButton(self.tr("Pulisci tutto"))
        pulisci.clicked.connect(self._pulisci)
        annulla = QtWidgets.QPushButton(self.tr("Annulla"))
        annulla.clicked.connect(self.dialog.reject)
        salva = QtWidgets.QPushButton(self.tr("Salva"))
        salva.setProperty("ruolo", "primario")
        salva.setDefault(True)
        salva.clicked.connect(self.dialog.accept)
        riga.addWidget(pulisci)
        riga.addStretch()
        riga.addWidget(annulla)
        riga.addWidget(salva)
        layout.addLayout(riga)

        for campo in (self.solo_tabelle, self.escludi_tabelle, self.escludi_viste,
                      self.escludi_sequenze, self.escludi_sinonimi):
            campo.textChanged.connect(lambda _=None: self._aggiorna_riepilogo())
        for casella in self.caselle_categorie.values():
            casella.toggled.connect(lambda _=False: self._aggiorna_riepilogo())

    def _riquadro(self, titolo: str):
        """Un Riquadro con titolo visibile in entrambi i temi.

        In Moderna il titolo e' l'etichetta interna; in Retro quella si nasconde
        e il titolo passa sul bordo (lo fa il Riquadro da solo).
        """
        riquadro = Riquadro(titolo)
        vbox = QtWidgets.QVBoxLayout(riquadro)
        vbox.setContentsMargins(16, 14, 16, 14)
        vbox.setSpacing(6)
        intestazione = QtWidgets.QLabel(titolo)
        intestazione.setProperty("ruolo", "didascalia")
        riquadro.registra_etichetta(intestazione)
        vbox.addWidget(intestazione)
        return riquadro, vbox

    # --- dati ---------------------------------------------------------------

    def _riempi(self, regole: Regole):
        self.solo_tabelle.setText(testo_da_pattern(regole.solo_tabelle).replace("\n", ", "))
        self.escludi_tabelle.setText(", ".join(regole.escludi_tabelle))
        self.escludi_viste.setText(", ".join(regole.escludi_viste))
        self.escludi_sequenze.setText(", ".join(regole.escludi_sequenze))
        self.escludi_sinonimi.setText(", ".join(regole.escludi_sinonimi))
        for chiave, casella in self.caselle_categorie.items():
            casella.setChecked(chiave in regole.categorie_ignorate)

    def _pulisci(self):
        for campo in (self.solo_tabelle, self.escludi_tabelle, self.escludi_viste,
                      self.escludi_sequenze, self.escludi_sinonimi):
            campo.clear()
        for casella in self.caselle_categorie.values():
            casella.setChecked(False)

    def _regole_correnti(self) -> Regole:
        return regole_aggiornate(
            self.regole,
            solo_tabelle=pattern_da_testo(self.solo_tabelle.text()),
            escludi_tabelle=pattern_da_testo(self.escludi_tabelle.text()),
            escludi_viste=pattern_da_testo(self.escludi_viste.text()),
            escludi_sequenze=pattern_da_testo(self.escludi_sequenze.text()),
            escludi_sinonimi=pattern_da_testo(self.escludi_sinonimi.text()),
            categorie_ignorate={chiave for chiave, c in self.caselle_categorie.items()
                                if c.isChecked()},
        )

    def _aggiorna_riepilogo(self):
        descrizione = self._regole_correnti().descrizione()
        self.riepilogo.setText(descrizione or self.tr("Nessun filtro: si confronta tutto."))

    # --- ciclo del dialog ---------------------------------------------------

    def chiedi(self) -> Regole | None:
        if self.dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            return self._regole_correnti()
        return None
