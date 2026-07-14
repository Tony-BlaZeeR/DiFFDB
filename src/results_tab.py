"""Tab dei risultati: mostra il diff dentro l'app, non solo nell'Excel.

E' pura presentazione del DiffResult che il confronto ha gia' prodotto:
- albero raggruppato per categoria, con contatori per sezione;
- colore per direzione (manca in un ambiente / manca nell'altro / diverso);
- casella di ricerca per filtrare;
- checkbox su ogni riga per esportare (SQL) solo le differenze scelte.
"""

import logging
from typing import List, Optional

from src.diff_DB import DEFINITION_MISMATCH, MISSING
from src.qt import Qt, QtGui, QtWidgets

logger = logging.getLogger(__name__)

# Categorie nell'ordine in cui compaiono nell'albero.
SECTION_LABELS = {
    "tables": "Tabelle e colonne",
    "constraints": "Indici, chiavi e vincoli",
    "views": "Viste",
    "sequences": "Sequenze",
    "synonyms": "Sinonimi",
}

DIFF_ROLE = Qt.ItemDataRole.UserRole  # ci appendo l'oggetto Difference

# Colori (leggibili sul tema scuro): verde = da aggiungere qui, rosso = solo qui,
# ambra = presente in entrambi ma diverso.
COLOR_MISSING_HERE = QtGui.QColor("#6A8759")
COLOR_ONLY_HERE = QtGui.QColor("#CC7832")
COLOR_MISMATCH = QtGui.QColor("#D9A343")


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

        self.summary_label = QtWidgets.QLabel("Nessun confronto ancora eseguito.")
        self.summary_label.setObjectName("resultsSummary")
        layout.addWidget(self.summary_label)

        top = QtWidgets.QHBoxLayout()
        self.filter_input = QtWidgets.QLineEdit()
        self.filter_input.setPlaceholderText("Filtra per nome oggetto o colonna...")
        self.filter_input.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_input)

        self.select_all_button = QtWidgets.QPushButton("Seleziona tutto")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_button = QtWidgets.QPushButton("Deseleziona")
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(self.select_all_button)
        top.addWidget(self.select_none_button)
        layout.addLayout(top)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Oggetto", "Differenza", "Presente in", "Manca in", "Dettaglio"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        self.export_excel_button = QtWidgets.QPushButton("Esporta Excel (tutto)")
        self.export_excel_button.clicked.connect(self._export_excel)
        self.export_sql_button = QtWidgets.QPushButton("Esporta SQL (selezionati)")
        self.export_sql_button.clicked.connect(self._export_sql)
        bottom.addWidget(self.export_excel_button)
        bottom.addWidget(self.export_sql_button)
        layout.addLayout(bottom)

        self._set_buttons_enabled(False)

    # --- popolamento ------------------------------------------------------

    def show_result(self, diff):
        """Riempie l'albero con un DiffResult."""
        self._diff = diff
        self.tree.blockSignals(True)
        self.tree.clear()

        e1, e2 = diff.snapshot1.env_name, diff.snapshot2.env_name
        if diff.is_empty:
            self.summary_label.setText(f"{e1} e {e2} hanno la stessa struttura: nessuna differenza.")
        else:
            self.summary_label.setText(
                f"{len(diff.all)} differenze fra {e1} e {e2}. "
                f"Spunta le voci da includere nello script SQL."
            )

        for section, diffs in diff.sections.items():
            if not diffs:
                continue
            parent = QtWidgets.QTreeWidgetItem(self.tree, [f"{SECTION_LABELS[section]} ({len(diffs)})"])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.CheckState.Checked)
            parent.setExpanded(True)
            for d in diffs:
                self._add_diff_item(parent, d)

        self.tree.blockSignals(False)
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)
        self._set_buttons_enabled(not diff.is_empty)

    def _add_diff_item(self, parent, d):
        label = d.name if not d.column else f"{d.name}.{d.column}"
        item = QtWidgets.QTreeWidgetItem(
            parent, [label, d.change, d.present_in or "", d.missing_in or "", d.detail])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(0, DIFF_ROLE, d)

        color = self._color_for(d)
        for column in range(self.tree.columnCount()):
            item.setForeground(column, color)

    def _color_for(self, d) -> QtGui.QColor:
        if d.change == MISSING and self._diff is not None:
            # "manca nel primo ambiente" = presente solo nel secondo, e viceversa.
            if d.missing_in == self._diff.snapshot1.env_name:
                return COLOR_MISSING_HERE
            return COLOR_ONLY_HERE
        return COLOR_MISMATCH

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

    def checked_differences(self) -> List:
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
                self, "Niente da esportare", "Spunta almeno una differenza.")
            return
        if self._on_export_sql and self._diff is not None:
            self._on_export_sql(self._diff.subset(selected))

    # --- utilita' ---------------------------------------------------------

    def _set_buttons_enabled(self, enabled: bool):
        self.export_excel_button.setEnabled(enabled)
        self.export_sql_button.setEnabled(enabled)
        self.select_all_button.setEnabled(enabled)
        self.select_none_button.setEnabled(enabled)
        self._update_sql_button_text()

    def _update_sql_button_text(self):
        count = len(self.checked_differences()) if self._diff is not None else 0
        self.export_sql_button.setText(f"Esporta SQL ({count} selezionati)")
