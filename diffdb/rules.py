"""Regole di confronto: cosa guardare e cosa e' gia' stato accettato.

Su uno schema vero — due, tremila tabelle — un confronto senza regole produce
centinaia di differenze di cui la gran parte e' rumore: tabelle temporanee,
copie di backup, residui di migrazioni, oggetti di altri team nello stesso
schema. Un elenco cosi' non lo legge nessuno, e dopo due volte si smette di
aprire il report. Il valore dello strumento non e' trovare differenze: e'
produrre un elenco che qualcuno guardera' davvero.

Due meccanismi distinti, che risolvono problemi diversi:

**Filtri** — per modello di nome. Dicono cosa non e' schema applicativo e non va
guardato mai. Si applicano *prima* della riflessione, quindi fanno anche
risparmiare tempo.

**Differenze accettate** — una baseline. Ci sono differenze note e volute:
produzione ha un indice in piu' per le prestazioni, collaudo ha una colonna di
debug. Non vanno escluse per modello (nasconderebbero anche quelle future dello
stesso oggetto): vanno accettate una volta e ricomparire solo se cambiano. E'
lo stesso meccanismo della baseline di un linter, ed e' quello che trasforma il
confronto da elenco da leggere a semaforo verde/rosso usabile in pipeline.

Il file e' JSON come il resto della configurazione, e va versionato accanto al
codice: le esclusioni sono decisioni di squadra, non preferenze di chi lancia
il comando.
"""

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FORMATO = 1
NOME_PREDEFINITO = "diffdb.rules.json"

# Le categorie che si possono spegnere in blocco.
CATEGORIE = ("tables", "constraints", "views", "sequences", "synonyms")


class RegoleNonValide(ValueError):
    """Il file delle regole non e' leggibile o non e' nel formato atteso."""


@dataclass
class Regole:
    """Cosa entra nel confronto, e cosa e' gia' stato deciso."""

    escludi_tabelle: list[str] = field(default_factory=list)
    escludi_viste: list[str] = field(default_factory=list)
    escludi_sequenze: list[str] = field(default_factory=list)
    escludi_sinonimi: list[str] = field(default_factory=list)
    solo_tabelle: list[str] = field(default_factory=list)
    categorie_ignorate: set[str] = field(default_factory=set)
    accettate: set[str] = field(default_factory=set)
    origine: str | None = None

    # --- interrogazione ----------------------------------------------------

    @property
    def vuote(self) -> bool:
        return not (self.escludi_tabelle or self.escludi_viste or self.escludi_sequenze
                    or self.escludi_sinonimi or self.solo_tabelle
                    or self.categorie_ignorate or self.accettate)

    def tabella_inclusa(self, nome: str) -> bool:
        if self.solo_tabelle and not _combacia(nome, self.solo_tabelle):
            return False
        return not _combacia(nome, self.escludi_tabelle)

    def vista_inclusa(self, nome: str) -> bool:
        return not _combacia(nome, self.escludi_viste)

    def sequenza_inclusa(self, nome: str) -> bool:
        return not _combacia(nome, self.escludi_sequenze)

    def sinonimo_incluso(self, nome: str) -> bool:
        return not _combacia(nome, self.escludi_sinonimi)

    def categoria_inclusa(self, categoria: str) -> bool:
        return categoria not in self.categorie_ignorate

    def accettata(self, differenza) -> bool:
        return chiave(differenza) in self.accettate

    # --- identita' ---------------------------------------------------------

    def firma(self) -> str | None:
        """Forma canonica dei filtri, per l'impronta dello snapshot.

        Senza questa, due snapshot presi con filtri diversi risulterebbero
        strutture diverse, e `--verify` direbbe che l'ambiente e' cambiato
        quando e' cambiata solo una regola. Le differenze accettate non entrano:
        non cambiano *cosa* si e' letto dal database, solo cosa si mostra.
        """
        if not (self.escludi_tabelle or self.escludi_viste or self.escludi_sequenze
                or self.escludi_sinonimi or self.solo_tabelle or self.categorie_ignorate):
            return None   # nessun filtro: impronta identica a quella storica
        return json.dumps({
            "escludi_tabelle": sorted(self.escludi_tabelle),
            "escludi_viste": sorted(self.escludi_viste),
            "escludi_sequenze": sorted(self.escludi_sequenze),
            "escludi_sinonimi": sorted(self.escludi_sinonimi),
            "solo_tabelle": sorted(self.solo_tabelle),
            "categorie_ignorate": sorted(self.categorie_ignorate),
        }, sort_keys=True, separators=(",", ":"))

    def descrizione(self) -> str:
        """Una riga che dice cosa e' stato escluso, per l'intestazione degli script."""
        if self.vuote:
            return ""
        pezzi = []
        for etichetta, modelli in (("tabelle", self.escludi_tabelle),
                                   ("viste", self.escludi_viste),
                                   ("sequenze", self.escludi_sequenze),
                                   ("sinonimi", self.escludi_sinonimi)):
            if modelli:
                pezzi.append(f"escluse {etichetta} {', '.join(sorted(modelli))}")
        if self.solo_tabelle:
            pezzi.append(f"solo tabelle {', '.join(sorted(self.solo_tabelle))}")
        if self.categorie_ignorate:
            pezzi.append(f"categorie ignorate: {', '.join(sorted(self.categorie_ignorate))}")
        if self.accettate:
            pezzi.append(f"{len(self.accettate)} differenze accettate")
        return "; ".join(pezzi)


