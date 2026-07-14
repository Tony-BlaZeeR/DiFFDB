"""Percorsi di risorse e configurazione.

Funzionano sia da sorgente sia dentro un eseguibile PyInstaller, dove i file
.ui/.qss/.png stanno in una cartella temporanea (sys._MEIPASS) e la config
deve invece restare accanto all'eseguibile.
"""

import os
import sys
from pathlib import Path

APP_NAME = "DiFFDB"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_path(*parts: str) -> str:
    """Risorsa read-only inclusa nel bundle (ui/, styles/, images/)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base.joinpath(*parts))


def app_dir() -> Path:
    """Cartella dell'eseguibile (build) o radice del progetto (sorgente)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def config_dir() -> Path:
    """DIFFDB_HOME, altrimenti accanto all'eseguibile (portable), altrimenti cartella utente."""
    override = os.environ.get("DIFFDB_HOME")
    if override:
        target = Path(override)
    else:
        target = app_dir() if _is_writable(app_dir()) else user_config_dir()

    target.mkdir(parents=True, exist_ok=True)
    return target


def connections_file() -> Path:
    return config_dir() / "connections.json"


def legacy_text_files():
    """Vecchi file in formato testo, letti una volta sola per migrare le voci."""
    return [
        config_dir() / "connections.txt",
        app_dir() / "config" / "DB.txt",
        Path(resource_path("config", "DB.txt")),
    ]


def _is_writable(path: Path) -> bool:
    probe = path / ".diffdb_write_test"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False
