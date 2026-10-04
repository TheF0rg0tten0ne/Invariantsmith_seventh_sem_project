"""Everything that frames the code editor: breadcrumb row, find/replace bar,
minimap, and the thin info strip under the text."""
import re

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget, QPushButton, QFrame)

from . import icons
from .widgets import IconButton

MINIMAP_WIDTH = 92


class Minimap(QWidget):
    """Scaled-down overview of the file: one thin bar per line (length =
    line length, colour = syntax-ish tint), error markers, and the visible
    window. Click / drag to scroll. Drawn from plain text, so it stays cheap;
    capped line count keeps huge files fast."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.tokens = None
        self.setFixedWidth(MINIMAP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dragging = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.update)
        editor.textChanged.connect(self._timer.start)
        editor.verticalScrollBar().valueChanged.connect(lambda _: self.update())
        editor.verticalScrollBar().rangeChanged.connect(lambda *_: self.update())
        editor.errorsChanged.connect(lambda _: self.update())
        editor.documentSwitched.connect(lambda _: self.update())

    def retheme(self, t):
        self.tokens = t
        self.update()

    def _row_h(self, n_lines: int) -> float:
        return max(0.8, min(3.0, (self.height() - 8) / max(1, n_lines)))

    def paintEvent(self, e):
        t = self.tokens
        p = QPainter(self)
        if t is None:
            return
        p.fillRect(self.rect(), t.base)
        p.setPen(Qt.PenStyle.NoPen)
        doc = self.editor.document()
        n = doc.blockCount()
        rh = self._row_h(n)
        shown = min(n, int(self.height() / rh))
        scale = (MINIMAP_WIDTH - 12) / 110.0

        # blocks -> bars. Python-ish keyword tint for lines starting with a keyword.
        kw = t.syntax.get("keyword", t.accent)
        cm = t.syntax.get("comment", t.text_faint)
        base = QColor(t.text_muted)
        base.setAlpha(120)
        kwc = QColor(kw)
        kwc.setAlpha(170)
        cmc = QColor(cm)
        cmc.setAlpha(140)
        block = doc.firstBlock()
        i = 0
        while block.isValid() and i < shown:
            text = block.text()
            s = text.lstrip()
            if s:
                indent = (len(text) - len(s)) * scale
                width = min(MINIMAP_WIDTH - 12 - indent, len(s) * scale)
                head = s.split(None, 1)[0] if s else ""
                col = cmc if s.startswith(("#", "//", "/*", "*")) else (
                    kwc if head in ("def", "class", "import", "from", "if", "for", "while", "return", "public",
                                    "private", "static", "int", "void", "char", "struct", "#include") else base)
                p.setBrush(col)
                p.drawRoundedRect(QRectF(6 + indent, 4 + i * rh, max(2.0, width), max(1.0, rh - 0.6)), 0.6, 0.6)
            block = block.next()
            i += 1

        for err in self.editor.current_errors:
            ln = err.get("line", 0) - 1
            if 0 <= ln < shown:
                c = QColor(t.error if err.get("severity") == "syntax" else t.warning)
                p.setBrush(c)
                p.drawRect(QRectF(0, 4 + ln * rh, 3, max(2.0, rh)))

        # visible window
        vs = self.editor.verticalScrollBar()
        total = vs.maximum() + vs.pageStep()
        if total > 0:
            top = vs.value() / total * min(n * rh, self.height() - 8) + 4
            hgt = max(14.0, vs.pageStep() / total * min(n * rh, self.height() - 8))
            hl = QColor(t.text)
            hl.setAlpha(28)
            p.setBrush(hl)
            p.drawRect(QRectF(0, top, self.width(), hgt))
        p.setPen(t.hairline)
        p.drawLine(0, 0, 0, self.height())

    def _scroll_to(self, y: float):
        vs = self.editor.verticalScrollBar()
        n = self.editor.document().blockCount()
        span = max(1.0, min(n * self._row_h(n), self.height() - 8))
        total = vs.maximum() + vs.pageStep()
        vs.setValue(int((y - 4) / span * total - vs.pageStep() / 2))

    def mousePressEvent(self, e):
        self._dragging = True
        self._scroll_to(e.position().y())

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._scroll_to(e.position().y())

    def mouseReleaseEvent(self, e):
        self._dragging = False


class FindBar(QWidget):
    """Ctrl+F / Ctrl+H. Live-highlights all matches, shows 'n matches', and
    supports case / regex toggles plus replace / replace all."""

    closed = Signal()

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setObjectName("findBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 10, 6)
        v.setSpacing(6)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setMinimumWidth(180)
        self.find_edit.textChanged.connect(self._update)
        self.find_edit.returnPressed.connect(lambda: self.step(False))
        self.case_btn = IconButton("case", "Match case", 26, 15, checkable=True)
        self.regex_btn = IconButton("regex", "Regular expression", 26, 15, checkable=True)
        self.count = QLabel("")
        self.count.setObjectName("infoItem")
        self.count.setMinimumWidth(78)
        self.prev_btn = IconButton("arrow-up", "Previous match (Shift+Enter)", 26, 15)
        self.next_btn = IconButton("arrow-down", "Next match (Enter)", 26, 15)
        self.toggle_replace = IconButton("swap", "Toggle replace (Ctrl+H)", 26, 15, checkable=True)
        self.close_btn = IconButton("x", "Close (Esc)", 26, 15)
        for w in (self.find_edit,):
            r1.addWidget(w, stretch=1)
        for w in (self.case_btn, self.regex_btn, self.count, self.prev_btn, self.next_btn,
                  self.toggle_replace, self.close_btn):
            r1.addWidget(w)
        v.addLayout(r1)

        self.replace_row = QWidget()
        r2 = QHBoxLayout(self.replace_row)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(6)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace")
        self.replace_edit.returnPressed.connect(self.replace_one)
        self.rep_btn = QPushButton("Replace")
        self.rep_all_btn = QPushButton("Replace all")
        for b in (self.rep_btn, self.rep_all_btn):
            b.setObjectName("ghostBtn")
            b.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        r2.addWidget(self.replace_edit, stretch=1)
        r2.addWidget(self.rep_btn)
        r2.addWidget(self.rep_all_btn)
        v.addWidget(self.replace_row)
        self.replace_row.setVisible(False)

        self.case_btn.toggled.connect(self._update)
        self.regex_btn.toggled.connect(self._update)
        self.prev_btn.clicked.connect(lambda: self.step(True))
        self.next_btn.clicked.connect(lambda: self.step(False))
        self.toggle_replace.toggled.connect(self.replace_row.setVisible)
        self.close_btn.clicked.connect(self.close_bar)
        self.rep_btn.clicked.connect(self.replace_one)
        self.rep_all_btn.clicked.connect(self.replace_all)
        self.setVisible(False)
        editor.documentSwitched.connect(lambda _: self._update())

    def retheme(self, t):
        for b in (self.case_btn, self.regex_btn, self.prev_btn, self.next_btn, self.toggle_replace, self.close_btn):
            b.retheme(t)

    def open_bar(self, replace: bool = False):
        self.setVisible(True)
        if replace:
            self.toggle_replace.setChecked(True)
        sel = self.editor.textCursor().selectedText()
        if sel and "\u2029" not in sel:
            self.find_edit.setText(sel)
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._update()

    def close_bar(self):
        self.setVisible(False)
        self.editor.clear_find()
        self.editor.setFocus()
        self.closed.emit()

    def _opts(self):
        return self.find_edit.text(), self.case_btn.isChecked(), self.regex_btn.isChecked()

    def _update(self, *_):
        if not self.isVisible():
            return
        text, case, rx = self._opts()
        if rx and text:
            try:
                re.compile(text)
            except re.error:
                self.count.setText("bad regex")
                self.editor.clear_find()
                return
        n = self.editor.find_all(text, case, rx)
        self.count.setText("" if not text else (f"{n} match{'es' if n != 1 else ''}" if n else "No results"))

    def step(self, backwards: bool):
        text, case, rx = self._opts()
        self.editor.find_step(text, case, rx, backwards)

    def replace_one(self):
        text, case, rx = self._opts()
        self.editor.replace_current(text, self.replace_edit.text(), case, rx)
        self._update()

    def replace_all(self):
        text, case, rx = self._opts()
        n = self.editor.replace_all(text, self.replace_edit.text(), case, rx)
        self.count.setText(f"{n} replaced")
        self.editor.clear_find()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.step(True)
            return
        super().keyPressEvent(e)


class EditorArea(QWidget):
    """breadcrumb / find bar / (editor | minimap) / info strip"""

    crumbClicked = Signal()

    def __init__(self, editor):
        super().__init__()
        self.setObjectName("editorArea")
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.crumb_bar = QWidget()
        self.crumb_bar.setObjectName("breadcrumb")
        self.crumb_bar.setFixedHeight(30)
        cl = QHBoxLayout(self.crumb_bar)
        cl.setContentsMargins(14, 0, 12, 0)
        cl.setSpacing(6)
        self.crumb_layout = cl
        lay.addWidget(self.crumb_bar)

        self.find_bar = FindBar(editor)
        lay.addWidget(self.find_bar)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(editor, stretch=1)
        self.minimap = Minimap(editor)
        row.addWidget(self.minimap)
        lay.addLayout(row, stretch=1)

        self.info = QWidget()
        self.info.setObjectName("infoStrip")
        self.info.setFixedHeight(26)
        il = QHBoxLayout(self.info)
        il.setContentsMargins(14, 0, 14, 0)
        il.setSpacing(14)
        self.pos_label = QLabel("Ln 1, Col 1")
        self.spaces_label = QLabel("Spaces: 4")
        self.enc_label = QLabel("UTF-8")
        self.eol_label = QLabel("LF")
        self.lang_label = QLabel("")
        for w in (self.pos_label, self.spaces_label, self.enc_label, self.eol_label):
            w.setObjectName("infoItem")
        il.addStretch()
        for w in (self.pos_label, self.spaces_label, self.enc_label, self.eol_label):
            il.addWidget(w)
        self.lang_chip = QLabel("")
        self.lang_chip.setObjectName("infoItem")
        il.addWidget(self.lang_chip)
        self.ok_icon = QLabel()
        il.addWidget(self.ok_icon)
        lay.addWidget(self.info)
        self._tokens = None
        self._health = "ok"

        editor.cursorMoved.connect(lambda l, c: self.pos_label.setText(f"Ln {l}, Col {c}"))

    def set_minimap_visible(self, v: bool):
        self._minimap_wanted = v
        self._sync_minimap()

    def _sync_minimap(self):
        # In a narrow editor the minimap would eat a quarter of the width, so it
        # steps aside below ~620px even when enabled.
        self.minimap.setVisible(getattr(self, "_minimap_wanted", True) and self.width() >= 620)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_minimap()

    def set_tab_width(self, n: int):
        self.spaces_label.setText(f"Spaces: {n}")

    def set_language_label(self, text: str, language: str):
        self._language = language
        self.lang_chip.setText(text)

    def set_health(self, state: str):
        """'ok' | 'errors' | 'warnings' -- the tick at the right of the strip."""
        self._health = state
        self._paint_health()

    def _paint_health(self):
        t = self._tokens
        if t is None:
            return
        name, col = {"ok": ("check", t.success), "errors": ("x-circle", t.error),
                     "warnings": ("alert", t.warning)}.get(self._health, ("check", t.success))
        self.ok_icon.setPixmap(icons.pixmap(name, col.name(), 14))

    def set_path(self, parts: list[str]):
        cl = self.crumb_layout
        while cl.count():
            it = cl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        t = self._tokens
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if i:
                sep = QLabel()
                if t:
                    sep.setPixmap(icons.pixmap("chevron-right", t.hex(t.text_faint), 10))
                cl.addWidget(sep)
            if last and getattr(self, "_language", None):
                ic = QLabel()
                ic.setPixmap(icons.lang_pixmap(self._language, 14))
                cl.addWidget(ic)
            lab = QLabel(part)
            lab.setObjectName("crumbActive" if last else "crumb")
            cl.addWidget(lab)
        cl.addStretch()

    def retheme(self, t):
        self._tokens = t
        self.minimap.retheme(t)
        self.find_bar.retheme(t)
        self._paint_health()
