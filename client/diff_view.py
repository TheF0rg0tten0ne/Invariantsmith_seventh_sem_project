"""
Diff rendering for the Fix Insight panel.

Matches the design mockup: a hunk header line with the enclosing function
signature, a gutter with line numbers and a +/- sign, and full-width red /
green row backgrounds -- in either a unified view or a true side-by-side
view (two aligned panes with synced scrolling).

Parsing is separate from painting (parse_unified_diff / align_split) so it is
unit-testable without a GUI.
"""
import re
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QSplitter, QStackedWidget, QTextEdit, QWidget,
)

from . import design
from .widgets import IconButton

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_SIG_RE = re.compile(
    r"^\s*(?:async\s+def|def|class)\s+.+$"                       # python
    r"|^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*"
    r"[\w<>\[\],\s\*]+\s+\**\w+\s*\([^;{}]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{?\s*$"  # c / java
)


@dataclass
class Row:
    kind: str          # 'ctx' | 'add' | 'del' | 'hunk' | 'pad'
    number: int | None
    text: str


def _enclosing_signature(code_lines: list[str], before_line: int) -> str | None:
    """Nearest def/class/function signature at or above 1-based `before_line`."""
    for i in range(min(before_line, len(code_lines)) - 1, -1, -1):
        line = code_lines[i]
        if line.strip() and not line.lstrip().startswith(("#", "//", "*", "/*")) and _SIG_RE.match(line):
            stripped = line.strip()
            if stripped.startswith(("if ", "for ", "while ", "switch", "else", "return")):
                continue
            return stripped.rstrip("{").rstrip()
    return None


