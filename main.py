import logging
import sys

from PyQt5 import QtGui, QtWidgets

from src.main_window import MainWindow
from src.paths import resource_path


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DiFFDB")
    app.setWindowIcon(QtGui.QIcon(resource_path("images", "logo.png")))

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
