# PyInstaller: eseguibile unico e portabile.
#   pyinstaller DiFFDB.spec        -> dist/DiFFDB.exe (Windows) / dist/DiFFDB (Linux, macOS)
#
# I file .ui/.qss/.png finiscono dentro il bundle; le connessioni restano invece
# accanto all'eseguibile (vedi src/paths.py), cosi' l'app e' davvero portable:
# la copi su una chiavetta insieme al suo connections.json e funziona.

import os
import sys

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Su Windows PyInstaller vuole un .ico. Se non c'e', si costruisce senza icona
# invece di far fallire la build (per generarlo: vedi README, sezione Build).
icon = "diffdb/images/logo.ico" if os.path.exists("diffdb/images/logo.ico") else None

# Le risorse stanno dentro il pacchetto: nel bundle vanno nella stessa
# posizione, perche' diffdb/paths.py le cerca sotto _MEIPASS/diffdb.
datas = [
    ("diffdb/ui", "diffdb/ui"),
    ("diffdb/styles", "diffdb/styles"),
    ("diffdb/fonts", "diffdb/fonts"),
    ("diffdb/images", "diffdb/images"),
    # Solo i cataloghi compilati: i .ts sono i sorgenti della traduzione.
    # Vanno rigenerati prima della build (vedi README, sezione Traduzioni).
    ("diffdb/translations/*.qm", "diffdb/translations"),
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

# oracledb (thin mode) e cryptography importano moduli dall'interno delle loro
# estensioni compilate (thin_impl*.pyd, _rust.pyd): essendo codice C/Cython,
# l'analisi statica di PyInstaller non vede quegli import e non li impacchetta.
# Senza, la connessione Oracle fallisce a runtime: prima "DPY-3016 ...
# cryptography package is not installed", poi ModuleNotFoundError su moduli
# standard (uuid, secrets, getpass, ...) che thin_impl importa. Li raccogliamo
# a mano. Verificato su build frozen: la connessione arriva fino al socket.
crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all("cryptography")
oracle_datas, oracle_binaries, oracle_hiddenimports = collect_all("oracledb")
datas += crypto_datas + oracle_datas
hiddenimports += crypto_hiddenimports + oracle_hiddenimports
# Stdlib importati da dentro le estensioni compilate di oracledb (invisibili
# all'analisi statica): li elenchiamo esplicitamente.
hiddenimports += [
    "array", "asyncio", "base64", "collections", "datetime", "decimal",
    "getpass", "hashlib", "hmac", "json", "platform", "queue", "random",
    "secrets", "ssl", "struct", "subprocess", "uuid", "xml.dom.minidom",
]
collected_binaries = crypto_binaries + oracle_binaries

# PyQt5 va escluso esplicitamente: se resta installato sulla macchina,
# PyInstaller lo impacchetterebbe accanto a PySide6 e i due binding Qt nello
# stesso processo fanno crashare l'applicazione all'avvio.
excludes = ["PyQt5", "tkinter", "matplotlib", "pytest"]

# Su macOS pymssql va tolto, e non per scelta: il suo wheel si dichiara
# universal2 e i suoi moduli lo sono, ma le OpenSSL che si porta dietro
# (pymssql/.dylibs/libssl.3.dylib) sono solo x86_64. PyInstaller appiattisce
# tutte le dylib nella radice del bundle, dove quel nome collide con la
# libssl.3.dylib arm64 di psycopg2: vince quella x86_64 e rompe psycopg2, il
# modulo ssl della stdlib e di conseguenza oracledb, che su ssl si appoggia.
# Su macOS arm64 pymssql non riesce a caricarsi comunque, quindi togliendolo
# si perde una cosa che non funzionava e si recuperano PostgreSQL e Oracle.
# Da rivedere quando il wheel a monte spedira' OpenSSL arm64.
if sys.platform == "darwin":
    hiddenimports.remove("pymssql")
    excludes.append("pymssql")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=collected_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
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

# Su macOS l'eseguibile nudo non basta: Finder e Gatekeeper si aspettano un
# bundle .app. Si costruisce attorno allo stesso EXE, con l'icona .icns
# (generata in CI dal PNG) quando c'e'. La versione per l'Info.plist arriva
# dall'ambiente, cosi' combacia con quella del tag.
if sys.platform == "darwin":
    icns = "diffdb/images/logo.icns" if os.path.exists("diffdb/images/logo.icns") else None
    app = BUNDLE(
        exe,
        name="DiFFDB.app",
        icon=icns,
        bundle_identifier="com.tony-blazeer.diffdb",
        info_plist={
            "CFBundleShortVersionString": os.environ.get("DIFFDB_VERSION", "0.0.0"),
            "CFBundleVersion": os.environ.get("DIFFDB_VERSION", "0.0.0"),
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.developer-tools",
        },
    )