def parse_unified_diff(diff_text: str, code: str = "") -> list[Row]:
    """Unified diff -> display rows. Added lines carry their NEW line number,
    removed lines their OLD line number, context lines the new number."""
    code_lines = code.split("\n") if code else []
    rows: list[Row] = []
    old_no = new_no = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith(("--- ", "+++ ")) and not in_hunk:
            continue
        m = _HUNK_RE.match(raw)
        if m:
            in_hunk = True
            old_no, new_no = int(m.group(1)), int(m.group(3))
            sig = _enclosing_signature(code_lines, old_no) if code_lines else None
            label = f"@@ {sig}" if sig else f"@@ -{m.group(1)} +{m.group(3)} @@"
            rows.append(Row("hunk", None, label))
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            rows.append(Row("add", new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            rows.append(Row("del", old_no, raw[1:]))
            old_no += 1
        elif raw.startswith("\\"):
            continue   # "\ No newline at end of file"
        else:
            rows.append(Row("ctx", new_no, raw[1:] if raw.startswith(" ") else raw))
            old_no += 1
            new_no += 1
    return rows


def align_split(rows: list[Row]) -> tuple[list[Row], list[Row]]:
    """Rows -> (left, right) panes of equal length. A run of removals followed
    by a run of additions is paired line-for-line; the shorter side is padded."""
    left: list[Row] = []
    right: list[Row] = []
    i = 0
    n = len(rows)
    while i < n:
        r = rows[i]
        if r.kind in ("ctx", "hunk"):
            left.append(r)
            right.append(r)
            i += 1
            continue
        dels, adds = [], []
        while i < n and rows[i].kind == "del":
            dels.append(rows[i]); i += 1
        while i < n and rows[i].kind == "add":
            adds.append(rows[i]); i += 1
        for k in range(max(len(dels), len(adds))):
            left.append(dels[k] if k < len(dels) else Row("pad", None, ""))
            right.append(adds[k] if k < len(adds) else Row("pad", None, ""))
    return left, right


class _Gutter(QWidget):
    def __init__(self, pane: "CodePane"):
        super().__init__(pane)
        self.pane = pane

    def sizeHint(self):
        return QSize(self.pane.gutter_width(), 0)

    def paintEvent(self, event):
        self.pane.paint_gutter(event)


class CodePane(QPlainTextEdit):
    """Read-only monospace pane that renders Rows with a number+sign gutter
    and full-width coloured backgrounds."""

    def __init__(self, show_sign: bool = True, right_margin: int = 0):
        super().__init__()
        self._right_margin = right_margin
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.rows: list[Row] = []
        self._show_sign = show_sign
        self._tokens = None
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _: self._update_margin())
        self.updateRequest.connect(self._on_update_request)
        self._update_margin()

    # -- data ---------------------------------------------------------------
    def set_rows(self, rows: list[Row]):
        self.rows = rows
        self._gutter.setVisible(True)
        self.setPlainText("\n".join(r.text for r in rows))
        self._update_margin()
        self._apply_row_colors()
        self.verticalScrollBar().setValue(0)
        self._gutter.update()

    def set_message(self, text: str):
        self.rows = []
        self.setPlainText(text)
        self.setExtraSelections([])
        self._update_margin()
        self._gutter.setVisible(False)

    # -- theming ------------------------------------------------------------
    def retheme(self, t):
        self._tokens = t
        self.setFont(design.mono_font(10.0))
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.hex(t.frame)}; color: {t.hex(t.text)}; border: none; }}"
        )
        self._apply_row_colors()
        self._gutter.update()

    def _apply_row_colors(self):
        t = self._tokens
        if t is None or not self.rows:
            return
        sels = []
        doc = self.document()
        for i, r in enumerate(self.rows):
            bg = {"add": t.diff_add_bg, "del": t.diff_rm_bg}.get(r.kind)
            fg = {"add": t.diff_add_fg, "del": t.diff_rm_fg, "hunk": t.text_muted,
                  "pad": t.text_faint}.get(r.kind)
            if bg is None and fg is None:
                continue
            block = doc.findBlockByNumber(i)
            if not block.isValid():
                continue
            fmt = QTextCharFormat()
            if bg is not None:
                fmt.setBackground(bg)
            if fg is not None:
                fmt.setForeground(fg)
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel = QTextEdit.ExtraSelection()
            cur = self.textCursor()
            cur.setPosition(block.position())
            cur.clearSelection()
            sel.cursor = cur
            sel.format = fmt
            sels.append(sel)
        self.setExtraSelections(sels)

    # -- gutter -------------------------------------------------------------
    def gutter_width(self) -> int:
        if not self.rows:
            return 0          # message mode ("Thinking...", "No fix yet"): no gutter at all
        digits = max([len(str(r.number)) for r in self.rows if r.number] + [2])
        w = self.fontMetrics().horizontalAdvance("9") * digits + 14
        if self._show_sign:
            w += self.fontMetrics().horizontalAdvance("+") + 6
        return w

    def _update_margin(self):
        self.setViewportMargins(self.gutter_width(), 0, self._right_margin, 0)

    def _on_update_request(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        t = self._tokens
        p = QPainter(self._gutter)
        bg = t.frame if t else QColor("#111")
        p.fillRect(event.rect(), bg)
        if t is None:
            return
        fm = self.fontMetrics()
        num_w = self._gutter.width() - (fm.horizontalAdvance("+") + 6 if self._show_sign else 0) - 8
        block = self.firstVisibleBlock()
        i = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top() and i < len(self.rows):
                r = self.rows[i]
                if r.kind in ("add", "del"):
                    row_bg = t.diff_add_bg if r.kind == "add" else t.diff_rm_bg
                    p.fillRect(0, int(top), self._gutter.width(), int(bottom - top), row_bg)
                if r.number is not None:
                    col = {"add": t.diff_add_fg, "del": t.diff_rm_fg}.get(r.kind, t.text_faint)
                    p.setPen(col)
                    p.drawText(0, int(top), num_w, fm.height(), Qt.AlignmentFlag.AlignRight, str(r.number))
                    if self._show_sign and r.kind in ("add", "del"):
                        p.drawText(num_w + 6, int(top), fm.horizontalAdvance("+") + 4, fm.height(),
                                   Qt.AlignmentFlag.AlignLeft, "+" if r.kind == "add" else "\u2212")
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            i += 1


class DiffView(QWidget):
    """Unified / side-by-side diff with a floating copy button."""

    copyRequested = Signal()

    def __init__(self):
        super().__init__()
        self._mode = "unified"
        self._diff = ""
        self._code = ""
        self._tokens = None

        self.stack = QStackedWidget(self)
        self.unified = CodePane(show_sign=True, right_margin=30)
        self.split_left = CodePane(show_sign=False)
        self.split_right = CodePane(show_sign=False, right_margin=30)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.split_left)
        splitter.addWidget(self.split_right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.split = splitter
        self.stack.addWidget(self.unified)
        self.stack.addWidget(self.split)
        # keep the two split panes scrolling together
        self.split_left.verticalScrollBar().valueChanged.connect(self.split_right.verticalScrollBar().setValue)
        self.split_right.verticalScrollBar().valueChanged.connect(self.split_left.verticalScrollBar().setValue)
        self.split_left.horizontalScrollBar().valueChanged.connect(self.split_right.horizontalScrollBar().setValue)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self.copy_btn = IconButton("copy", "Copy diff", size=24, icon_size=14)
        self.copy_btn.setParent(self)
        self.copy_btn.clicked.connect(self.copyRequested)
        self.copy_btn.setVisible(False)
        self.setMinimumHeight(110)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.copy_btn.move(self.width() - self.copy_btn.width() - 8, 4)
        self.copy_btn.raise_()

    def retheme(self, t):
        self._tokens = t
        for pane in (self.unified, self.split_left, self.split_right):
            pane.retheme(t)
        self.copy_btn.retheme(t)
        self.setStyleSheet(
            f"QSplitter::handle {{ background: {t.hex(t.hairline)}; }} "
            f"DiffView {{ border: 1px solid {t.hex(t.hairline)}; border-radius: 8px; }}"
        )

    def set_mode(self, mode: str):
        self._mode = mode
        self.stack.setCurrentIndex(0 if mode == "unified" else 1)
        if self._diff:
            self._render()

    def mode(self) -> str:
        return self._mode

    def set_diff(self, diff_text: str, code: str = ""):
        self._diff, self._code = diff_text, code
        self.copy_btn.setVisible(bool(diff_text))
        self._render()

    def set_message(self, text: str):
        self._diff = ""
        self.copy_btn.setVisible(False)
        self.unified.set_message(text)
        self.split_left.set_message(text)
        self.split_right.set_message("")

    def _render(self):
        rows = parse_unified_diff(self._diff, self._code)
        if not rows:
            self.set_message(self._diff or "(no changes)")
            return
        if self._mode == "unified":
            self.unified.set_rows(rows)
        else:
            left, right = align_split(rows)
            self.split_left.set_rows(left)
            self.split_right.set_rows(right)
