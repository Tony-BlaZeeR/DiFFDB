"""Controllo aggiornamenti: chiede a GitHub qual e' l'ultima release.

Non parte mai da solo. Lo decide l'utente - il pulsante "Controlla" nel dialog
Info, o una preferenza opt-in spenta di default. DiFFDB e' pensato anche per
reti chiuse e per il confronto offline (vedi snapshot_io.py): una chiamata di
rete non richiesta sarebbe fuori posto, e in certi ambienti un problema.

Qui c'e' solo: come si confrontano due versioni, e come si legge l'ultima
release. La parte di interfaccia (thread, banner) sta in about_dialog.py.
"""

import json
import urllib.request

from diffdb import __version__

REPO = "Tony-BlaZeeR/DiFFDB"
API_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGINA_RELEASE = f"https://github.com/{REPO}/releases/latest"


def _numeri(versione: str) -> tuple[int, ...]:
    """'v1.3.0' / '1.3.0' -> (1, 3, 0). I suffissi tipo '-rc1' si ignorano.

    Un confronto fra stringhe direbbe che '1.10.0' < '1.9.0': serve confrontare
    numero per numero.
    """
    pulita = versione.strip().lstrip("vV")
    numeri = []
    for parte in pulita.split("."):
        cifre = ""
        for carattere in parte:
            if carattere.isdigit():
                cifre += carattere
            else:
                break   # si ferma al primo non-numero: '0-rc1' -> 0
        numeri.append(int(cifre) if cifre else 0)
    return tuple(numeri)


def e_piu_recente(remota: str, corrente: str = __version__) -> bool:
    """Vero se `remota` e' piu' nuova di `corrente` (confronto numerico)."""
    return _numeri(remota) > _numeri(corrente)


def ultima_release(timeout: float = 6.0) -> str:
    """Il tag dell'ultima release pubblicata (es. 'v1.3.0').

    Solleva in caso di rete assente, timeout o risposta inattesa: chi chiama
    traduce l'errore in "impossibile controllare", senza bloccare l'app.
    """
    richiesta = urllib.request.Request(
        API_ULTIMA,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "DiFFDB"})
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:  # noqa: S310
        dati = json.load(risposta)
    tag = dati.get("tag_name")
    if not tag:
        raise ValueError("risposta di GitHub senza 'tag_name'")
    return str(tag)
