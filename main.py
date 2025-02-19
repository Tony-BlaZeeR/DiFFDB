import sys
import os
from PyQt5 import QtWidgets, QtGui
from main_window import MainWindow

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DiFFDB")  # Imposta il nome dell'applicazione
    app.setWindowIcon(QtGui.QIcon(os.path.join(os.path.dirname(__file__), 'images', 'logo.png')))  # Imposta l'icona della barra delle applicazioni
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()