"""Autodiagnosi dei driver impacchettati: `DiFFDB --selftest`.

Serve in CI, sull'eseguibile appena costruito. Da sorgente questi import
riescono sempre, percio' un normale test con pytest resta verde anche quando
l'eseguibile e' rotto: i driver importano i loro moduli dall'interno di
estensioni compilate (thin_impl.pyd, _rust.pyd) e l'analisi statica di
PyInstaller non vede quegli import, quindi non li impacchetta.

E' il controllo che avrebbe intercettato il DPY-3016 ("cryptography package is
not installed") prima della 1.4.0, invece di farlo scoprire a chi installava.

Non apre nessuna connessione: non serve un database, e in CI non ci sono
tempi di attesa ne' esiti variabili.
"""

from __future__ import annotations

import importlib
import sys

NOME_REPORT = "selftest-report.txt"

# Modulo da importare -> a cosa serve (compare nel report).
MODULI: list[tuple[str, str]] = [
    ("sqlalchemy", "motore SQL"),
    ("psycopg2", "driver PostgreSQL"),
    ("pymysql", "driver MySQL"),
    ("oracledb", "driver Oracle (thin)"),
    ("pymssql", "driver SQL Server"),
    # oracledb thin cifra l'handshake di autenticazione con cryptography, ma lo
    # importa solo quando apre la connessione: senza queste due righe il bundle
    # sembra sano e poi fallisce con DPY-3016 davanti all'utente.
    ("cryptography", "cifratura per Oracle thin"),
    ("cryptography.hazmat.bindings._rust", "estensione nativa di cryptography"),
]


def esegui() -> int:
    """Importa ogni driver e riporta cosa manca. Ritorna 0 se e' tutto a posto.

    Il report va sia su stdout sia su un file, perche' su Windows
    l'eseguibile e' costruito senza console (`console=False`) e quello che
    stampa non arriva da nessuna parte: in CI si legge il file.
    """
    righe: list[str] = []
    mancanti: list[str] = []

    for nome, scopo in MODULI:
        try:
            importlib.import_module(nome)
        except Exception as errore:  # ImportError, ma anche errori di init
            mancanti.append(nome)
            righe.append(f"MANCA  {nome}  ({scopo}): {errore!r}")
        else:
            righe.append(f"ok     {nome}  ({scopo})")

    if mancanti:
        righe.append("")
        righe.append(
            f"Autodiagnosi FALLITA: {len(mancanti)} modulo/i non disponibili "
            f"nell'eseguibile ({', '.join(mancanti)}). "
            "Vanno aggiunti alla raccolta in DiFFDB.spec."
        )
    else:
        righe.append("")
        righe.append(f"Autodiagnosi OK: {len(MODULI)} moduli disponibili.")

    report = "\n".join(righe)
    print(report)
    try:
        with open(NOME_REPORT, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    except OSError:
        # Il report su file e' una comodita' per la CI: se la cartella non e'
        # scrivibile, l'esito (codice di uscita) resta comunque valido.
        pass

    return 1 if mancanti else 0


if __name__ == "__main__":
    sys.exit(esegui())