NESSUNA = Regole()


# --- chiave stabile di una differenza --------------------------------------


def chiave(differenza) -> str:
    """Identifica una differenza in modo che sopravviva a un nuovo confronto.

    Non entra il *dettaglio*: una colonna che passa da VARCHAR(50) a VARCHAR(80)
    deve restare la stessa differenza gia' accettata. Entra invece il tipo di
    differenza, perche' "manca" e "ha un tipo diverso" sono cose diverse.
    """
    return "|".join([differenza.kind, differenza.name, differenza.column or "",
                     differenza.change, differenza.missing_in or ""])


# --- lettura e scrittura ----------------------------------------------------


def carica(percorso) -> Regole:
    """Legge il file delle regole. Solleva RegoleNonValide se non si capisce."""
    percorso = Path(percorso)
    try:
        payload = json.loads(percorso.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegoleNonValide(f"{percorso}: file non leggibile ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RegoleNonValide(f"{percorso}: non e' un JSON valido ({exc})") from exc

    return da_dizionario(payload, origine=str(percorso))


def da_dizionario(payload: dict, origine: str | None = None) -> Regole:
    dove = origine or "regole"
    if not isinstance(payload, dict):
        raise RegoleNonValide(f"{dove}: atteso un oggetto JSON")

    formato = payload.get("format", FORMATO)
    if not isinstance(formato, int) or formato > FORMATO:
        raise RegoleNonValide(
            f"{dove}: formato {formato}, questa versione di DiFFDB arriva al {FORMATO}.")

    escludi = payload.get("escludi") or {}
    solo = payload.get("includi_solo") or {}

    categorie = set(escludi.get("categorie") or [])
    sconosciute = categorie - set(CATEGORIE)
    if sconosciute:
        raise RegoleNonValide(
            f"{dove}: categorie sconosciute {sorted(sconosciute)}. "
            f"Ammesse: {', '.join(CATEGORIE)}.")

    return Regole(
        escludi_tabelle=_elenco(escludi, "tabelle", dove),
        escludi_viste=_elenco(escludi, "viste", dove),
        escludi_sequenze=_elenco(escludi, "sequenze", dove),
        escludi_sinonimi=_elenco(escludi, "sinonimi", dove),
        solo_tabelle=_elenco(solo, "tabelle", dove),
        categorie_ignorate=categorie,
        accettate=set(payload.get("accettate") or []),
        origine=origine,
    )


def a_dizionario(regole: Regole) -> dict:
    return {
        "format": FORMATO,
        "escludi": {
            "tabelle": sorted(regole.escludi_tabelle),
            "viste": sorted(regole.escludi_viste),
            "sequenze": sorted(regole.escludi_sequenze),
            "sinonimi": sorted(regole.escludi_sinonimi),
            "categorie": sorted(regole.categorie_ignorate),
        },
        "includi_solo": {"tabelle": sorted(regole.solo_tabelle)},
        "accettate": sorted(regole.accettate),
    }


def salva(regole: Regole, percorso) -> Path:
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps(a_dizionario(regole), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    logger.info("Regole salvate in '%s'.", percorso)
    return percorso


def cerca(cartelle) -> Path | None:
    """Il primo diffdb.rules.json trovato fra le cartelle indicate, o None."""
    for cartella in cartelle:
        candidato = Path(cartella) / NOME_PREDEFINITO
        if candidato.is_file():
            return candidato
    return None


# --- utilita' ---------------------------------------------------------------


def _elenco(sezione: dict, nome: str, dove: str) -> list[str]:
    valori = sezione.get(nome) or []
    if not isinstance(valori, list) or not all(isinstance(v, str) for v in valori):
        raise RegoleNonValide(f"{dove}: '{nome}' deve essere un elenco di stringhe")
    return list(valori)


def _combacia(nome: str, modelli) -> bool:
    """Confronto senza distinzione di maiuscole.

    Oracle restituisce i nomi tutti maiuscoli e PostgreSQL tutti minuscoli: un
    modello scritto a mano non deve dipendere da quale dei due si sta guardando.
    """
    if not modelli:
        return False
    alto = (nome or "").upper()
    return any(fnmatch.fnmatchcase(alto, modello.upper()) for modello in modelli)
