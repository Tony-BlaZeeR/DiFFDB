"""Password nel portachiavi del sistema operativo.

Cifrare il file delle connessioni non risolverebbe niente: la chiave finirebbe
accanto al file cifrato. La risposta e' non custodire il segreto — lo tiene il
sistema operativo, legato all'account utente:

- Windows: Credential Manager (DPAPI)
- macOS:   Keychain
- Linux:   Secret Service (GNOME Keyring, KWallet)

Un `connections.json` copiato su un'altra macchina non contiene piu' niente di
utile: dentro c'e' solo il segnaposto `${keyring}`.

Il portachiavi non c'e' sempre (un runner di CI non ne ha uno): li' si continua
a usare `${VAR}` con il secret store della pipeline. Per questo l'import di
`keyring` e' opzionale e l'assenza non e' un errore finche' nessuno lo usa.
"""

import logging

logger = logging.getLogger(__name__)

SERVIZIO = "DiFFDB"

try:  # pragma: no cover - dipende da cosa e' installato sulla macchina
    import keyring as _keyring
    from keyring.errors import KeyringError as _KeyringError
except ImportError:  # pragma: no cover
    _keyring = None

    class _KeyringError(Exception):
        pass


class KeystoreNonDisponibile(RuntimeError):
    """Il portachiavi non e' utilizzabile su questa macchina."""


def disponibile() -> bool:
    """Vero se si puo' leggere e scrivere nel portachiavi.

    Non basta che il pacchetto sia installato: su un server headless `keyring`
    ripiega su un backend che non sa conservare niente, ed e' meglio saperlo
    prima di salvare una password che poi non si rilegge.
    """
    if _keyring is None:
        return False
    try:
        backend = _keyring.get_keyring()
    except _KeyringError as exc:  # pragma: no cover
        logger.debug("Portachiavi non interrogabile: %s", exc)
        return False
    return "fail" not in type(backend).__name__.lower()


def descrizione() -> str:
    """Nome del backend, per dirlo all'utente invece di un generico errore."""
    if _keyring is None:
        return "il pacchetto 'keyring' non e' installato"
    try:
        return type(_keyring.get_keyring()).__name__
    except _KeyringError as exc:  # pragma: no cover
        return f"portachiavi non interrogabile ({exc})"


def leggi(nome: str) -> str | None:
    if not disponibile():
        return None
    try:
        return _keyring.get_password(SERVIZIO, nome)
    except _KeyringError as exc:
        logger.warning("Lettura dal portachiavi fallita per '%s': %s", nome, exc)
        return None


def richiedi(nome: str | None) -> str:
    """Password della connessione, o un errore che dice cosa fare.

    Usata al momento di connettersi: qui un fallimento deve fermarsi subito e in
    modo comprensibile, non degradare in un errore di autenticazione oscuro.
    """
    if not nome:
        raise KeystoreNonDisponibile(
            "${keyring} si puo' usare solo in una connessione con un nome.")
    if not disponibile():
        raise KeystoreNonDisponibile(
            f"La connessione '{nome}' usa ${{keyring}} ma il portachiavi non e' "
            f"utilizzabile: {descrizione()}."
        )
    password = leggi(nome)
    if password is None:
        raise KeystoreNonDisponibile(
            f"Nel portachiavi non c'e' nessuna password per '{nome}'. "
            f"Impostala con: python -m diffdb.cli --set-password {nome}"
        )
    return password


def scrivi(nome: str, password: str) -> None:
    if not disponibile():
        raise KeystoreNonDisponibile(f"Portachiavi non utilizzabile: {descrizione()}.")
    try:
        _keyring.set_password(SERVIZIO, nome, password)
    except _KeyringError as exc:
        raise KeystoreNonDisponibile(f"Scrittura nel portachiavi fallita: {exc}") from exc
    # A dirlo all'utente ci pensa il chiamante: qui resta solo la traccia nel log.
    logger.debug("Password di '%s' salvata nel portachiavi di sistema.", nome)


def elimina(nome: str) -> bool:
    """Toglie la voce dal portachiavi. Vero se c'era qualcosa da togliere."""
    if not disponibile() or leggi(nome) is None:
        return False
    try:
        _keyring.delete_password(SERVIZIO, nome)
    except _KeyringError as exc:  # pragma: no cover
        logger.warning("Rimozione dal portachiavi fallita per '%s': %s", nome, exc)
        return False
    return True
