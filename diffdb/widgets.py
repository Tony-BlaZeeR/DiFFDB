"""Widget disegnati a mano che il QSS da solo non puo' dare.

- `WordmarkGradiente`: la scritta "DiFFDB" in font pixel con il gradiente
  verticale del logo (menta -> teal), ridipinta quando cambia il tema.
- `Riquadro`: un QFrame che, in variante Retro, aggiunge le parentesi angolari
  da interfaccia testuale (TUI) attorno al bordo.
"""

from __future__ import annotations

from PySide6.QtSvg import QSvgRenderer

from diffdb import theme
from diffdb.qt import Qt, QtCore, QtGui, QtWidgets

# --- logo (il Delta a 3 strati, disegnato col gradiente del tema) ------------
# Due stili dello stesso marchio: trapezi lisci (Moderna) o blocchi (Retro).
_GEO_SLABS = ("M128,52 L158.8,112 L97.2,112 Z",
              "M92.1,122 L163.9,122 L181.4,156 L74.6,156 Z",
              "M69.5,166 L186.5,166 L204,200 L52,200 Z")
_PIX_GRID = [
    "       #       ", "      ###      ", "      ###      ", "               ",
    "     #####     ", "     #####     ", "    #######    ", "               ",
    "   #########   ", "   #########   ", "  ###########  ", " ############# ",
    "###############",
]
_PIX_CELL = 12
_PIX_X0 = (256 - len(_PIX_GRID[0]) * _PIX_CELL) // 2
_PIX_Y0 = (256 - len(_PIX_GRID) * _PIX_CELL) // 2


def _logo_svg() -> str:
    token = theme.corrente()
    top = token.get("logo_top", "#E4F3E9")
    bottom = token.get("logo_bottom", "#2E5A44")
    grad = (f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{top}"/>'
            f'<stop offset="1" stop-color="{bottom}"/></linearGradient>')
    if theme.e_retro():
        shapes = "".join(
            f'<rect x="{_PIX_X0+c*_PIX_CELL}" y="{_PIX_Y0+r*_PIX_CELL}" '
            f'width="{_PIX_CELL}" height="{_PIX_CELL}" fill="#fff"/>'
            for r, row in enumerate(_PIX_GRID) for c, ch in enumerate(row) if ch == "#")
    else:
        shapes = "".join(f'<path d="{s}" fill="#fff"/>' for s in _GEO_SLABS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
            f'<defs>{grad}<mask id="m">{shapes}</mask></defs>'
            f'<rect x="0" y="0" width="256" height="256" fill="url(#g)" mask="url(#m)"/></svg>')


def logo_pixmap(size: int) -> QtGui.QPixmap:
    """Il logo renderizzato col gradiente del tema attivo (segue variante e colore)."""
    renderer = QSvgRenderer(QtCore.QByteArray(_logo_svg().encode("utf-8")))
    img = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(img)
    renderer.render(painter)
    painter.end()
    return QtGui.QPixmap.fromImage(img)


class WordmarkGradiente(QtWidgets.QWidget):
    """La scritta del marchio con riempimento a gradiente verticale."""

    def __init__(self, testo: str, dimensione: int, parent=None):
        super().__init__(parent)
        self._testo = testo
        self._dimensione = dimensione
        self.imposta_tema()

    def _font(self) -> QtGui.QFont:
        f = QtGui.QFont(theme.corrente().get("font_logo", "Silkscreen"), self._dimensione)
        f.setHintingPreference(QtGui.QFont.HintingPreference.PreferFullHinting)
        return f

    def imposta_tema(self):
        """Da richiamare quando cambia il tema: aggiorna font e colori."""
        metriche = QtGui.QFontMetrics(self._font())
        self.setFixedSize(metriche.horizontalAdvance(self._testo) + 4,
                          metriche.height() + 2)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setFont(self._font())
        token = theme.corrente()
        gradiente = QtGui.QLinearGradient(0, 0, 0, self.height())
        gradiente.setColorAt(0.0, QtGui.QColor(token.get("logo_top", "#D6EBDD")))
        gradiente.setColorAt(1.0, QtGui.QColor(token.get("logo_bottom", "#3C7156")))
        painter.setPen(QtGui.QPen(QtGui.QBrush(gradiente), 0))
        painter.drawText(self.rect(),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._testo)


class Riquadro(QtWidgets.QFrame):
    """Riquadro che raggruppa una sezione (ruolo QSS 'riquadro').

    In variante Retro disegna le parentesi angolari sul bordo e, se gli e' stato
    dato un titolo, lo incide sulla linea superiore come `┤ TITOLO ├`; nella
    Moderna resta un pannello dagli angoli morbidi, tutto dal QSS, e il titolo
    lo mostra invece l'etichetta interna registrata con `registra_etichetta`.
    """

    def __init__(self, titolo: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("ruolo", "riquadro")
        self._titolo = titolo.upper()
        self._etichetta_interna = None

    def registra_etichetta(self, etichetta):
        """L'etichetta interna che fa da titolo nella Moderna: nel Retro si
        nasconde, perche' il titolo passa sul bordo."""
        self._etichetta_interna = etichetta
        self.aggiorna_tema()

    def aggiorna_tema(self):
        if self._etichetta_interna is not None and self._titolo:
            self._etichetta_interna.setVisible(not theme.e_retro())
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not theme.e_retro():
            return
        painter = QtGui.QPainter(self)
        colore = QtGui.QColor(theme.corrente().get("accent_strong", "#93C4A6"))
        painter.setPen(QtGui.QPen(colore, 2))
        r = self.rect().adjusted(1, 1, -2, -2)
        d = 10  # lunghezza del gancio d'angolo
        for x, sx in ((r.left(), 1), (r.right(), -1)):
            for y, sy in ((r.top(), 1), (r.bottom(), -1)):
                painter.drawLine(x, y, x + sx * d, y)
                painter.drawLine(x, y, x, y + sy * d)

        if self._titolo:
            testo = f"┤ {self._titolo} ├"   # ┤ TITOLO ├
            font = QtGui.QFont(theme.corrente().get("font_logo", "Silkscreen"), 8)
            painter.setFont(font)
            metriche = QtGui.QFontMetrics(font)
            larghezza = metriche.horizontalAdvance(testo)
            x = r.left() + 16
            y = r.top() + 3   # appena sotto il bordo superiore, tutto visibile
            # Sfondo pieno dietro il testo per "tagliare" la linea del bordo.
            painter.fillRect(x - 3, y, larghezza + 6, metriche.height(),
                             QtGui.QColor(theme.corrente().get("surface", "#111A14")))
            painter.setPen(colore)
            painter.drawText(x, y + metriche.ascent(), testo)
