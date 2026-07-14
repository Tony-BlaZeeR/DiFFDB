"""Dialog di inserimento e modifica di una connessione."""

from typing import Optional

from src.connections import Connection
from src.paths import resource_path
from src.qt import QtWidgets, load_ui


def ask_connection(parent, connection: Optional[Connection] = None) -> Optional[Connection]:
    """Apre il dialog e restituisce la connessione, o None se l'utente annulla."""
    editing = connection is not None
    ui_file = "edit_connection.ui" if editing else "add_connection.ui"
    dialog = load_ui(resource_path("ui", ui_file), parent)

    button = dialog.edit_button if editing else dialog.add_button
    button.clicked.connect(dialog.accept)

    if editing:
        dialog.conn_name_input.setText(connection.name)
        dialog.conn_string_input.setText(connection.conn_string)
        dialog.schema_input.setText(connection.schema or "")

    while dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        name = dialog.conn_name_input.text().strip()
        conn_string = dialog.conn_string_input.text().strip()
        schema = dialog.schema_input.text().strip() or None

        if name and conn_string:
            return Connection(name=name, conn_string=conn_string, schema=schema)

        QtWidgets.QMessageBox.warning(
            dialog, "Dati mancanti", "Nome e stringa di connessione sono obbligatori."
        )

    return None
