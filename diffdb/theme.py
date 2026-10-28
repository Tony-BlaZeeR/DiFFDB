"""Temi dell'interfaccia: due varianti visive (Moderna e Retro) e, per la
Moderna, un sotto-tema chiaro/scuro.

Il colore vive qui, in un dizionario di token per variante: i due fogli di stile
in `styles/moderna.qss` e `styles/retro.qss` sono template con segnaposto
`{token}` che vengono riempiti con `str.format_map`. Cosi' la tavolozza sta in un
posto solo, e i QSS restano leggibili.

Tutta l'interfaccia e' gia' stilizzata per proprieta' (`ruolo`, `pastiglia`) e
object-name (`#titleBar`, ...): cambiare variante vuol dire ricaricare il foglio
di stile dell'applicazione, non ricostruire i widget. I pochi colori che stanno
nel codice (le direzioni del diff nella scheda Risultati) si leggono da qui con
`colori_diff()`, cosi' seguono il tema anche loro.
"""

from __future__ import annotations

import logging
import re

from diffdb.paths import resource_path
from diffdb.qt import QtGui, QtWidgets

logger = logging.getLogger(__name__)

VARIANTE_MODERNA = "moderna"
VARIANTE_RETRO = "retro"
TEMA_SCURO = "scuro"
TEMA_CHIARO = "chiaro"

# File dei font, in diffdb/fonts/. Variabili (Inter, JetBrains Mono) o statici.
FONT_FILES = (
    "Inter.ttf",
    "JetBrainsMono.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-SemiBold.ttf",
    "Silkscreen-Regular.ttf",
    "Silkscreen-Bold.ttf",
)

# Famiglie usate dai QSS. Se un font non si carica, Qt ripiega sul generico.
FONTS_MODERNA = {"font_ui": "Inter", "font_mono": "JetBrains Mono", "font_logo": "Silkscreen"}
FONTS_RETRO = {"font_ui": "IBM Plex Mono", "font_mono": "IBM Plex Mono", "font_logo": "Silkscreen"}

# --- tavolozze -----------------------------------------------------------------
# Alpha in 0-255 come vuole rgba() di QSS. Derivata dal logo pixel di Retro:
# menta chiaro in alto, teal profondo in basso, su nero verdastro.

MODERNA_SCURO = {
    "page": "#070B08", "bg": "#0B110D", "titlebar": "#0E1611", "surface": "#111A14",
    "raised": "#18241C", "border": "#243528", "border_strong": "#2E4535",
    "divider": "rgba(214,235,221,33)", "row_rule": "rgba(214,235,221,18)",
    "hover": "rgba(214,235,221,10)",
    "text": "#D6EBDD", "text2": "#8FB39C", "muted": "#84A191", "disabled_text": "#4E6B59",
    "accent": "#6FA888", "accent_strong": "#93C4A6",
    "accent_tint": "rgba(111,168,136,31)", "accent_tint2": "rgba(111,168,136,56)",
    "plus": "#93C4A6", "plus_bg": "rgba(111,168,136,36)", "plus_border": "#3C7156",
    "minus": "#E0A866", "minus_bg": "rgba(224,168,102,33)", "minus_border": "#6B5530",
    "tilde": "#D9B84A", "tilde_bg": "rgba(201,162,39,36)", "tilde_border": "#6B5530",
    "error": "#E08A74", "error_bg": "rgba(198,95,74,31)", "error_border": "#6B3B35",
    "code": "#0A0F0C", "line_number": "#3C5446",
    "sel_bg": "rgba(111,168,136,56)", "sel_text": "#D6EBDD",
    "logo_top": "#D6EBDD", "logo_bottom": "#3C7156",
    # direzioni del diff (lette da results_tab), verificate a >=4.5:1 sul fondo albero
    "diff_manca_primo": "#97B188", "diff_solo_qui": "#DA9C69", "diff_diverso": "#D9A343",
    **FONTS_MODERNA,
}

