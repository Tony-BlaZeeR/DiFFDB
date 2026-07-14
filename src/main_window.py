import logging
import os

import qtawesome as qta
from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtGui import QPixmap

from src.connections import Connection, load_connections, save_connections
from src.dialogs import AddConnectionDialog, EditConnectionDialog
from src.diff_DB import generate_excel_report, generate_sql_scripts, write_sql_script
from src.paths import config_dir, resource_path
from src.worker import CompareWorker

logger = logging.getLogger(__name__)

ICON_COLOR = "#A9B7C6"
TAB_SCELTA = 2


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.drag_position = None
        self.connections = []
        self.thread = None
        self.worker = None

        uic.loadUi(resource_path("ui", "main_window.ui"), self)
        with open(resource_path("styles", "style.qss"), encoding="utf-8") as qss:
            self.setStyleSheet(qss.read())

        self.setWindowTitle("DiFFDB")
        self.setWindowIcon(QtGui.QIcon(resource_path("images", "logo.png")))
        _set_windows_taskbar_identity()

        self.create_custom_title_bar()
        self.load_tabs()

        conn_table = self.conn_table()
        conn_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        conn_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        self.connections = load_connections()
        self.refresh_conn_table()
        self.refresh_comboboxes()

        self.tabWidget.currentChanged.connect(self.on_tab_changed)

    # --- accesso ai tab ---------------------------------------------------

    def conn_table(self):
        return self.tabWidget.widget(1).conn_table

    def scelta_tab(self):
        return self.tabWidget.widget(TAB_SCELTA)

    # --- gestione connessioni ---------------------------------------------

    def refresh_conn_table(self):
        """Ricostruisce la tabella dal modello in memoria.

        Va rifatta da zero a ogni modifica: i pulsanti riga catturano l'indice,
        che dopo una cancellazione non corrisponde piu' alla riga giusta.
        """
        table = self.conn_table()
        table.setRowCount(0)
        if table.columnCount() < 4:
            table.setColumnCount(4)
            table.setHorizontalHeaderItem(2, QtWidgets.QTableWidgetItem(""))
            table.setHorizontalHeaderItem(3, QtWidgets.QTableWidgetItem(""))

        for row, connection in enumerate(self.connections):
            table.insertRow(row)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(connection.name))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(_mask_password(connection.conn_string)))

            edit_button = QtWidgets.QPushButton()
            edit_button.setIcon(qta.icon("fa5s.pencil-alt", color=ICON_COLOR))
            edit_button.clicked.connect(lambda _, r=row: self.open_edit_connection_dialog(r))
            table.setCellWidget(row, 2, edit_button)

            delete_button = QtWidgets.QPushButton()
            delete_button.setIcon(qta.icon("fa5s.trash-alt", color=ICON_COLOR))
            delete_button.clicked.connect(lambda _, r=row: self.delete_row(r))
            table.setCellWidget(row, 3, delete_button)

        table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

    def persist(self):
        save_connections(self.connections)
        self.refresh_conn_table()
        self.refresh_comboboxes()

    def delete_row(self, row):
        if not 0 <= row < len(self.connections):
            return
        name = self.connections[row].name
        confirm = QtWidgets.QMessageBox.question(
            self, "Elimina connessione", f"Eliminare la connessione '{name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm == QtWidgets.QMessageBox.Yes:
            del self.connections[row]
            self.persist()

    def open_add_connection_dialog(self):
        dialog = AddConnectionDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            name = dialog.conn_name_input.text().strip()
            conn_string = dialog.conn_string_input.text().strip()
            if not name or not conn_string:
                QtWidgets.QMessageBox.warning(self, "Dati mancanti", "Nome e connection string sono obbligatori.")
                return
            self.connections.append(Connection(name=name, conn_string=conn_string))
            self.persist()

    def open_edit_connection_dialog(self, row):
        if not 0 <= row < len(self.connections):
            return
        connection = self.connections[row]
        dialog = EditConnectionDialog(self)
        dialog.conn_name_input.setText(connection.name)
        dialog.conn_string_input.setText(connection.conn_string)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            name = dialog.conn_name_input.text().strip()
            conn_string = dialog.conn_string_input.text().strip()
            if not name or not conn_string:
                QtWidgets.QMessageBox.warning(self, "Dati mancanti", "Nome e connection string sono obbligatori.")
                return
            self.connections[row] = Connection(name=name, conn_string=conn_string)
            self.persist()

    # --- barra del titolo --------------------------------------------------

    def create_custom_title_bar(self):
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        title_bar = QtWidgets.QWidget(self)
        title_bar.setObjectName("titleBar")
        layout = QtWidgets.QHBoxLayout(title_bar)
        layout.setContentsMargins(0, 0, 0, 0)

        logo_label = QtWidgets.QLabel(title_bar)
        logo_label.setPixmap(
            QPixmap(resource_path("images", "logo.png")).scaled(
                20, 20, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
        )

        title_label = QtWidgets.QLabel("DiFFDB", title_bar)
        title_label.setObjectName("titleLabel")

        minimize_button = QtWidgets.QPushButton("_", title_bar)
        minimize_button.setObjectName("minimizeButton")
        minimize_button.clicked.connect(self.showMinimized)

        close_button = QtWidgets.QPushButton("X", title_bar)
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.close)

        layout.addSpacerItem(
            QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        )
        layout.addWidget(logo_label)
        layout.addWidget(title_label)
        layout.addStretch()
        layout.addWidget(minimize_button)
        layout.addWidget(close_button)

        self.setMenuWidget(title_bar)
        title_bar.mousePressEvent = self.mousePressEvent
        title_bar.mouseMoveEvent = self.mouseMoveEvent

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and self.drag_position is not None:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    # --- tab ---------------------------------------------------------------

    def load_tabs(self):
        tab_home = uic.loadUi(resource_path("ui", "home.ui"))
        tab_config = uic.loadUi(resource_path("ui", "configurazione.ui"))
        tab_scelta = uic.loadUi(resource_path("ui", "scelta.ui"))

        self.tabWidget.insertTab(0, tab_home, qta.icon("fa5s.home", color=ICON_COLOR), "Home")
        self.tabWidget.insertTab(1, tab_config, qta.icon("fa5s.cog", color=ICON_COLOR), "Configurazione")
        self.tabWidget.insertTab(2, tab_scelta, qta.icon("fa5s.database", color=ICON_COLOR), "Scelta")

        if tab_home.layout() is None:
            tab_home.setLayout(QtWidgets.QVBoxLayout())
        logo_label = QtWidgets.QLabel(tab_home)
        logo_label.setPixmap(
            QPixmap(resource_path("images", "logo.png")).scaled(
                100, 100, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
        )
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        tab_home.layout().addWidget(logo_label)

        self.status_label = QtWidgets.QLabel("", tab_scelta)
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        tab_scelta.mainLayout.addWidget(self.status_label)

        tab_config.add_conn_button.clicked.connect(self.open_add_connection_dialog)
        tab_scelta.compare_button.clicked.connect(self.start_comparison)
        tab_scelta.comboBox1.currentIndexChanged.connect(self.update_compare_button_text)
        tab_scelta.comboBox2.currentIndexChanged.connect(self.update_compare_button_text)
        self.update_compare_button_text()

    def refresh_comboboxes(self):
        tab = self.scelta_tab()
        for combo in (tab.comboBox1, tab.comboBox2):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for connection in self.connections:
                combo.addItem(connection.name, connection.conn_string)
            index = combo.findText(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.update_compare_button_text()

    def update_compare_button_text(self):
        tab = self.scelta_tab()
        db1, db2 = tab.comboBox1.currentText(), tab.comboBox2.currentText()
        if db1 and db2:
            tab.compare_button.setText(f"Confronta {db1} con {db2}")
        else:
            tab.compare_button.setText("Confronta")

    def on_tab_changed(self, index):
        if index == TAB_SCELTA:
            self.refresh_comboboxes()

    # --- confronto ---------------------------------------------------------

    def start_comparison(self):
        if self.thread is not None:
            return  # confronto gia' in corso

        tab = self.scelta_tab()
        env1, env2 = tab.comboBox1.currentText(), tab.comboBox2.currentText()
        conn1, conn2 = tab.comboBox1.currentData(), tab.comboBox2.currentData()

        if not conn1 or not conn2:
            QtWidgets.QMessageBox.warning(
                self, "Connessioni mancanti",
                "Configura almeno due connessioni nella scheda Configurazione.",
            )
            return
        if env1 == env2:
            QtWidgets.QMessageBox.warning(
                self, "Ambienti uguali", "Seleziona due ambienti diversi da confrontare."
            )
            return

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Dove salvare report e script", str(config_dir())
        )
        if not output_dir:
            return
        self.output_dir = output_dir

        tab.compare_button.setEnabled(False)
        self.status_label.setText("Confronto in corso...")

        self.thread = QtCore.QThread(self)
        self.worker = CompareWorker(env1, conn1, env2, conn2)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_comparison_done)
        self.worker.failed.connect(self.on_comparison_failed)
        self.thread.start()

    def on_comparison_done(self, diff):
        self.cleanup_thread()

        if diff.is_empty:
            self.status_label.setText("Nessuna differenza trovata.")
            QtWidgets.QMessageBox.information(
                self, "Confronto completato",
                f"{diff.snapshot1.env_name} e {diff.snapshot2.env_name} hanno la stessa struttura.",
            )
            return

        try:
            excel_path = os.path.join(self.output_dir, "differenze_ambienti.xlsx")
            generate_excel_report(diff, excel_path)

            written = [excel_path]
            for target in (diff.snapshot1.env_name, diff.snapshot2.env_name):
                scripts = generate_sql_scripts(diff, target)
                if not any(scripts.values()):
                    continue
                sql_path = os.path.join(self.output_dir, f"allinea_{_slug(target)}.sql")
                write_sql_script(scripts, sql_path, target)
                written.append(sql_path)
        except Exception as exc:
            logger.exception("Scrittura degli output fallita")
            QtWidgets.QMessageBox.critical(self, "Errore", f"Impossibile scrivere i file: {exc}")
            return

        self.status_label.setText(f"{len(diff.all)} differenze trovate.")
        QtWidgets.QMessageBox.information(
            self, "Confronto completato",
            f"{len(diff.all)} differenze trovate.\n\nFile generati:\n" + "\n".join(written),
        )

    def on_comparison_failed(self, message):
        self.cleanup_thread()
        self.status_label.setText("Confronto fallito.")
        QtWidgets.QMessageBox.critical(self, "Errore di connessione", message)

    def cleanup_thread(self):
        self.scelta_tab().compare_button.setEnabled(True)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.worker = None


def _mask_password(conn_string: str) -> str:
    """Nasconde la password nella tabella a video (resta in chiaro nel file)."""
    if "://" not in conn_string or "@" not in conn_string:
        return conn_string
    scheme, rest = conn_string.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return conn_string
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_").lower() or "target"


def _set_windows_taskbar_identity():
    """Icona corretta nella taskbar di Windows. Su Linux/macOS non serve."""
    try:
        from PyQt5.QtWinExtras import QtWin

        QtWin.setCurrentProcessExplicitAppUserModelID("diffdb.app.1.0")
    except ImportError:
        pass
