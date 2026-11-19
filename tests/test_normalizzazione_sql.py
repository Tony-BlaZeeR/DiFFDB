"""La normalizzazione SQL usata per confrontare viste, default e CHECK.

Due famiglie di test, e la seconda e' quella che conta di piu':

- la formattazione non deve generare falsi allarmi (indentazione, maiuscole,
  spazi attorno a virgole e operatori, commenti);
- una differenza vera non deve sparire. La versione precedente metteva tutto
  in minuscolo, comprese le stringhe, percio' un default 'Mario' e un default
  'mario' risultavano identici: il confronto taceva su una differenza reale,
  che per uno strumento di diff e' il guasto peggiore.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diffdb.schema_snapshot import normalize_sql  # noqa: E402


@pytest.mark.parametrize("uno,due,motivo", [
    ("select a from t", "SELECT\n    a\nFROM t", "indentazione e maiuscole"),
    ("select a, b from t", "select a , b from t", "spazio prima della virgola"),
    ("select a from t where x=1", "select a from t where x = 1", "spazi attorno a ="),
    ("select f(a, b) from t", "select f( a,b ) from t", "spazi dentro le parentesi"),
    ("select a from t", "select a from t -- commento di riga", "commento di riga"),
    ("select a from t", "select a from t /* commento a blocco */", "commento a blocco"),
    ("select a from t;", "select a from t", "punto e virgola finale"),
    ("select a from t", "  select   a   from   t  ", "spaziatura esuberante"),
])
def test_la_formattazione_non_crea_differenze(uno, due, motivo):
    assert normalize_sql(uno) == normalize_sql(due), motivo


@pytest.mark.parametrize("uno,due,motivo", [
    ("select 'Mario' from t", "select 'mario' from t",
     "maiuscole dentro una stringa: erano la differenza nascosta"),
    ("select a from t", "select b from t", "colonna diversa"),
    ("select a from t where x = 1", "select a from t where x = 2", "valore diverso"),
    ("select a from t", "select a from u", "tabella diversa"),
    ('select "Col" from t', 'select "col" from t',
     "identificatore quotato: le maiuscole contano"),
])
def test_le_differenze_vere_restano_visibili(uno, due, motivo):
    assert normalize_sql(uno) != normalize_sql(due), motivo


# --- parentesi e apici esterni ---------------------------------------------
#
# SQL Server conserva i default fra parentesi, a volte doppie, e le stringhe
# fra apici: vanno tolti per confrontare fra dialetti diversi. Il controllo
# precedente guardava solo i caratteri agli estremi e cosi' riduceva
# "(a) or (b)" a "a) or (b", un'espressione senza senso.

def test_le_parentesi_che_avvolgono_tutto_si_togliono():
    assert normalize_sql("((0))") == normalize_sql("0")
    assert normalize_sql("(saldo > 0)") == normalize_sql("saldo > 0")


def test_gli_apici_che_avvolgono_tutto_si_togliono():
    assert normalize_sql("('attivo')") == normalize_sql("attivo")


def test_le_parentesi_che_non_avvolgono_tutto_restano():
    """Il caso che prima veniva mutilato."""
    normalizzato = normalize_sql("(a) or (b)")
    assert normalizzato == "(a) or (b)"
    assert not normalizzato.startswith("a)")


def test_parentesi_sbilanciate_non_vengono_toccate():
    assert normalize_sql("(a") == "(a"


@pytest.mark.parametrize("vuoto", [None, "", "   ", "\n\t "])
def test_valori_vuoti(vuoto):
    assert normalize_sql(vuoto) == ""


def test_accetta_oggetti_non_stringa():
    """Arriva anche sqltext di SQLAlchemy, che non e' una str."""

    class Finta:
        def __str__(self):
            return "SALDO > 0"

    assert normalize_sql(Finta()) == normalize_sql("saldo > 0")
