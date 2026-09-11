"""Tab dei risultati: mostra il diff dentro l'app, non solo nell'Excel.

E' pura presentazione del DiffResult che il confronto ha gia' prodotto:
- albero raggruppato per categoria, con contatori per sezione;
- colore per direzione (manca in un ambiente / manca nell'altro / diverso);
- casella di ricerca per filtrare;
- checkbox su ogni riga per esportare (SQL) solo le differenze scelte.
"""

import logging

from diffdb.diff_DB import MISSING
from diffdb.qt import Qt, QtGui, QtWidgets

logger = logging.getLogger(__name__)

# Le etichette delle categorie si traducono al momento dell'uso (vedi
# _etichetta_sezione): un dizionario di modulo verrebbe valutato all'import,
# prima che il traduttore sia installato.

DIFF_ROLE = Qt.ItemDataRole.UserRole  # ci appendo l'oggetto Difference

# Colori, verificati a 4.5:1 sul fondo piu' chiaro dell'albero (WCAG AA).
# I precedenti stavano a 2.64:1 e 3.18:1: leggibili da chi ci vede bene, molto
# meno da tutti gli altri.
COLOR_MISSING_HERE = QtGui.QColor("#97B188")
COLOR_ONLY_HERE = QtGui.QColor("#DA9C69")
COLOR_MISMATCH = QtGui.QColor("#D9A343")

# Il colore non basta: chi non distingue verde e arancio vedrebbe tre righe
# identiche. Ogni direzione porta anche un simbolo, spiegato dalla legenda.
SIMBOLO_MANCA_NEL_PRIMO = "←"
SIMBOLO_MANCA_NEL_SECONDO = "→"
SIMBOLO_DIVERSO = "≠"


