# PyInstaller: eseguibile unico e portabile.
#   pyinstaller DiFFDB.spec        -> dist/DiFFDB.exe (Windows) / dist/DiFFDB (Linux, macOS)
#
# I file .ui/.qss/.png finiscono dentro il bundle; le connessioni restano invece
# accanto all'eseguibile (vedi src/paths.py), cosi' l'app e' davvero portable:
# la copi su una chiavetta insieme al suo connections.json e funziona.

import os

block_cipher = None

# Su Windows PyInstaller vuole un .ico. Se non c'e', si costruisce senza icona
# invece di far fallire la build (per generarlo: vedi README, sezione Build).
icon = "images/logo.ico" if os.path.exists("images/logo.ico") else None

datas = [
    ("ui", "ui"),
    ("styles", "styles"),
    ("images", "images"),
]

# I driver DB sono importati dinamicamente da SQLAlchemy: vanno dichiarati a mano.
# Togli quelli che non ti servono per alleggerire l'eseguibile.
hiddenimports = [
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.mysql",
    "sqlalchemy.dialects.oracle",
    "sqlalchemy.dialects.mssql",
    "sqlalchemy.dialects.sqlite",
    "psycopg2",
    "pymysql",
    "oracledb",   # thin mode: nessun Instant Client da installare
    "pymssql",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # PyQt5 va escluso esplicitamente: se resta installato sulla macchina,
    # PyInstaller lo impacchetterebbe accanto a PySide6 e i due binding Qt
    # nello stesso processo fanno crashare l'applicazione all'avvio.
    excludes=["PyQt5", "tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="DiFFDB",
    debug=False,
    strip=False,
    upx=True,
    console=False,  # niente finestra nera all'avvio
    icon=icon,
)
