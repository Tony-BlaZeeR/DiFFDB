"""Il report Excel di fronte a quello che i database contengono davvero.

Due limiti del formato .xlsx che non si notano finche' non capitano, e che
hanno in comune il difetto peggiore: un solo valore anomalo rovinava tutto
il file invece della sola cella.

- i caratteri di controllo non sono ammessi, e openpyxl solleva
  IllegalCharacterError: bastava uno per non ottenere *nessun* Excel;
- le celle si fermano a 32767 caratteri, e il taglio avveniva in silenzio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.diff_DB import Difference, DiffResult  # noqa: E402
from diffdb.report import LIMITE_CELLA, generate_excel_report  # noqa: E402
from diffdb.schema_snapshot import Snapshot  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

COLONNA_DETTAGLIO = 7   # "Dettaglio", l'ultima di COLONNE


def _report(tmp_path, detail: str) -> str:
    """Scrive un report con una sola differenza e il dettaglio dato."""
    diff = DiffResult(
        Snapshot("SVI", "sqlite"), Snapshot("COLLAUDO", "sqlite"),
        tables=[Difference("column", "clienti", "default diverso",
                           column="stato", detail=detail)],
    )
    percorso = str(tmp_path / "report.xlsx")
    generate_excel_report(diff, percorso)
    return percorso


def _dettaglio_scritto(percorso: str) -> str:
    foglio = openpyxl.load_workbook(percorso)["Tabelle"]
    return foglio.cell(row=2, column=COLONNA_DETTAGLIO).value


def test_un_dettaglio_normale_arriva_intatto(tmp_path):
    """Prima di tutto: la pulizia non deve toccare i valori normali."""
    testo = "SVI: 0 | COLLAUDO: 1"
    assert _dettaglio_scritto(_report(tmp_path, testo)) == testo


@pytest.mark.parametrize("carattere,come", [
    ("\x00", "carattere nullo"),
    ("\x0b", "tabulazione verticale"),
    ("\x1f", "separatore di unita'"),
])
def test_un_carattere_di_controllo_non_fa_perdere_il_report(tmp_path, carattere,
                                                            come):
    """Il guasto: openpyxl sollevava IllegalCharacterError e l'export finiva
    senza scrivere niente. Una cella sporca non deve costare tutto il file."""
    scritto = _dettaglio_scritto(_report(tmp_path, f"SVI: 'a{carattere}b'"))

    assert carattere not in scritto, come
    assert "�" in scritto      # dove c'era, si vede
    assert "SVI: 'a" in scritto     # il resto del dettaglio e' rimasto


def test_una_cella_troppo_lunga_dichiara_il_taglio(tmp_path):
    """Il taglio a 32767 caratteri e' del formato e non si puo' evitare, ma
    openpyxl lo faceva in silenzio: un report che perde pezzi senza dirlo e'
    peggio di uno che lo dichiara."""
    originale = "SVI: " + "x" * 40000
    scritto = _dettaglio_scritto(_report(tmp_path, originale))

    assert len(scritto) == LIMITE_CELLA
    assert "troncato" in scritto
    assert str(len(originale)) in scritto   # quanto era in origine


def test_una_cella_al_limite_esatto_non_viene_toccata(tmp_path):
    """Il confine: 32767 caratteri entrano, quindi non va dichiarato niente."""
    scritto = _dettaglio_scritto(_report(tmp_path, "y" * LIMITE_CELLA))

    assert len(scritto) == LIMITE_CELLA
    assert "troncato" not in scritto
