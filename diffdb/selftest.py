"""Autodiagnosi dei driver impacchettati: `DiFFDB --selftest`.

Serve in CI, sull'eseguibile appena costruito. Da sorgente questi import
riescono sempre, percio' un normale test con pytest resta verde anche quando
l'eseguibile e' rotto: i driver importano i loro moduli dall'interno di
estensioni compilate (thin_impl, _rust) e l'analisi statica di PyInstaller
non vede quegli import, quindi non li impacchetta.

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
    # L'export Excel. pandas non parte senza numpy, e un numpy impacchettato
    # a meta' lo faceva fallire con "Unable to import required dependencies":
    # l'app lo riportava come "manca pandas" e consigliava un pip install che
    # non serviva. Da sorgente non si vedeva, come per i driver.
    ("numpy", "calcolo per il report Excel"),
    ("pandas", "report Excel"),
    ("openpyxl", "scrittura del file .xlsx"),
]

# Driver che su una piattaforma sono assenti di proposito: qui l'assenza e'
# l'esito giusto, non un guasto. Il motivo sta accanto, cosi' il report si
# spiega da solo a chi lo legge in CI; i dettagli sono in DiFFDB.spec.
NON_ATTESI: dict[str, dict[str, str]] = {
    "darwin": {
        "pymssql": (
            "escluso dal bundle macOS: il wheel spedisce OpenSSL x86_64 che "
            "collide con quella arm64 di psycopg2 e rompe ssl e oracledb"
        ),
    },
}


def esegui() -> int:
    """Importa i driver attesi su questa piattaforma e riporta cosa manca.

    Ritorna 0 se e' tutto a posto. Il report va sia su stdout sia su un file,
    perche' su Windows l'eseguibile e' costruito senza console
    (`console=False`) e quello che stampa non arriva da nessuna parte: in CI
    si legge il file.
    """
    esclusi = NON_ATTESI.get(sys.platform, {})
    righe: list[str] = []
    mancanti: list[str] = []
    attesi = 0

    for nome, scopo in MODULI:
        if nome in esclusi:
            righe.append(f"salto   {nome}  ({scopo}): {esclusi[nome]}")
            continue

        attesi += 1
        try:
            importlib.import_module(nome)
        except Exception as errore:  # ImportError, ma anche errori di init
            mancanti.append(nome)
            righe.append(f"MANCA  {nome}  ({scopo}): {errore!r}")
        else:
            righe.append(f"ok     {nome}  ({scopo})")

    righe.append("")
    if mancanti:
        righe.append(
            f"Autodiagnosi FALLITA: {len(mancanti)} modulo/i non disponibili "
            f"nell'eseguibile ({', '.join(mancanti)}). "
            "Vanno aggiunti alla raccolta in DiFFDB.spec."
        )
    else:
        righe.append(f"Autodiagnosi OK: {attesi} moduli disponibili.")

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
