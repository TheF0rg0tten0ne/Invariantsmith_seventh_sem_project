"""Small reusable widgets shared across the client."""
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize, QRectF,
                            Signal, QPoint, QEvent)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QWidget, QVBoxLayout, QSizePolicy,
)

from . import icons


class IconButton(QToolButton):
    """Flat icon-only button whose glyph is re-tinted from theme tokens.

    `role` picks the tint: 'muted' (default chrome), 'text', 'accent',
    'danger'. Call retheme(tokens) after a theme change."""

    def __init__(self, name: str, tooltip: str = "", size: int = 28, icon_size: int = 16,
                 role: str = "muted", object_name: str = "chromeBtn", checkable: bool = False):
        super().__init__()
        self._name = name
        self._role = role
        self._icon_size = icon_size
        self.setObjectName(object_name)
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tokens = None

    def set_icon_name(self, name: str):
        self._name = name
        if self._tokens is not None:
            self.retheme(self._tokens)

    def _color(self, t) -> tuple[str, str]:
        base = {"muted": t.text_muted, "text": t.text, "accent": t.accent,
                "danger": t.error, "faint": t.text_faint}[self._role]
        hov = {"danger": t.error, "accent": t.accent}.get(self._role, t.text)
        return t.hex(base), t.hex(hov if not isinstance(hov, str) else hov)

    def retheme(self, t):
        self._tokens = t
        c, h = self._color(t)
        self.setIcon(icons.icon(self._name, c, self._icon_size, hover=h, disabled=t.hex(t.text_faint)))


