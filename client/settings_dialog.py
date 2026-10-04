"""Settings dialog. Changes apply immediately (live) and persist."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget, QFrame)

from .widgets import ToggleSwitch


class SettingsDialog(QDialog):
    changed = Signal(str, object)    # (pref key, new value)

    def __init__(self, prefs, tokens, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setFixedWidth(460)
        self.prefs = prefs
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(4)
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        v.addWidget(title)
        v.addSpacing(8)

        self.switches: dict[str, ToggleSwitch] = {}
        self._row(v, "Font size", "Editor text size. Ctrl+scroll also zooms.", self._spin("font_size", 8, 28))
        self._row(v, "Tab width", "Spaces per indent level.", self._spin("tab_width", 1, 8))
        self._toggle(v, "word_wrap", "Word wrap", "Wrap long lines instead of scrolling sideways.", tokens)
        self._toggle(v, "auto_close", "Auto-close brackets and quotes",
                     "Typing ( [ { or a quote adds the closing one; select text first to wrap it.", tokens)
        self._toggle(v, "suggestions", "Code suggestions",
                     "Pop up completions and snippets while you type. Ctrl+Space opens them on demand.", tokens)
        self._toggle(v, "indent_guides", "Indent guides", "Faint vertical lines at each indent level.", tokens)
        self._toggle(v, "tidy_on_save", "Tidy on save",
                     "Trim trailing spaces and end the file with a newline when you save.", tokens)
        self._toggle(v, "minimap", "Minimap", "Show the file overview at the right edge of the editor.", tokens)
        self._toggle(v, "native_frame", "Use the system window frame",
                     "Turn on if the custom title bar misbehaves on your system. Takes effect after restart.", tokens)
        v.addSpacing(10)
        hint = QLabel("Theme is chosen from the palette button in the title bar \u2014 hover a theme to preview it.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.hex(tokens.text_muted)}; font-size: 11.5px; background: transparent;")
        v.addWidget(hint)
        v.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch()
        done = QPushButton("Done")
        done.setObjectName("accentBtn")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)

    def _spin(self, key, lo, hi):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(int(self.prefs.get(key)))
        s.setFixedWidth(72)
        s.valueChanged.connect(lambda val, k=key: self._emit(k, val))
        return s

    def _row(self, v, title, sub, widget):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 8)
        box = QVBoxLayout()
        box.setSpacing(1)
        a = QLabel(title)
        a.setStyleSheet("font-weight: 600; font-size: 12.5px; background: transparent;")
        b = QLabel(sub)
        b.setObjectName("muted")
        b.setWordWrap(True)
        b.setStyleSheet("font-size: 11px; background: transparent;")
        box.addWidget(a)
        box.addWidget(b)
        l.addLayout(box, stretch=1)
        l.addWidget(widget, alignment=Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(w)

    def _toggle(self, v, key, title, sub, tokens):
        sw = ToggleSwitch(bool(self.prefs.get(key)))
        sw.set_colors(tokens.accent, tokens.press, tokens.base if tokens.is_dark else tokens.raised)
        sw.toggled.connect(lambda val, k=key: self._emit(k, val))
        self.switches[key] = sw
        self._row(v, title, sub, sw)

    def _emit(self, key, val):
        self.prefs.set(key, val)
        self.changed.emit(key, val)
