"""Punto unico di accesso a Qt.

Il progetto usa PySide6 (LGPL): PyQt5 e' GPL/commerciale e non si concilia con la
licenza MIT dell'applicazione.
"""

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
from PySide6.QtCore import QFile, QIODevice, QObject, Qt, QThread, Signal  # noqa: F401
from PySide6.QtUiTools import QUiLoader

__all__ = [
    "QtCore", "QtGui", "QtWidgets", "Qt", "QObject", "QThread", "Signal",
    "load_ui", "bind_children",
]


def load_ui(path: str, parent=None):
    """Carica un file .ui di Qt Designer e ne restituisce il widget."""
    loader = QUiLoader()
    ui_file = QFile(path)
    if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise FileNotFoundError(f"File .ui non trovato o illeggibile: {path}")
    try:
        widget = loader.load(ui_file, parent)
    finally:
        ui_file.close()

    if widget is None:
        raise RuntimeError(f"Impossibile caricare {path}: {loader.errorString()}")

    bind_children(widget, widget)
    return widget


def bind_children(source, target) -> None:
    """Espone i figli come attributi (tab.comboBox1, dialog.conn_name_input, ...).

    QUiLoader, a differenza di uic.loadUi di PyQt5, non lo fa da solo.
    """
    for child in source.findChildren(QObject):
        name = child.objectName()
        if name and not hasattr(target, name):
            setattr(target, name, child)
