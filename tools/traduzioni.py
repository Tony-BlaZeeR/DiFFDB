"""Rigenera i cataloghi di traduzione.

    python tools/traduzioni.py           aggiorna i .ts e ricompila i .qm
    python tools/traduzioni.py --check   verifica che non manchi niente (per la CI)

I `.ts` sono i sorgenti da tradurre (si aprono con `pyside6-linguist`), i `.qm`
sono i cataloghi compilati che l'applicazione carica a runtime. Entrambi sono
versionati: cosi' l'applicazione parla inglese anche eseguita da sorgente,
senza un passo di build.

La lingua sorgente e' l'italiano, quindi non esiste un `diffdb_it.ts`: le
stringhe italiane sono gia' nel codice.
"""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLA = RADICE / "diffdb" / "translations"

# Solo i file che contengono stringhe visibili all'utente.
SORGENTI = [
    "diffdb/main_window.py",
    "diffdb/dialogs.py",
    "diffdb/filters_dialog.py",
    "diffdb/about_dialog.py",
    "diffdb/results_tab.py",
    "diffdb/choose_tab.py",
    "diffdb/home_tab.py",
]
LINGUE = ["en"]


def _strumento(nome: str) -> str:
    """pyside6-lupdate / pyside6-lrelease, presi dallo stesso ambiente di Python."""
    cartella = Path(sys.executable).parent
    for candidato in (cartella / f"pyside6-{nome}.exe", cartella / f"pyside6-{nome}"):
        if candidato.exists():
            return str(candidato)
    return f"pyside6-{nome}"  # sul PATH


def aggiorna(lingua: str) -> Path:
    ts = CARTELLA / f"diffdb_{lingua}.ts"
    ingressi = SORGENTI + sorted(
        str(p.relative_to(RADICE)) for p in (RADICE / "diffdb" / "ui").glob("*.ui"))
    subprocess.run(
        [_strumento("lupdate"), *ingressi,
         "-source-language", "it_IT", "-target-language", lingua,
         "-ts", str(ts)],
        cwd=RADICE, check=True)
    return ts


def compila(lingua: str) -> Path:
    ts = CARTELLA / f"diffdb_{lingua}.ts"
    qm = CARTELLA / f"diffdb_{lingua}.qm"
    subprocess.run([_strumento("lrelease"), str(ts), "-qm", str(qm)], cwd=RADICE, check=True)
    return qm


def non_tradotte(lingua: str):
    """Stringhe senza traduzione: in CI e' quello che si vuole vedere fallire."""
    ts = CARTELLA / f"diffdb_{lingua}.ts"
    if not ts.exists():
        return [f"manca {ts.name}"]

    mancanti = []
    for contesto in ET.parse(ts).getroot():
        for messaggio in contesto.findall("message"):
            traduzione = messaggio.find("translation")
            if traduzione is None or traduzione.get("type") == "unfinished" \
                    or not (traduzione.text or "").strip():
                mancanti.append(f"[{contesto.findtext('name')}] {messaggio.findtext('source')}")
    return mancanti


def main() -> int:
    controllo = "--check" in sys.argv
    CARTELLA.mkdir(exist_ok=True)

    problemi = []
    for lingua in LINGUE:
        aggiorna(lingua)
        mancanti = non_tradotte(lingua)
        if mancanti:
            problemi.append((lingua, mancanti))
        elif not controllo:
            compila(lingua)

    for lingua, mancanti in problemi:
        print(f"\n{lingua}: {len(mancanti)} stringhe da tradurre "
              f"in diffdb/translations/diffdb_{lingua}.ts")
        for voce in mancanti[:20]:
            print("   ", voce)

    if problemi:
        print("\nTraducile con: pyside6-linguist diffdb/translations/diffdb_<lingua>.ts")
        return 1

    print("Traduzioni complete." if controllo else "Traduzioni aggiornate e compilate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