MODERNA_CHIARO = {
    "page": "#DFE7E1", "bg": "#F5F8F5", "titlebar": "#ECF2ED", "surface": "#FBFCFA",
    "raised": "#EAF0EB", "border": "#D2DED5", "border_strong": "#B9CBBE",
    "divider": "rgba(23,49,31,36)", "row_rule": "rgba(23,49,31,20)", "hover": "rgba(23,49,31,9)",
    "text": "#132019", "text2": "#3C5A47", "muted": "#587262", "disabled_text": "#9DB2A4",
    "accent": "#2E5A44", "accent_strong": "#224634",
    "accent_tint": "rgba(46,90,68,20)", "accent_tint2": "rgba(46,90,68,41)",
    "plus": "#2B6A48", "plus_bg": "rgba(46,106,72,26)", "plus_border": "#9BBFA7",
    "minus": "#985712", "minus_bg": "rgba(176,105,30,28)", "minus_border": "#D3B68A",
    "tilde": "#7E640A", "tilde_bg": "rgba(160,128,20,31)", "tilde_border": "#CFC07E",
    "error": "#A8432F", "error_bg": "rgba(168,67,47,23)", "error_border": "#D9A99C",
    "code": "#F0F4F1", "line_number": "#A3B8AA",
    "sel_bg": "rgba(46,90,68,41)", "sel_text": "#132019",
    "logo_top": "#4E8A6B", "logo_bottom": "#17311F",
    "diff_manca_primo": "#2B6A48", "diff_solo_qui": "#985712", "diff_diverso": "#7E640A",
    **FONTS_MODERNA,
}

RETRO_SCURO = {
    "page": "#070B08", "bg": "#0B110D", "titlebar": "#17311F", "surface": "#111A14",
    "raised": "#18241C", "border": "#243528", "border_strong": "#3C7156",
    "divider": "#3C7156", "row_rule": "#243528", "hover": "#17311F",
    "text": "#D6EBDD", "text2": "#8FB39C", "muted": "#84A191", "disabled_text": "#4E6B59",
    "accent": "#6FA888", "accent_strong": "#93C4A6",
    "accent_tint": "#17311F", "accent_tint2": "#224634",
    "plus": "#93C4A6", "plus_bg": "#17311F", "plus_border": "#3C7156",
    "minus": "#C9A227", "minus_bg": "#2A2410", "minus_border": "#6B5A14",
    "tilde": "#D6EBDD", "tilde_bg": "#224634", "tilde_border": "#3C7156",
    "error": "#C9A227", "error_bg": "#2A2410", "error_border": "#6B5A14",
    "code": "#080D0A", "line_number": "#3C7156",
    "sel_bg": "#93C4A6", "sel_text": "#0B110D",
    "logo_top": "#D6EBDD", "logo_bottom": "#2E5A44",
    "diff_manca_primo": "#93C4A6", "diff_solo_qui": "#C9A227", "diff_diverso": "#D6EBDD",
    **FONTS_RETRO,
}

# Retro chiaro: "tutta la carta", testo verde scuro su fondo avorio, accenti a
# blocco invertito. Stessa struttura, luminosita' ribaltata.
RETRO_CHIARO = {
    "page": "#DCE4DC", "bg": "#EEF3ED", "titlebar": "#DCE7DD", "surface": "#F4F8F3",
    "raised": "#E4EDE5", "border": "#C4D3C7", "border_strong": "#2E5A44",
    "divider": "#2E5A44", "row_rule": "#C4D3C7", "hover": "#DCE7DD",
    "text": "#122018", "text2": "#33503E", "muted": "#4F6B5A", "disabled_text": "#9DB2A4",
    "accent": "#2E5A44", "accent_strong": "#1C3B2C",
    "accent_tint": "#DCE7DD", "accent_tint2": "#C8DBCE",
    "plus": "#2B6A48", "plus_bg": "#DCE7DD", "plus_border": "#9BBFA7",
    "minus": "#8A5A12", "minus_bg": "#EFE4CC", "minus_border": "#CFB888",
    "tilde": "#122018", "tilde_bg": "#C8DBCE", "tilde_border": "#9BBFA7",
    "error": "#8A5A12", "error_bg": "#EFE4CC", "error_border": "#CFB888",
    "code": "#F4F8F3", "line_number": "#9BBFA7",
    "sel_bg": "#1C3B2C", "sel_text": "#F4F8F3",
    "logo_top": "#2E5A44", "logo_bottom": "#17311F",
    "diff_manca_primo": "#2B6A48", "diff_solo_qui": "#8A5A12", "diff_diverso": "#7E640A",
    **FONTS_RETRO,
}

