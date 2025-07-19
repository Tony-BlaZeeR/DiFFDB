import os
from PyQt5 import QtWidgets, uic

class AddConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(AddConnectionDialog, self).__init__(parent)
        ui_path = os.path.join(os.path.dirname(__file__), '..', 'ui', 'add_connection.ui')
        uic.loadUi(ui_path, self)
        self.add_button.clicked.connect(self.accept)

class EditConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(EditConnectionDialog, self).__init__(parent)
        ui_path = os.path.join(os.path.dirname(__file__), '..', 'ui', 'edit_connection.ui')
        uic.loadUi(ui_path, self)
        self.edit_button.clicked.connect(self.accept)