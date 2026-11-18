"""Avvio dai sorgenti: `python main.py`.

Il codice vero sta in diffdb/app.py, che e' anche l'entry point del comando
`diffdb-gui` installato con pip. Questo file resta per comodita' di chi lavora
dal repository e perche' e' quello che PyInstaller impacchetta.
"""

import sys

if __name__ == "__main__":
    # `--selftest` controlla che i driver DB siano davvero dentro il bundle e
    # esce: lo usa la CI sull'eseguibile appena costruito. Va intercettato
    # prima di importare diffdb.app, cosi' non serve ne' Qt ne' un display.
    if "--selftest" in sys.argv[1:]:
        from diffdb.selftest import esegui

        sys.exit(esegui())

    from diffdb.app import main

    sys.exit(main())
