"""Preferenze dell'interfaccia: lingua, geometria della finestra, ultima cartella.

Stanno in un `diffdb.ini` accanto a `connections.json`, non nel registro di
Windows: l'applicazione e' pensata per essere portabile, e portabile vuol dire
che tutto quello che la riguarda si copia insieme a lei. Anche `DIFFDB_HOME`
continua a funzionare.
"""


from diffdb.paths import config_dir
from diffdb.qt import QtCore

NOME_FILE = "diffdb.ini"

CHIAVE_LINGUA = "interfaccia/lingua"
CHIAVE_CARTELLA_OUTPUT = "percorsi/cartella_output"

# Dimensione e posizione in chiaro invece del blob di saveGeometry(): su una
# finestra senza cornice restoreGeometry() dice di aver funzionato e non
# funziona, e un .ini leggibile e' comunque piu' in linea con un'app portabile.
CHIAVE_LARGHEZZA = "interfaccia/larghezza"
CHIAVE_ALTEZZA = "interfaccia/altezza"
CHIAVE_X = "interfaccia/x"
CHIAVE_Y = "interfaccia/y"
CHIAVE_MASSIMIZZATA = "interfaccia/massimizzata"

# "auto" = come la lingua del sistema operativo.
LINGUA_AUTOMATICA = "auto"
LINGUE = {
    LINGUA_AUTOMATICA: "Come il sistema",
    "it": "Italiano",
    "en": "English",
}


def impostazioni() -> QtCore.QSettings:
    return QtCore.QSettings(str(config_dir() / NOME_FILE),
                            QtCore.QSettings.Format.IniFormat)


def lingua() -> str:
    return str(impostazioni().value(CHIAVE_LINGUA, LINGUA_AUTOMATICA))


def imposta_lingua(codice: str) -> None:
    impostazioni().setValue(CHIAVE_LINGUA, codice)


def geometria() -> dict | None:
    """Dimensione, posizione e stato della finestra, o None se non c'e' niente."""
    valori = impostazioni()
    larghezza = valori.value(CHIAVE_LARGHEZZA)
    altezza = valori.value(CHIAVE_ALTEZZA)
    if larghezza is None or altezza is None:
        return None
    try:
        return {
            "larghezza": int(larghezza),
            "altezza": int(altezza),
            "x": int(valori.value(CHIAVE_X, 0)),
            "y": int(valori.value(CHIAVE_Y, 0)),
            "massimizzata": str(valori.value(CHIAVE_MASSIMIZZATA, "false")).lower() == "true",
        }
    except (TypeError, ValueError):
        return None   # file scritto a mano e rovinato: si riparte dai valori di default


def imposta_geometria(larghezza: int, altezza: int, x: int, y: int,
                      massimizzata: bool) -> None:
    valori = impostazioni()
    valori.setValue(CHIAVE_LARGHEZZA, int(larghezza))
    valori.setValue(CHIAVE_ALTEZZA, int(altezza))
    valori.setValue(CHIAVE_X, int(x))
    valori.setValue(CHIAVE_Y, int(y))
    valori.setValue(CHIAVE_MASSIMIZZATA, "true" if massimizzata else "false")
    valori.sync()


CHIAVE_ULTIMO_CONFRONTO = "ultimo_confronto"


def ultimo_confronto() -> dict | None:
    """L'ultimo confronto eseguito, per riproporlo dalla schermata iniziale."""
    valori = impostazioni()
    riferimento = valori.value(f"{CHIAVE_ULTIMO_CONFRONTO}/riferimento")
    da_allineare = valori.value(f"{CHIAVE_ULTIMO_CONFRONTO}/da_allineare")
    if not riferimento or not da_allineare:
        return None
    try:
        differenze = int(valori.value(f"{CHIAVE_ULTIMO_CONFRONTO}/differenze", 0))
    except (TypeError, ValueError):
        differenze = 0
    return {
        "riferimento": str(riferimento),
        "da_allineare": str(da_allineare),
        "differenze": differenze,
        "quando": str(valori.value(f"{CHIAVE_ULTIMO_CONFRONTO}/quando", "")),
    }


def imposta_ultimo_confronto(riferimento: str, da_allineare: str, differenze: int,
                             quando: str) -> None:
    valori = impostazioni()
    valori.setValue(f"{CHIAVE_ULTIMO_CONFRONTO}/riferimento", riferimento)
    valori.setValue(f"{CHIAVE_ULTIMO_CONFRONTO}/da_allineare", da_allineare)
    valori.setValue(f"{CHIAVE_ULTIMO_CONFRONTO}/differenze", int(differenze))
    valori.setValue(f"{CHIAVE_ULTIMO_CONFRONTO}/quando", quando)
    valori.sync()


def cartella_output(predefinita: str = "") -> str:
    return str(impostazioni().value(CHIAVE_CARTELLA_OUTPUT, predefinita) or predefinita)


def imposta_cartella_output(percorso: str) -> None:
    impostazioni().setValue(CHIAVE_CARTELLA_OUTPUT, percorso)
