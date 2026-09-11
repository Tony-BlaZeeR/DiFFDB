"""Avvio dai sorgenti: `python main.py`.

Il codice vero sta in diffdb/app.py, che e' anche l'entry point del comando
`diffdb-gui` installato con pip. Questo file resta per comodita' di chi lavora
dal repository e perche' e' quello che PyInstaller impacchetta.
"""

import sys

from diffdb.app import main

if __name__ == "__main__":
    sys.exit(main())
