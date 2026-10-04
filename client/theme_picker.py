"""Theme picker with a colour hint for every theme.

Each row paints a mini code preview in that theme's own colours (its
background, keyword / function / string / class colours and accent), so you
see what you'll get before choosing. Hovering a row live-previews the theme
on the whole window; leaving without choosing reverts it.
"""
from PySide6.QtCore import Qt, Signal, QPoint, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import design, icons


def _is_dark(colors: dict) -> bool:
    return QColor(colors["background"]).lightness() < 128


class Swatch(QWidget):
    """Mini editor preview: bg, three coloured 'code' tokens and accent dots."""

    def __init__(self, colors: dict, w: int = 112, h: int = 38):
        super().__init__()
        self.c = colors
        self.setFixedSize(w, h)

    def paintEvent(self, e):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(c["foreground"]).darker(300) if _is_dark(c) else QColor(c["foreground"]).lighter(300), 1))
        p.setBrush(QColor(c["background"]))
        p.drawRoundedRect(r, 7, 7)
        # gutter strip
        p.setPen(Qt.PenStyle.NoPen)
        g = QColor(c.get("gutter", c["background"]))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(1, 1, 14, self.height() - 2), 6, 6)
        p.drawRect(QRectF(8, 1, 7, self.height() - 2))
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        x, y = 22, 15
        p.setPen(QColor(c["keyword"]))
        p.drawText(x, y, "def")
        p.setPen(QColor(c["function"]))
        p.drawText(x + 25, y, "fix")
        p.setPen(QColor(c["foreground"]))
        p.drawText(x + 44, y, "()")
        p.setPen(QColor(c["string"]))
        p.drawText(x + 6, y + 13, '"ok"')
        p.setPen(QColor(c["number"]))
        p.drawText(x + 40, y + 13, "42")
        # accent + diff dots
        p.setPen(Qt.PenStyle.NoPen)
        for i, key in enumerate(("ai-suggestion-text", "diff-add-text", "error-underline")):
            p.setBrush(QColor(c.get(key, c["foreground"])))
            p.drawEllipse(QRectF(self.width() - 12 - i * 11, self.height() - 14, 7, 7))


class ThemeRow(QFrame):
    hovered = Signal(str)
    chosen = Signal(str)

    def __init__(self, name: str, label: str, colors: dict, current: bool):
        super().__init__()
        self.name = name
        self.setObjectName("themeRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 12, 6)
        lay.setSpacing(12)
        lay.addWidget(Swatch(colors))
        lab = QLabel(label)
        lab.setStyleSheet("background: transparent; font-size: 12.5px; font-weight: 600;")
        kind = QLabel("Dark" if _is_dark(colors) else "Light")
        kind.setStyleSheet("background: transparent; font-size: 10.5px;")
        kind.setObjectName("muted")
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(lab)
        box.addWidget(kind)
        lay.addLayout(box, stretch=1)
        self.check = QLabel()
        self.check.setFixedSize(16, 16)
        lay.addWidget(self.check)
        self.current = current

    def enterEvent(self, e):
        self.hovered.emit(self.name)
        super().enterEvent(e)

    def mousePressEvent(self, e):
        self.chosen.emit(self.name)


class ThemePopup(QFrame):
    previewRequested = Signal(str)
    themeChosen = Signal(str)
    dismissed = Signal()

    def __init__(self, themes: dict, labels: dict, current: str, tokens: design.Tokens):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._chosen = False
        t = tokens
        self.setStyleSheet(
            f"QFrame#popup {{ background: {t.hex(t.raised)}; border: 1px solid {t.hex(t.hairline_strong)}; border-radius: 12px; }}"
            f"QFrame#themeRow {{ background: transparent; border-radius: 9px; border: 1px solid transparent; }}"
            f"QFrame#themeRow:hover {{ background: {t.hex(t.hover)}; border: 1px solid {t.hex(t.hairline_strong)}; }}"
            f"QLabel {{ color: {t.hex(t.text)}; }} QLabel#muted {{ color: {t.hex(t.text_muted)}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(2)
        head = QLabel("THEME")
        head.setStyleSheet(f"color: {t.hex(t.text_muted)}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px;"
                           f"padding: 4px 8px 6px 8px; background: transparent;")
        v.addWidget(head)
        order = sorted(themes, key=lambda n: (not _is_dark(themes[n].colors), labels.get(n, n).lower()))
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        for name in order:
            row = ThemeRow(name, labels.get(name, name), themes[name].colors, name == current)
            if name == current:
                row.check.setPixmap(icons.pixmap("check", t.hex(t.accent), 16))
            row.hovered.connect(self.previewRequested)
            row.chosen.connect(self._pick)
            hl.addWidget(row)
        scroll = QScrollArea()
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: {t.hex(t.hairline_strong)}; border-radius: 3px; min-height: 24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {t.hex(t.text_faint)}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")
        scroll.setMinimumHeight(min(440, 62 * len(order) + 4))
        scroll.setMaximumHeight(440)
        v.addWidget(scroll)
        self.setFixedWidth(300)

    def _pick(self, name: str):
        self._chosen = True
        self.themeChosen.emit(name)
        self.close()

    def hideEvent(self, e):
        super().hideEvent(e)
        if not self._chosen:
            self.dismissed.emit()
        self.deleteLater()


class ThemeButton(QPushButton):
    """Title-bar button: shows the current theme's colours as a tiny swatch strip."""
    clickedPicker = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("themeBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(32)
        self.setMinimumWidth(104)
        self.setToolTip("Choose theme")
        self._colors = None
        self._label = ""
        self._tokens = None
        self.clicked.connect(self.clickedPicker)

    def set_theme(self, theme, label: str, tokens):
        self._colors, self._label, self._tokens = theme.colors, label, tokens
        self.setStyleSheet(
            f"QPushButton#themeBtn {{ background: transparent; border: 1px solid {tokens.hex(tokens.hairline_strong)};"
            f" border-radius: 8px; }} QPushButton#themeBtn:hover {{ background: {tokens.hex(tokens.hover)};"
            f" border-color: {tokens.hex(tokens.accent)}; }}")
        fm = self.fontMetrics()
        self.setFixedWidth(max(110, fm.horizontalAdvance(label) + 78))
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._colors:
            return
        c, t = self._colors, self._tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # a rounded chip showing bg with 3 colour dots
        p.setPen(QPen(t.hairline_strong, 1))
        p.setBrush(QColor(c["background"]))
        p.drawRoundedRect(QRectF(8, 8, 34, 16), 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        for i, key in enumerate(("keyword", "function", "string")):
            p.setBrush(QColor(c[key]))
            p.drawEllipse(QRectF(12 + i * 10, 12, 8, 8))
        p.setPen(t.text)
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(50, 0, self.width() - 70, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
        p.drawPixmap(self.width() - 20, (self.height() - 12) // 2, icons.pixmap("chevron-down", t.hex(t.text_muted), 12))
