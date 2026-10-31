import os

__version__ = "1.3.0"

# qtawesome passa da qtpy, che sceglie il binding Qt da solo: senza questa riga,
# se sulla macchina c'e' ancora PyQt5, il processo caricherebbe due binding
# diversi nello stesso interprete e crasherebbe.
os.environ.setdefault("QT_API", "pyside6")