# Alias storico (test e codice che importavano RETRO).
RETRO = RETRO_SCURO

# Accento verde di default: coincide con quello delle tavolozze qui sopra.
ACCENTO_PREDEFINITO = "#6FA888"

_TAVOLOZZE = {
    (VARIANTE_MODERNA, TEMA_SCURO): MODERNA_SCURO,
    (VARIANTE_MODERNA, TEMA_CHIARO): MODERNA_CHIARO,
    (VARIANTE_RETRO, TEMA_SCURO): RETRO_SCURO,
    (VARIANTE_RETRO, TEMA_CHIARO): RETRO_CHIARO,
}

# Token e variante applicati per ultimi: li legge chi disegna fuori dal QSS
# (colori del diff, wordmark a gradiente, cornici TUI del retro).
_corrente: dict = MODERNA_SCURO
_variante_corrente: str = VARIANTE_MODERNA
_font_caricati = False


def carica_font() -> None:
    """Registra i font una volta sola. Vanno caricati dopo QApplication."""
    global _font_caricati
    if _font_caricati:
        return
    for nome in FONT_FILES:
        percorso = resource_path("fonts", nome)
        if QtGui.QFontDatabase.addApplicationFont(percorso) < 0:
            logger.warning("Font non caricato: %s", percorso)
    _font_caricati = True


def _tavolozza(variante: str, tema: str) -> dict:
    return _TAVOLOZZE.get((variante, tema)) or MODERNA_SCURO


def _ritinge(valore: str, h: float, sat: float) -> str:
    """Riporta un token sulla tonalita' `h` con saturazione `sat`, **conservando
    la luminosita'** originale: cosi' il fondo (o il bordo, o il testo) prende il
    colore scelto ma i rapporti di contrasto restano quelli di partenza.

    Gestisce sia `#RRGGBB` sia `rgba(r,g,b,a)` (di cui conserva l'alpha).
    """
    valore = valore.strip()
    if valore.startswith("rgba"):
        n = [int(x) for x in re.findall(r"\d+", valore)]
        r, g, b = n[:3]
        a = n[3] if len(n) > 3 else 255
        _hh, _ss, lum, _aa = QtGui.QColor(r, g, b).getHslF()
        c = QtGui.QColor.fromHslF(h, min(1.0, sat), lum)
        return f"rgba({c.red()},{c.green()},{c.blue()},{a})"
    base = QtGui.QColor(valore)
    if not base.isValid():
        return valore
    _hh, _ss, lum, _aa = base.getHslF()
    return QtGui.QColor.fromHslF(h, min(1.0, sat), lum).name().upper()


