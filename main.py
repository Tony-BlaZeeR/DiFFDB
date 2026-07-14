import logging
import sys

import src  # noqa: F401  (fissa il binding Qt prima di qualunque import di qtawesome/qtpy)
from src.main_window import MainWindow
from src.paths import resource_path
from src.qt import QtGui, QtWidgets


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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