class ResultsTab(QtWidgets.QWidget):
    def __init__(self, on_export_excel=None, on_export_sql=None, parent=None):
        super().__init__(parent)
        self._on_export_excel = on_export_excel
        self._on_export_sql = on_export_sql
        self._diff = None
        self._build_ui()

    # --- costruzione UI ---------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        layout.addWidget(self._riquadro_riepilogo())

        top = QtWidgets.QHBoxLayout()
        self.filter_input = QtWidgets.QLineEdit()
        self.filter_input.setPlaceholderText(self.tr("Filtra per nome oggetto o colonna..."))
        self.filter_input.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_input)

        self.select_all_button = QtWidgets.QPushButton(self.tr("Seleziona tutto"))
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_button = QtWidgets.QPushButton(self.tr("Deseleziona"))
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(self.select_all_button)
        top.addWidget(self.select_none_button)
        layout.addLayout(top)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([self.tr("Oggetto"), self.tr("Differenza"),
                                   self.tr("Presente in"), self.tr("Manca in"),
                                   self.tr("Dettaglio")])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        self.export_excel_button = QtWidgets.QPushButton(self.tr("Esporta Excel (tutto)"))
        self.export_excel_button.clicked.connect(self._export_excel)
        self.export_sql_button = QtWidgets.QPushButton(self.tr("Esporta SQL (selezionati)"))
        self.export_sql_button.clicked.connect(self._export_sql)
        bottom.addWidget(self.export_excel_button)
        bottom.addWidget(self.export_sql_button)
        layout.addLayout(bottom)

        self._scorciatoie()
        self._set_buttons_enabled(False)

    def _scorciatoie(self):
        """Le scorciatoie valgono solo dentro questa scheda.

        Con la portata predefinita (tutta la finestra) Ctrl+S esporterebbe lo
        script SQL anche stando nella scheda delle connessioni.
        """
        for sequenza, azione, widget, descrizione in (
            ("Ctrl+F", self.filter_input.setFocus, self.filter_input,
             self.tr("Vai al filtro")),
            ("Ctrl+E", self._export_excel, self.export_excel_button,
             self.export_excel_button.text()),
            ("Ctrl+S", self._export_sql, self.export_sql_button,
             self.export_sql_button.text()),
        ):
            scorciatoia = QtGui.QShortcut(QtGui.QKeySequence(sequenza), self)
            scorciatoia.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            scorciatoia.activated.connect(azione)
            widget.setToolTip(f"{descrizione} ({sequenza})")

    def _riquadro_riepilogo(self) -> QtWidgets.QFrame:
        """Quante differenze, in che direzione, e come si distribuiscono.

        E' la prima cosa che si guarda: prima era una riga di testo piccolo che
        diceva solo il totale.
        """
        riquadro = QtWidgets.QFrame()
        riquadro.setObjectName("resultsSummary")
        riquadro.setProperty("ruolo", "riquadro")
        layout = QtWidgets.QHBoxLayout(riquadro)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(18)

        self.count_label = QtWidgets.QLabel("—")
        self.count_label.setProperty("ruolo", "conteggio")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setMinimumWidth(56)

        colonna = QtWidgets.QVBoxLayout()
        colonna.setSpacing(6)
        self.summary_label = QtWidgets.QLabel(self.tr("Nessun confronto ancora eseguito."))
        self.summary_label.setWordWrap(True)
        colonna.addWidget(self.summary_label)

        self.pills_row = QtWidgets.QHBoxLayout()
        self.pills_row.setSpacing(6)
        self.pills_row.addStretch()
        colonna.addLayout(self.pills_row)

        self.legend_label = QtWidgets.QLabel("")
        self.legend_label.setProperty("ruolo", "didascalia")
        self.legend_label.setWordWrap(True)
        colonna.addWidget(self.legend_label)

        layout.addWidget(self.count_label)
        layout.addLayout(colonna, 1)
        return riquadro

    def _aggiorna_legenda(self, diff):
        """Cosa vogliono dire simboli e colori. Prima non lo diceva niente:
        la spiegazione esisteva solo in un commento nel codice."""
        if diff.is_empty:
            self.legend_label.setText("")
            return
        e1, e2 = diff.snapshot1.env_name, diff.snapshot2.env_name
        self.legend_label.setText("    ".join([
            self.tr("{0} manca in {1}").format(SIMBOLO_MANCA_NEL_PRIMO, e1),
            self.tr("{0} manca in {1}").format(SIMBOLO_MANCA_NEL_SECONDO, e2),
            self.tr("{0} presente in entrambi ma diverso").format(SIMBOLO_DIVERSO),
        ]))

    def _aggiorna_riepilogo(self, diff):
        e1, e2 = diff.snapshot1.env_name, diff.snapshot2.env_name
        self.count_label.setText(str(len(diff.all)) if not diff.is_empty else "0")

        if diff.is_empty:
            self.summary_label.setText(
                self.tr("{0} e {1} hanno la stessa struttura: nessuna differenza.").format(e1, e2))
        else:
            self.summary_label.setText(
                self.tr("{0}  →  {1}. Spunta le voci da includere nello script SQL.")
                .format(e1, e2))

        _svuota(self.pills_row)
        for sezione, differenze in diff.sections.items():
            if differenze:
                self.pills_row.addWidget(_pastiglia(
                    f"{len(differenze)} {self._etichetta_sezione(sezione).lower()}"))
        self.pills_row.addStretch()

        self._aggiorna_legenda(diff)

    # --- popolamento ------------------------------------------------------

    def show_result(self, diff):
        """Riempie l'albero con un DiffResult."""
        self._diff = diff
        self.tree.blockSignals(True)
        self.tree.clear()

        self._aggiorna_riepilogo(diff)

        for section, diffs in diff.sections.items():
            if not diffs:
                continue
            parent = QtWidgets.QTreeWidgetItem(
                self.tree, [f"{self._etichetta_sezione(section)} ({len(diffs)})"])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.CheckState.Checked)
            parent.setExpanded(True)
            # Costruiti senza genitore e attaccati tutti insieme: passare il
            # genitore al costruttore uno per volta e' quadratico in Qt (ogni
            # inserimento ricalcola qualcosa sui fratelli esistenti). Su
            # 100.000 differenze la differenza e' 5 secondi contro 0.2,
            # misurata prima di scrivere questa riga, non presunta.
            parent.addChildren([self._costruisci_diff_item(d) for d in diffs])

        self.tree.blockSignals(False)

        # Le prime colonne si dimensionano sul contenuto e l'ultima si prende il
        # resto: prima "Dettaglio" sbordava e obbligava a scorrere in orizzontale.
        # Interactive e non ResizeToContents, cosi' restano trascinabili a mano.
        intestazione = self.tree.header()
        ultima = self.tree.columnCount() - 1
        for colonna in range(ultima):
            intestazione.setSectionResizeMode(
                colonna, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.tree.resizeColumnToContents(colonna)
        intestazione.setSectionResizeMode(ultima, QtWidgets.QHeaderView.ResizeMode.Stretch)

        self._set_buttons_enabled(not diff.is_empty)

    def _etichetta_sezione(self, chiave: str) -> str:
        """Nome leggibile di una categoria, nella lingua dell'interfaccia."""
        return {
            "tables": self.tr("Tabelle e colonne"),
            "constraints": self.tr("Indici, chiavi e vincoli"),
            "views": self.tr("Viste"),
            "sequences": self.tr("Sequenze"),
            "synonyms": self.tr("Sinonimi"),
        }.get(chiave, chiave)

    def _costruisci_diff_item(self, d):
        """Costruisce la riga di una differenza, senza genitore.

        Chi chiama la attacca con addChildren() (vedi show_result): fuori da
        qui non deve mai finire nell'albero con QTreeWidgetItem(parent, ...).
        """
        label = d.name if not d.column else f"{d.name}.{d.column}"
        item = QtWidgets.QTreeWidgetItem(
            [label, f"{self._simbolo(d)}  {d.change}",
             d.present_in or "", d.missing_in or "", d.detail])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(0, DIFF_ROLE, d)

        color = self._color_for(d)
        # Il testo lungo viene troncato con i puntini: nel tooltip resta intero.
        suggerimento = "\n".join(filter(None, [f"{label}: {d.change}", d.detail]))
        for column in range(self.tree.columnCount()):
            item.setForeground(column, color)
            item.setToolTip(column, suggerimento)
        return item

    def _color_for(self, d) -> QtGui.QColor:
        return {SIMBOLO_MANCA_NEL_PRIMO: COLOR_MISSING_HERE,
                SIMBOLO_MANCA_NEL_SECONDO: COLOR_ONLY_HERE}.get(
                    self._simbolo(d), COLOR_MISMATCH)

    def _simbolo(self, d) -> str:
        """Il verso della differenza, in un carattere.

        Serve a chi non distingue i colori, e a chiunque scorra un albero lungo:
        una freccia si riconosce piu' in fretta di una sfumatura.
        """
        if d.change == MISSING and self._diff is not None:
            # "manca nel primo ambiente" = presente solo nel secondo, e viceversa.
            if d.missing_in == self._diff.snapshot1.env_name:
                return SIMBOLO_MANCA_NEL_PRIMO
            return SIMBOLO_MANCA_NEL_SECONDO
        return SIMBOLO_DIVERSO

    # --- interazione ------------------------------------------------------

    def _on_item_changed(self, item, column):
        # Il conteggio dei selezionati aggiorna il testo del pulsante SQL.
        self._update_sql_button_text()

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            root.child(i).setCheckState(0, state)

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            section = root.child(i)
            visible_children = 0
            for j in range(section.childCount()):
                child = section.child(j)
                match = needle in child.text(0).lower() or needle in child.text(4).lower()
                child.setHidden(bool(needle) and not match)
                visible_children += 0 if child.isHidden() else 1
            section.setHidden(bool(needle) and visible_children == 0)

    def checked_differences(self) -> list:
        """Le Difference con la spunta attiva."""
        result = []
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            section = root.child(i)
            for j in range(section.childCount()):
                child = section.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    diff = child.data(0, DIFF_ROLE)
                    if diff is not None:
                        result.append(diff)
        return result

    # --- export -----------------------------------------------------------

    def _export_excel(self):
        if self._on_export_excel and self._diff is not None:
            self._on_export_excel(self._diff)

    def _export_sql(self):
        selected = self.checked_differences()
        if not selected:
            QtWidgets.QMessageBox.information(
                self, self.tr("Niente da esportare"),
                self.tr("Spunta almeno una differenza."))
            return
        if self._on_export_sql and self._diff is not None:
            # Anche il totale: lo script deve poter dire se e' completo o parziale.
            self._on_export_sql(self._diff.subset(selected), len(self._diff.all))

    # --- utilita' ---------------------------------------------------------

    def _set_buttons_enabled(self, enabled: bool):
        self.export_excel_button.setEnabled(enabled)
        self.export_sql_button.setEnabled(enabled)
        self.select_all_button.setEnabled(enabled)
        self.select_none_button.setEnabled(enabled)
        self._update_sql_button_text()

    def _update_sql_button_text(self):
        count = len(self.checked_differences()) if self._diff is not None else 0
        self.export_sql_button.setText(self.tr("Esporta SQL ({0} selezionati)").format(count))


def _pastiglia(testo: str) -> QtWidgets.QLabel:
    etichetta = QtWidgets.QLabel(testo)
    etichetta.setProperty("pastiglia", "neutra")
    return etichetta


def _svuota(layout):
    while layout.count():
        voce = layout.takeAt(0)
        widget = voce.widget()
        if widget is not None:
            widget.deleteLater()
