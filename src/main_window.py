import os
import logging
from PyQt5 import QtWidgets, uic, QtCore, QtGui
from PyQt5.QtGui import QPixmap
import qtawesome as qta
from sqlalchemy import create_engine, inspect
import sqlalchemy.exc
from PyQt5.QtWinExtras import QtWin
from dialogs import AddConnectionDialog, EditConnectionDialog
from utils import compare_environments, generate_sql_scripts, generate_excel_report

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        
        ui_path = os.path.join(os.path.dirname(__file__), 'ui', 'main_window.ui')
        print(f"UI Path: {ui_path}")  # Print the UI path for debugging
        if not os.path.exists(ui_path):
            raise FileNotFoundError(f"The UI file was not found: {ui_path}")
        uic.loadUi(ui_path, self)
        self.setStyleSheet(open('src/styles/style.qss').read())

        # Set application name and design for Windows taskbar
        self.setWindowTitle("DiFFDB")
        app_id = 'mycompany.diffdb.1.0'
        QtWin.setCurrentProcessExplicitAppUserModelID(app_id)

        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), 'images', 'logo.png')
        self.setWindowIcon(QtGui.QIcon(icon_path))

        # Create custom title bar
        self.create_custom_title_bar()

        # Load tabs
        self.load_tabs()
        
        # Set column widths for conn_table
        self.tabWidget.widget(1).conn_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.tabWidget.widget(1).conn_table.setColumnWidth(0, int(self.tabWidget.widget(1).conn_table.width() * 0.3))
        self.tabWidget.widget(1).conn_table.setColumnWidth(1, int(self.tabWidget.widget(1).conn_table.width() * 0.7))

        # Add edit buttons to conn_table
        self.add_edit_buttons()

        # Load connections from file
        self.load_connections_from_file()

        # Connect tab change signal to function
        self.tabWidget.currentChanged.connect(self.on_tab_changed)

    def add_edit_buttons(self):
        conn_table = self.tabWidget.widget(1).conn_table
        row_count = conn_table.rowCount()
        column_count = conn_table.columnCount()

        # Ensure there is a column for the edit buttons
        if column_count < 4:
            conn_table.setColumnCount(4)
            conn_table.setHorizontalHeaderItem(2, QtWidgets.QTableWidgetItem(""))
            conn_table.setHorizontalHeaderItem(3, QtWidgets.QTableWidgetItem(""))

        icon_color = '#A9B7C6'  # Colore del testo

        for row in range(row_count):
            edit_button = QtWidgets.QPushButton()
            edit_button.setIcon(qta.icon('fa.pencil', color=icon_color))
            edit_button.clicked.connect(lambda _, r=row: self.open_edit_connection_dialog(r))
            conn_table.setCellWidget(row, 2, edit_button)

            delete_button = QtWidgets.QPushButton()
            delete_button.setIcon(qta.icon('fa.trash', color=icon_color))
            delete_button.clicked.connect(lambda _, r=row: self.delete_row(r))
            conn_table.setCellWidget(row, 3, delete_button)

        # Set column resize mode to fit contents
        conn_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        conn_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

        # Disable default cell editing
        conn_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    def edit_row(self, row, conn_name, conn_string):
        self.tabWidget.widget(1).conn_table.setItem(row, 0, QtWidgets.QTableWidgetItem(conn_name))
        self.tabWidget.widget(1).conn_table.setItem(row, 1, QtWidgets.QTableWidgetItem(conn_string))
        self.save_connections_to_file()

    def delete_row(self, row):
        conn_table = self.tabWidget.widget(1).conn_table
        conn_table.removeRow(row)
        self.save_connections_to_file()

    def open_add_connection_dialog(self):
        dialog = AddConnectionDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            conn_name = dialog.conn_name_input.text()
            conn_string = dialog.conn_string_input.text()
            row_position = self.tabWidget.widget(1).conn_table.rowCount()
            self.tabWidget.widget(1).conn_table.insertRow(row_position)
            self.tabWidget.widget(1).conn_table.setItem(row_position, 0, QtWidgets.QTableWidgetItem(conn_name))
            self.tabWidget.widget(1).conn_table.setItem(row_position, 1, QtWidgets.QTableWidgetItem(conn_string))
            self.add_edit_buttons()
            self.save_connections_to_file()

    def open_edit_connection_dialog(self, row):
        dialog = EditConnectionDialog(self)
        conn_name = self.tabWidget.widget(1).conn_table.item(row, 0).text()
        conn_string = self.tabWidget.widget(1).conn_table.item(row, 1).text()
        dialog.conn_name_input.setText(conn_name)
        dialog.conn_string_input.setText(conn_string)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_conn_name = dialog.conn_name_input.text()
            new_conn_string = dialog.conn_string_input.text()
            self.edit_row(row, new_conn_name, new_conn_string)

    def save_connections_to_file(self):
        conn_table = self.tabWidget.widget(1).conn_table
        row_count = conn_table.rowCount()
        connections = []
        for row in range(row_count):
            conn_name = conn_table.item(row, 0).text()
            conn_string = conn_table.item(row, 1).text()
            connections.append(f"{conn_name},{conn_string}")
        with open('src/DB.txt', 'w') as file:
            file.write("\n".join(connections))

    def load_connections_from_file(self):
        conn_table = self.tabWidget.widget(1).conn_table
        if os.path.exists('src/DB.txt'):
            with open('src/DB.txt', 'r') as file:
                connections = file.readlines()
                for connection in connections:
                    conn_name, conn_string = connection.strip().split(',')
                    row_position = conn_table.rowCount()
                    conn_table.insertRow(row_position)
                    conn_table.setItem(row_position, 0, QtWidgets.QTableWidgetItem(conn_name))
                    conn_table.setItem(row_position, 1, QtWidgets.QTableWidgetItem(conn_string))
            self.add_edit_buttons()

    def create_custom_title_bar(self):
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        title_bar = QtWidgets.QWidget(self)
        title_bar.setObjectName("titleBar")
        title_bar_layout = QtWidgets.QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)

        # Add spacer to the left of the logo
        left_spacer = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        title_bar_layout.addItem(left_spacer)

        # Add logo to title bar
        logo_label = QtWidgets.QLabel(title_bar)
        logo_pixmap = QPixmap("src/images/logo.png").scaled(20, 20, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        logo_label.setPixmap(logo_pixmap)
        title_bar_layout.addWidget(logo_label)

        title_label = QtWidgets.QLabel("DiFFDB", title_bar)
        title_label.setObjectName("titleLabel")

        minimize_button = QtWidgets.QPushButton("_", title_bar)
        minimize_button.setObjectName("minimizeButton")
        minimize_button.clicked.connect(self.showMinimized)

        close_button = QtWidgets.QPushButton("X", title_bar)
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.close)

        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch()
        title_bar_layout.addWidget(minimize_button)
        title_bar_layout.addWidget(close_button)

        self.setMenuWidget(title_bar)

        # Enable window dragging
        title_bar.mousePressEvent = self.mousePressEvent
        title_bar.mouseMoveEvent = self.mouseMoveEvent

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def load_tabs(self):
        home_path = os.path.join(os.path.dirname(__file__), 'ui', 'home.ui')
        configurazione_path = os.path.join(os.path.dirname(__file__), 'ui', 'configurazione.ui')
        scelta_path = os.path.join(os.path.dirname(__file__), 'ui', 'scelta.ui')

        tab1 = uic.loadUi(home_path)
        tab2 = uic.loadUi(configurazione_path)
        if os.path.exists(scelta_path):
            tab3 = uic.loadUi(scelta_path)
        else:
            raise FileNotFoundError(f"The UI file was not found: {scelta_path}")

        icon_color = '#A9B7C6'  # Colore del testo

        self.tabWidget.insertTab(0, tab1, qta.icon('fa.home', color=icon_color), "Home")
        self.tabWidget.insertTab(1, tab2, qta.icon('fa.cog', color=icon_color), "Configurazione")
        self.tabWidget.insertTab(2, tab3, qta.icon('fa.database', color=icon_color), "Scelta")

        # Ensure tab1 has a layout
        if tab1.layout() is None:
            tab1.setLayout(QtWidgets.QVBoxLayout())

        # Set logo in Home tab
        logo_label = QtWidgets.QLabel(tab1)
        logo_pixmap = QPixmap("src/images/logo.png").scaled(100, 100, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        logo_label.setPixmap(logo_pixmap)
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        tab1.layout().addWidget(logo_label)

        # Connect buttons to functions
        tab2.add_conn_button.clicked.connect(self.open_add_connection_dialog)
        tab3.compare_button.clicked.connect(self.compare_environments)

        # Connect combo boxes to the update function
        tab3.comboBox1.currentIndexChanged.connect(self.update_compare_button_text)
        tab3.comboBox2.currentIndexChanged.connect(self.update_compare_button_text)
        
        # Initial update of the button text
        self.update_compare_button_text()

        # Load connections into combo boxes
        self.load_connections_into_comboboxes(tab3)

    def load_connections_into_comboboxes(self, tab):
        tab.comboBox1.clear()
        tab.comboBox2.clear()
        if os.path.exists('src/DB.txt'):
            with open('src/DB.txt', 'r') as file:
                connections = file.readlines()
                for connection in connections:
                    conn_name, conn_string = connection.strip().split(',')
                    tab.comboBox1.addItem(conn_name, conn_string)
                    tab.comboBox2.addItem(conn_name, conn_string)

    def update_compare_button_text(self):
        tab3 = self.tabWidget.widget(2)  # Assuming "Scelta" is the third tab (index 2)
        db1 = tab3.comboBox1.currentText()
        db2 = tab3.comboBox2.currentText()
        tab3.compare_button.setText(f"Compare {db1} vs {db2}")

    def on_tab_changed(self, index):
        # Refresh connections when switching to the "Scelta" tab
        if index == 2:  # Assuming "Scelta" is the third tab (index 2)
            self.load_connections_into_comboboxes(self.tabWidget.widget(2))

    def compare_svi_col(self):
        self.compare_environments('SVI', 'COL')

    def compare_col_pre(self):
        self.compare_environments('COL', 'PRE')

    def compare_svi_pre(self):
        self.compare_environments('SVI', 'PRE')
    
    def compare_environments(self):
        # Get connection strings from combo boxes
        oracle_conn_svi = self.tabWidget.widget(2).comboBox1.currentData()
        oracle_conn_col = self.tabWidget.widget(2).comboBox2.currentData()

        try:
            # Create engines and inspectors only when needed
            with create_engine(oracle_conn_svi).connect() as conn_svi, create_engine(oracle_conn_col).connect() as conn_col:
                inspector_svi = inspect(conn_svi)
                inspector_col = inspect(conn_col)

                table_diffs, view_diffs, synonym_diffs, sequence_diffs = compare_environments('SVI', oracle_conn_svi, 'COL', oracle_conn_col)

                # Generate SQL scripts and Excel report
                scripts = generate_sql_scripts(table_diffs, view_diffs, synonym_diffs, sequence_diffs)
                with open('script_mancanti.sql', 'w') as f:
                    for script_type in scripts:
                        f.write(f"-- {script_type.capitalize()} Scripts --\n")
                        for script in scripts[script_type]:
                            f.write(script + '\n')

                logging.info("Gli script SQL per gli oggetti mancanti sono stati generati e salvati in 'script_mancanti.sql'.")
                generate_excel_report(table_diffs, view_diffs, synonym_diffs, sequence_diffs, 'differenze_ambienti.xlsx')
        except sqlalchemy.exc.DatabaseError as e:
            logging.error(f"Database connection error: {e}")
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to connect to the database: {e}")