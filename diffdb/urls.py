"""Connection string: risoluzione dei segreti, mascheramento, policy.

Un solo posto per tutto quello che riguarda le password dentro un URL, perche'
un segreto custodito bene e poi stampato in un log e' un segreto perso.

Nella stringa salvata la password non e' mai scritta: ci sta un riferimento.

    postgresql+psycopg2://app:${keyring}@host:5432/db     portachiavi di sistema
    postgresql+psycopg2://app:${PROD_DB_PWD}@host:5432/db variabile d'ambiente

Il portachiavi e' il default per chi lavora da una postazione; la variabile
d'ambiente serve dove un portachiavi non c'e' (CI, container), dove a custodire
il segreto e' il secret store della pipeline.
"""

import logging
import os
import re
from pathlib import PurePath
from urllib.parse import quote

from diffdb import keystore

logger = logging.getLogger(__name__)

KEYRING_TOKEN = "${keyring}"

# Sostituito prima dell'espansione delle variabili e ripristinato dopo: cosi'
# una password che contiene '$' non viene interpretata a sua volta.
_SEGNAPOSTO = "\x00diffdb-keyring\x00"

# Riferimento a un segreto esterno: ${VAR}, %VAR% o ${keyring}.
_RIFERIMENTO = re.compile(r"\$\{[^}]*\}|\$\w+|%\w+%")

VARIABILE_POLICY = "DIFFDB_REQUIRE_SECRET_REFS"


class PasswordInChiaro(ValueError):
    """La policy vieta le password scritte nel file delle connessioni."""


def expand(conn_str: str, name: str | None = None) -> str:
    """URL pronto per connettersi, con i segreti risolti.

    `name` e' il nome della connessione: identifica la voce nel portachiavi.
    """
    grezzo = (conn_str or "").strip()
    _controlla_policy(grezzo, name)

    segreto = None
    if KEYRING_TOKEN in grezzo:
        segreto = keystore.richiedi(name)
        grezzo = grezzo.replace(KEYRING_TOKEN, _SEGNAPOSTO)

    risolto = os.path.expandvars(grezzo)

    if segreto is not None:
        # La password arriva dal portachiavi in chiaro: va codificata, altrimenti
        # una '@' o una '/' spezzerebbero l'URL.
        risolto = risolto.replace(_SEGNAPOSTO, quote(segreto, safe=""))
    return risolto


def mask_password(conn_string: str) -> str:
    """Nasconde la password in una connection string.

    Da usare ovunque l'URL esca dal processo: interfaccia, log, messaggi
    d'errore, snapshot salvati.
    """
    if not conn_string or "://" not in conn_string or "@" not in conn_string:
        return conn_string
    if password_letterale(conn_string) is None:
        # E' gia' un riferimento (${keyring}, ${VAR}): non e' un segreto, e
        # vederlo dice all'utente dove sta davvero la password.
        return conn_string
    scheme, rest = conn_string.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def sanitize(testo: str) -> str:
    """Maschera ogni connection string dentro un testo libero.

    I driver mettono l'URL completo nei messaggi d'errore, e quei messaggi
    finiscono nei log e nelle finestre di dialogo.
    """
    if not testo:
        return testo
    # La '@' finale fa parte del pezzo riconosciuto: e' quella che mask_password
    # usa per separare le credenziali dall'host.
    return re.sub(r"[a-zA-Z0-9+_.-]+://[^\s'\"]*:[^\s'\"@]*@",
                  lambda m: mask_password(m.group(0)), testo)


def descrizione(conn_string: str, schema: str | None = None) -> str:
    """Dialetto, host e database in forma breve, senza credenziali.

    Serve a dire a colpo d'occhio *cosa* si sta per toccare: scambiare PRE con
    PROD e' un clic, e il solo nome della connessione non lo impedisce.
    """
    try:
        from sqlalchemy.engine import make_url

        url = make_url((conn_string or "").strip())
    except Exception:
        return ""

    posizione = url.host or ""
    if url.database:
        # Per SQLite il "database" e' un percorso: ne basta il nome del file.
        nome = url.database if url.host else PurePath(url.database).name
        posizione = f"{posizione}/{nome}" if posizione else nome

    parti = [p for p in (url.get_backend_name(), posizione) if p]
    if schema:
        parti.append(f"schema {schema}")
    return " · ".join(parti)


def password_letterale(conn_string: str) -> str | None:
    """La password scritta in chiaro nella stringa, se c'e'.

    Un riferimento (`${...}`, `%VAR%`) non e' una password in chiaro.
    """
    if not conn_string or "://" not in conn_string or "@" not in conn_string:
        return None
    _, rest = conn_string.split("://", 1)
    credentials = rest.split("@", 1)[0]
    if ":" not in credentials:
        return None
    password = credentials.split(":", 1)[1]
    if not password or _RIFERIMENTO.fullmatch(password):
        return None
    return password


def policy_attiva() -> bool:
    return os.environ.get(VARIABILE_POLICY, "").strip().lower() in ("1", "true", "si", "yes")


def _controlla_policy(conn_str: str, name: str | None) -> None:
    if password_letterale(conn_str) is None:
        return

    etichetta = f"'{name}'" if name else "una connessione"
    if policy_attiva():
        raise PasswordInChiaro(
            f"La connessione {etichetta} ha la password scritta in chiaro e "
            f"{VARIABILE_POLICY} e' attiva. Usa ${{keyring}} "
            f"(python -m diffdb.cli --set-password {name or '<nome>'}) oppure ${{VARIABILE}}."
        )
    logger.warning(
        "La connessione %s ha la password scritta in chiaro nel file. "
        "Meglio ${keyring} o ${VARIABILE}.", etichetta)