class ToggleSwitch(QAbstractButton):
    """iOS-style on/off switch (QCheckBox indicators can't be themed with
    QSS alone without shipping image files)."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = QColor("#e0b454")
        self._off = QColor("#444")
        self._knob = QColor("#fff")

    def set_colors(self, on: QColor, off: QColor, knob: QColor):
        self._on, self._off, self._knob = on, off, knob
        self.update()

    def sizeHint(self):
        return QSize(38, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._on if self.isChecked() else self._off)
        p.drawRoundedRect(QRectF(0, 2, 38, 18), 9, 9)
        p.setBrush(self._knob)
        x = 20 if self.isChecked() else 2
        p.drawEllipse(QRectF(x, 3, 16, 16))


class SectionHeader(QPushButton):
    """Collapsible section toggle ('OUTLINE', 'TIMELINE'...) with a chevron."""

    def __init__(self, title: str, expanded: bool = False):
        super().__init__()
        self._title = title
        self._expanded = expanded
        self.setObjectName("sectionHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIconSize(QSize(12, 12))
        self._tokens = None
        self.setText("  " + title)

    def retheme(self, t):
        self._tokens = t
        self._refresh()

    def set_expanded(self, v: bool):
        self._expanded = v
        self._refresh()

    def _refresh(self):
        if self._tokens is not None:
            self.setIcon(icons.icon("chevron-down" if self._expanded else "chevron-right",
                                    self._tokens.hex(self._tokens.text_muted), 12))


class CollapsibleSection(QWidget):
    """Header + body. Collapsed = body hidden, so it costs only the header's
    height; expanded gets a sensible fixed height (no animation tricks, which
    is what caused the old panels to jam half-open)."""

    toggled = Signal(bool)

    def __init__(self, title: str, body: QWidget, expanded: bool = False, body_height: int = 150):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = SectionHeader(title, expanded)
        self.body = body
        self.body.setFixedHeight(body_height)
        self.body.setVisible(expanded)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.header.clicked.connect(self.toggle)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def toggle(self):
        self.set_expanded(not self.body.isVisible())

    def set_expanded(self, v: bool):
        self.body.setVisible(v)
        self.header.set_expanded(v)
        self.toggled.emit(v)

    def retheme(self, t):
        self.header.retheme(t)


class Toast(QFrame):
    """Transient, non-blocking message anchored bottom-centre of the window.
    Optionally carries one action button (e.g. 'Fix it', 'Undo')."""

    def __init__(self, parent: QWidget, text: str, kind: str, tokens, action: tuple | None, ms: int):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(9)
        name, color = {"success": ("check-circle", tokens.success), "error": ("x-circle", tokens.error),
                       "warn": ("alert", tokens.warning)}.get(kind, ("info", tokens.accent))
        ic = QLabel()
        ic.setPixmap(icons.pixmap(name, color.name(), 16))
        lay.addWidget(ic)
        lbl = QLabel(text)
        lbl.setObjectName("toastText")
        lbl.setWordWrap(False)
        lay.addWidget(lbl)
        self.action_btn = None
        if action:
            label, cb = action
            self.action_btn = QPushButton(label)
            self.action_btn.setObjectName("ghostBtn")
            self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.action_btn.setStyleSheet("padding: 3px 10px; font-size: 11px;")
            self.action_btn.clicked.connect(lambda: (cb(), self.dismiss()))
            lay.addWidget(self.action_btn)
        close = IconButton("x", "Dismiss", size=20, icon_size=12)
        close.retheme(tokens)
        close.clicked.connect(self.dismiss)
        lay.addWidget(close)
        self.adjustSize()

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._ms = ms

    def present(self):
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(self._ms)

    def dismiss(self):
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self):
        self.hide()
        self.deleteLater()
        mgr = getattr(self, "_manager", None)
        if mgr:
            mgr._toast_gone(self)


class ToastManager:
    """Shows one toast at a time (a new one replaces the old) and keeps a
    short history for the notification bell."""

    def __init__(self, window: QWidget):
        self.window = window
        self.tokens = None
        self.history: list[tuple[str, str]] = []   # (kind, text), newest last
        self._current: Toast | None = None
        self.bottom_margin = 40

    def show(self, text: str, kind: str = "info", action: tuple | None = None, ms: int = 3200):
        if self.tokens is None:
            return
        self.history.append((kind, text))
        del self.history[:-50]
        if self._current is not None:
            old, self._current = self._current, None
            old.hide()
            old.deleteLater()
        t = Toast(self.window, text, kind, self.tokens, action, ms if not action else max(ms, 7000))
        t._manager = self
        self._current = t
        self.reposition()
        t.present()

    def reposition(self):
        t = self._current
        if t is None:
            return
        t.adjustSize()
        w = self.window
        t.move((w.width() - t.width()) // 2, w.height() - t.height() - self.bottom_margin)

    def _toast_gone(self, toast):
        if self._current is toast:
            self._current = None


class ActionButton(QPushButton):
    """Button with a bold label and a dim keyboard-shortcut hint, like the
    mockup's 'Accept  Ctrl+Enter'. The frame (fill, border, radius, hover) is
    still drawn by the stylesheet; only the text is painted here so the label
    and the hint can have different weights/colours (QPushButton can't do
    rich text)."""

    def __init__(self, label: str, hint: str = "", kind: str = "secondary", object_name: str | None = None):
        super().__init__()
        self._label, self._hint, self._kind = label, hint, kind
        self.setObjectName(object_name or ("fixAccept" if kind == "primary" else "fixSecondary"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self._tokens = None

    def set_label(self, label: str, hint: str | None = None):
        self._label = label
        if hint is not None:
            self._hint = hint
        self.update()

    def retheme(self, t):
        self._tokens = t
        self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._label + "  " + self._hint) + 28, 36)

    def paintEvent(self, e):
        from PySide6.QtWidgets import QStyleOptionButton, QStyle
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        p = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)
        t = self._tokens
        if t is None:
            return
        enabled = self.isEnabled()
        hover = self.underMouse() and enabled
        if self._kind == "primary":
            main = t.base if hover else t.on_accent
            dim = QColor(main)
            dim.setAlpha(150)
        else:
            main = t.accent if hover else t.text
            dim = t.text_faint
        if not enabled:
            main = t.text_faint
            dim = QColor(t.text_faint)
            dim.setAlpha(150)
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Bold if self._kind == "primary" else QFont.Weight.DemiBold)
        fh = QFont(self.font())
        fh.setPixelSize(9)
        fh.setWeight(QFont.Weight.Normal)
        fm, fmh = QFontMetrics(f), QFontMetrics(fh)
        lw = fm.horizontalAdvance(self._label)
        hw = fmh.horizontalAdvance(self._hint) if self._hint else 0
        gap = 5 if self._hint else 0
        total = lw + gap + hw
        x = max(6, (self.width() - total) // 2)
        cy = self.height() // 2
        p.setFont(f)
        p.setPen(main)
        p.drawText(x, cy + (fm.ascent() - fm.descent()) // 2, self._label)
        if self._hint:
            p.setFont(fh)
            p.setPen(dim)
            p.drawText(x + lw + gap, cy + (fmh.ascent() - fmh.descent()) // 2, self._hint)