def _personalizza_accento(token: dict, retro: bool, chiaro: bool, accento: str) -> dict:
    """Ricolora l'interfaccia sulla tonalita' scelta: non solo gli elementi
    d'accento (tab, pulsanti, titoli) ma anche i **fondi, i bordi e i testi**, che
    prendono la stessa tinta a parita' di luminosita'. I colori semantici del diff
    (ambra/oro per le altre direzioni) restano invariati, per non perdere di
    leggibilita'.

    Le luminosita' dell'accento sono fissate a bande leggibili, cosi' resta
    distinguibile sui fondi qualunque colore scelga l'utente.
    """
    base = QtGui.QColor(accento)
    if not base.isValid():
        return token
    h, s, _l, _a = base.getHslF()
    if h < 0:
        h = 0.0
    s = max(s, 0.35)

    def hsl(lum: float, sat: float | None = None) -> str:
        c = QtGui.QColor.fromHslF(h, min(1.0, s if sat is None else sat), lum)
        return c.name().upper()

    def rgba(lum: float, alpha: int) -> str:
        c = QtGui.QColor.fromHslF(h, s, lum)
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"

    if chiaro:
        accent, strong = hsl(0.34), hsl(0.26)
        tint, tint2 = (hsl(0.90), hsl(0.84)) if retro else (rgba(0.34, 20), rgba(0.34, 41))
        logo_top, logo_bottom = hsl(0.42), hsl(0.20)
        testo_vivo = accent
    else:
        accent, strong = hsl(0.62), hsl(0.74)
        tint, tint2 = (hsl(0.18), hsl(0.26)) if retro else (rgba(0.62, 31), rgba(0.62, 56))
        logo_top, logo_bottom = hsl(0.86, s * 0.6), hsl(0.34)
        testo_vivo = strong

    nuovo = dict(token)
    nuovo.update(accent=accent, accent_strong=strong, accent_tint=tint, accent_tint2=tint2,
                 logo_top=logo_top, logo_bottom=logo_bottom)

    # Tinta anche i neutri (fondi, bordi, testi) sulla tonalita' scelta, con
    # saturazione crescente dai fondi ai bordi. Nel tema chiaro i fondi sono
    # quasi bianchi: li si tinge piu' leggeri, o diventano pastelli troppo carichi.
    sat_fondo = 0.10 if chiaro else 0.16
    for chiave in ("page", "bg", "titlebar", "surface", "raised", "code"):
        nuovo[chiave] = _ritinge(token[chiave], h, sat_fondo)
    for chiave in ("border", "border_strong"):
        nuovo[chiave] = _ritinge(token[chiave], h, 0.24)
    for chiave in ("divider", "row_rule", "hover"):
        nuovo[chiave] = _ritinge(token[chiave], h, 0.30)
    nuovo["text"] = _ritinge(token["text"], h, 0.10)
    for chiave in ("text2", "muted", "disabled_text", "line_number"):
        nuovo[chiave] = _ritinge(token[chiave], h, 0.22)
    nuovo["sel_text"] = _ritinge(token["sel_text"], h, sat_fondo)

    # La selezione segue l'accento: traslucida nel moderno, piena nel retro.
    nuovo["sel_bg"] = strong if retro else tint2
    # "Presente nel riferimento" (pastiglia buona, direzione del diff) e' legato
    # all'accento: verde di default, ma segue il colore scelto.
    nuovo["plus"] = testo_vivo
    nuovo["diff_manca_primo"] = testo_vivo
    if retro:
        nuovo["plus_bg"] = tint
        nuovo["plus_border"] = accent
    return nuovo


def applica(app: QtWidgets.QApplication, variante: str = VARIANTE_MODERNA,
            tema: str = TEMA_SCURO, accento: str | None = None) -> dict:
    """Carica i font (la prima volta), riempie il QSS della variante e lo applica.

    `accento` e' un colore #RRGGBB scelto dall'utente; None o il verde di default
    lascia la tavolozza cosi' com'e'. Ritorna i token in uso, per chi deve
    colorare a mano (scheda Risultati).
    """
    global _corrente, _variante_corrente
    carica_font()
    token = dict(_tavolozza(variante, tema))
    if accento and accento.upper() != ACCENTO_PREDEFINITO.upper():
        token = _personalizza_accento(
            token, variante == VARIANTE_RETRO, tema == TEMA_CHIARO, accento)
    foglio = VARIANTE_RETRO if variante == VARIANTE_RETRO else VARIANTE_MODERNA
    template = _leggi(resource_path("styles", f"{foglio}.qss"))
    try:
        app.setStyleSheet(template.format_map(token))
    except KeyError as exc:
        logger.error("Token mancante nel QSS %s: %s", foglio, exc)
        raise
    app.setFont(QtGui.QFont(token["font_ui"], 10))
    _corrente = token
    _variante_corrente = variante
    return token


def variante_attiva() -> str:
    return _variante_corrente


def e_retro() -> bool:
    return _variante_corrente == VARIANTE_RETRO


def logo_file() -> str:
    """Il marchio da usare: pixel nel Retro, geometrico altrove."""
    return "logo_retro.png" if _variante_corrente == VARIANTE_RETRO else "logo.png"


def corrente() -> dict:
    return _corrente


def colori_diff() -> dict:
    """QColor per le tre direzioni del diff, dalla tavolozza attiva."""
    return {
        "manca_primo": QtGui.QColor(_corrente["diff_manca_primo"]),
        "solo_qui": QtGui.QColor(_corrente["diff_solo_qui"]),
        "diverso": QtGui.QColor(_corrente["diff_diverso"]),
    }


def _leggi(percorso: str) -> str:
    with open(percorso, encoding="utf-8") as f:
        return f.read()
