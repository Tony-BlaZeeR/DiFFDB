import logging

import qtawesome as qta

from src.connections import load_connections, save_connections
from src.dialogs import ask_connection
from src.paths import config_dir, resource_path
from src.qt import Qt, QtCore, QtGui, QtWidgets, bind_children, load_ui
from src.report import write_outputs
from src.worker import CompareWorker

logger = logging.getLogger(__name__)

ICON_COLOR = "#A9B7C6"
TAB_SCELTA = 2
COL_NAME, COL_STRING, COL_SCHEMA, COL_EDIT, COL_DELETE = range(5)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.drag_position = None
        self.connections = []
        self.thread = None
        self.worker = None
        self.output_dir = str(config_dir())

        self._ui = load_ui(resource_path("ui", "main_window.ui"))
        self.setCentralWidget(self._ui.centralWidget())
        bind_children(self.centralWidget(), self)
        self.setMinimumSize(self._ui.minimumSize())
        self.setMaximumSize(self._ui.maximumSize())
        self.resize(self._ui.size())

        with open(resource_path("styles", "style.qss"), encoding="utf-8") as qss:
            self.setStyleSheet(qss.read())

        self.setWindowTitle("DiFFDB")
        self.setWindowIcon(QtGui.QIcon(resource_path("images", "logo.png")))
        _set_windows_taskbar_identity()

        self.create_custom_title_bar()
        self.load_tabs()

        table = self.conn_table()
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

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
        che dopo una cancellazione non corrisponderebbe piu' alla riga giusta.
        """
        table = self.conn_table()
        table.setRowCount(0)
        if table.columnCount() < 5:
            table.setColumnCount(5)
        for column, title in ((COL_NAME, "Nome"), (COL_STRING, "Connessione"),
                              (COL_SCHEMA, "Schema"), (COL_EDIT, ""), (COL_DELETE, "")):
            table.setHorizontalHeaderItem(column, QtWidgets.QTableWidgetItem(title))

        for row, connection in enumerate(self.connections):
            table.insertRow(row)
            table.setItem(row, COL_NAME, QtWidgets.QTableWidgetItem(connection.name))
            table.setItem(row, COL_STRING,
                          QtWidgets.QTableWidgetItem(mask_password(connection.conn_string)))
            table.setItem(row, COL_SCHEMA, QtWidgets.QTableWidgetItem(connection.schema or ""))

            edit_button = QtWidgets.QPushButton()
            edit_button.setIcon(qta.icon("fa5s.pencil-alt", color=ICON_COLOR))
            edit_button.clicked.connect(lambda _=False, r=row: self.edit_connection(r))
            table.setCellWidget(row, COL_EDIT, edit_button)

            delete_button = QtWidgets.QPushButton()
            delete_button.setIcon(qta.icon("fa5s.trash-alt", color=ICON_COLOR))
            delete_button.clicked.connect(lambda _=False, r=row: self.delete_connection(r))
            table.setCellWidget(row, COL_DELETE, delete_button)

        header = table.horizontalHeader()
        header.setSectionResizeMode(COL_EDIT, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DELETE, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

    def persist(self):
        save_connections(self.connections)
        self.refresh_conn_table()
        self.refresh_comboboxes()

    def add_connection(self):
        connection = ask_connection(self)
        if connection is not None:
            self.connections.append(connection)
            self.persist()

    def edit_connection(self, row):
        if not 0 <= row < len(self.connections):
            return
        connection = ask_connection(self, self.connections[row])
        if connection is not None:
            self.connections[row] = connection
            self.persist()

    def delete_connection(self, row):
        if not 0 <= row < len(self.connections):
            return
        name = self.connections[row].name
        confirm = QtWidgets.QMessageBox.question(
            self, "Elimina connessione", f"Eliminare la connessione '{name}'?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
            del self.connections[row]
            self.persist()

    # --- barra del titolo --------------------------------------------------

    def create_custom_title_bar(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        title_bar = QtWidgets.QWidget(self)
        title_bar.setObjectName("titleBar")
        layout = QtWidgets.QHBoxLayout(title_bar)
        layout.setContentsMargins(0, 0, 0, 0)

        logo_label = QtWidgets.QLabel(title_bar)
        logo_label.setPixmap(_logo(20))

        title_label = QtWidgets.QLabel("DiFFDB", title_bar)
        title_label.setObjectName("titleLabel")

        minimize_button = QtWidgets.QPushButton("_", title_bar)
        minimize_button.setObjectName("minimizeButton")
        minimize_button.clicked.connect(self.showMinimized)

        close_button = QtWidgets.QPushButton("X", title_bar)
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.close)

        layout.addSpacerItem(QtWidgets.QSpacerItem(
            20, 20, QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum))
        layout.addWidget(logo_label)
        layout.addWidget(title_label)
        layout.addStretch()
        layout.addWidget(minimize_button)
        layout.addWidget(close_button)

        self.setMenuWidget(title_bar)
        title_bar.mousePressEvent = self.mousePressEvent
        title_bar.mouseMoveEvent = self.mouseMoveEvent

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    # --- tab ---------------------------------------------------------------

    def load_tabs(self):
        tab_home = load_ui(resource_path("ui", "home.ui"))
        tab_config = load_ui(resource_path("ui", "configurazione.ui"))
        tab_scelta = load_ui(resource_path("ui", "scelta.ui"))

        self.tabWidget.insertTab(0, tab_home, qta.icon("fa5s.home", color=ICON_COLOR), "Home")
        self.tabWidget.insertTab(1, tab_config, qta.icon("fa5s.cog", color=ICON_COLOR), "Configurazione")
        self.tabWidget.insertTab(2, tab_scelta, qta.icon("fa5s.database", color=ICON_COLOR), "Scelta")

        if tab_home.layout() is None:
            tab_home.setLayout(QtWidgets.QVBoxLayout())
        logo_label = QtWidgets.QLabel(tab_home)
        logo_label.setPixmap(_logo(100))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tab_home.layout().addWidget(logo_label)

        self.status_label = QtWidgets.QLabel("", tab_scelta)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tab_scelta.mainLayout.addWidget(self.status_label)

        tab_config.add_conn_button.clicked.connect(self.add_connection)
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
                label = connection.name
                if connection.schema:
                    label += f" [{connection.schema}]"
                combo.addItem(label, connection.name)
            index = combo.findText(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.update_compare_button_text()

    def selected_connections(self):
        tab = self.scelta_tab()
        by_name = {c.name: c for c in self.connections}
        return by_name.get(tab.comboBox1.currentData()), by_name.get(tab.comboBox2.currentData())

    def update_compare_button_text(self):
        tab = self.scelta_tab()
        conn1, conn2 = self.selected_connections()
        if conn1 and conn2:
            tab.compare_button.setText(f"Confronta {conn1.name} con {conn2.name}")
        else:
            tab.compare_button.setText("Confronta")

    def on_tab_changed(self, index):
        if index == TAB_SCELTA:
            self.refresh_comboboxes()

    # --- confronto ---------------------------------------------------------

    def start_comparison(self):
        if self.thread is not None:
            return  # confronto gia' in corso

        conn1, conn2 = self.selected_connections()
        if conn1 is None or conn2 is None:
            QtWidgets.QMessageBox.warning(
                self, "Connessioni mancanti",
                "Configura almeno due connessioni nella scheda Configurazione.")
            return
        if conn1.name == conn2.name:
            QtWidgets.QMessageBox.warning(
                self, "Ambienti uguali", "Seleziona due ambienti diversi da confrontare.")
            return

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Dove salvare report e script", self.output_dir)
        if not output_dir:
            return
        self.output_dir = output_dir

        self.scelta_tab().compare_button.setEnabled(False)
        self.status_label.setText("Confronto in corso...")

        self.thread = QtCore.QThread(self)
        self.worker = CompareWorker(conn1, conn2)
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
                f"{diff.snapshot1.env_name} e {diff.snapshot2.env_name} hanno la stessa struttura.")
            return

        try:
            written = write_outputs(diff, self.output_dir)
        except Exception as exc:
            logger.exception("Scrittura degli output fallita")
            QtWidgets.QMessageBox.critical(self, "Errore", f"Impossibile scrivere i file: {exc}")
            return

        self.status_label.setText(f"{len(diff.all)} differenze trovate.")
        QtWidgets.QMessageBox.information(
            self, "Confronto completato",
            f"{len(diff.all)} differenze trovate.\n\nFile generati:\n" + "\n".join(written))

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


def mask_password(conn_string: str) -> str:
    """Nasconde la password nella tabella a video (nel file resta come l'hai scritta)."""
    if "://" not in conn_string or "@" not in conn_string:
        return conn_string
    scheme, rest = conn_string.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return conn_string
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def _logo(size: int) -> QtGui.QPixmap:
    return QtGui.QPixmap(resource_path("images", "logo.png")).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _set_windows_taskbar_identity():
    """Icona corretta nella taskbar di Windows. Su Linux e macOS non serve."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("diffdb.app.1.0")
    except Exception as exc:  # pragma: no cover - dipende dalla versione di Windows
        logger.debug("AppUserModelID non impostato: %s", exc)
