"""Avvio dell'interfaccia grafica.

Sta dentro il pacchetto e non in un main.py alla radice perche' e' l'entry point
dichiarato in pyproject.toml: installando DiFFDB con pip si ottiene il comando
`diffdb-gui`, e chi lancia dai sorgenti usa il `main.py` che chiama questo.
"""

import logging
import sys

import diffdb  # noqa: F401  (fissa il binding Qt prima di qualunque import di qtawesome/qtpy)
from diffdb import i18n, log, preferences, theme
from diffdb.paths import resource_path
from diffdb.qt import QtGui, QtWidgets


def main() -> int:
    """Prepara log, lingua e finestra, poi entra nel ciclo degli eventi."""
    # Su file, con rotazione: dentro un eseguibile GUI stderr non lo legge nessuno.
    percorso_log = log.configure(
        formato_console="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if percorso_log:
        logging.getLogger(__name__).info("Log applicativo in '%s'.", percorso_log)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DiFFDB")
    app.setApplicationVersion(diffdb.__version__)
    app.setOrganizationName("DiFFDB")

    # Prima di costruire qualunque widget: le stringhe si traducono quando
    # vengono create, non dopo.
    i18n.installa(app)

    # Font e tavolozza prima dei widget: lo stile e' dell'applicazione, cosi'
    # vale anche per le finestre di dialogo native.
    theme.applica(app, preferences.variante(), preferences.tema(), preferences.accento())
    app.setWindowIcon(QtGui.QIcon(resource_path("images", "logo.png")))

    try:
        from diffdb.main_window import MainWindow

        finestra = MainWindow()
        finestra.show()
        return app.exec()
    except Exception:
        logging.exception("Avvio dell'applicazione fallito")
        return 1


if __name__ == "__main__":
    sys.exit(main())
