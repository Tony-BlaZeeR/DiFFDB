from PyQt5 import QtWidgets, uic

from src.paths import resource_path


class AddConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(AddConnectionDialog, self).__init__(parent)
        uic.loadUi(resource_path("ui", "add_connection.ui"), self)
        self.add_button.clicked.connect(self.accept)


class EditConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(EditConnectionDialog, self).__init__(parent)
        uic.loadUi(resource_path("ui", "edit_connection.ui"), self)
        self.edit_button.clicked.connect(self.accept)
