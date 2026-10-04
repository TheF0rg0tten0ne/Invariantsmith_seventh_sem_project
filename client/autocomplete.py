"""
Editor autocomplete: the pure logic (context detection, ranking, snippet
parsing), the popup widget, and the snippet session that lets Tab hop between
placeholders.

Split so the logic is testable without a display:

    analyze_context()   what is the caret doing? (typing a word, inside
                        `#include <`, after a dot, in a comment, ...)
    query()             context -> ranked list of Completion
    parse_snippet()     "for (int ${1:i} ...)" -> text + tab-stop offsets
    CompletionPopup     the floating list
    SnippetSession      live tab stops (with mirrored placeholders)
"""
import re
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (QFrame, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout)

from .completion_data import (Completion, MODULES, c_include_lines, completions_for, member_completions)

MAX_RESULTS = 60
MAX_DOC_WORDS = 400

_KIND_RANK = {"snippet": 0, "func": 1, "member": 1, "keyword": 1, "type": 1, "module": 1, "word": 2}
_KIND_BADGE = {"snippet": "S", "keyword": "k", "func": "f", "member": "m", "type": "T", "module": "M", "word": "w"}
# which theme colour tints each kind's badge
_KIND_COLOR = {"snippet": "string", "keyword": "keyword", "func": "function", "member": "function",
               "type": "class", "module": "class", "word": "variable"}


# ---------------------------------------------------------------------------
# Snippets
# ---------------------------------------------------------------------------
_SNIP_TOKEN = re.compile(r"\$\{(\d+):([^}]*)\}|\$\{(\d+)\}|\$(\d+)")


def parse_snippet(body: str, unit: str, indent: str) -> tuple[str, list[tuple[int, int, int]]]:
    """Expand a snippet body.

    Returns (text, stops) where stops is a list of (number, start, end) offsets
    into ``text`` in order of appearance. ``\\t`` becomes ``unit`` and every
    newline is followed by ``indent`` so the snippet lines up with the line it
    was typed on.
    """
    def lit(s: str) -> str:
        return s.replace("\t", unit).replace("\n", "\n" + indent)

    out: list[str] = []
    stops: list[tuple[int, int, int]] = []
    pos = length = 0
    for m in _SNIP_TOKEN.finditer(body):
        seg = lit(body[pos:m.start()])
        out.append(seg)
        length += len(seg)
        if m.group(1) is not None:
            num, default = int(m.group(1)), m.group(2)
        elif m.group(3) is not None:
            num, default = int(m.group(3)), ""
        else:
            num, default = int(m.group(4)), ""
        stops.append((num, length, length + len(default)))
        out.append(default)
        length += len(default)
        pos = m.end()
    out.append(lit(body[pos:]))
    return "".join(out), stops


# ---------------------------------------------------------------------------
# Context analysis
# ---------------------------------------------------------------------------
@dataclass
class Context:
    kind: str            # "word" | "include" | "import" | "member"
    prefix: str          # what has been typed of the thing being completed
    start: int           # column in the line where ``prefix`` begins
    extra: str = ""      # include: opening delimiter; member: qualifier


def line_state(line: str, language: str) -> tuple[str, str]:
    """Scan one line prefix: ('code'|'str'|'comment', open-quote-char)."""
    quote = ""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        else:
            if ch in "\"'":
                quote = ch
            elif language == "python" and ch == "#":
                return "comment", ""
            elif language != "python" and line.startswith("//", i):
                return "comment", ""
        i += 1
    return ("str", quote) if quote else ("code", "")


def in_block_literal(text_before: str, language: str) -> bool:
    """Inside a /* */ comment (C, Java) or a triple-quoted string (Python)?"""
    if language == "python":
        return any(text_before.count(q) % 2 for q in ('"""', "'''"))
    return text_before.rfind("/*") > text_before.rfind("*/")


def in_literal(line_prefix: str, text_before: str, language: str) -> bool:
    if in_block_literal(text_before, language):
        return True
    return line_state(line_prefix, language)[0] != "code"


_WORD_AT_END = re.compile(r"(?<!\w)[A-Za-z_]\w*$")
_QUALIFIER = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$")


def analyze_context(line_prefix: str, text_before: str, language: str) -> Context | None:
    """Decide what kind of completion (if any) makes sense at the caret."""
    line = line_prefix

    if language == "c":
        m = re.match(r"^\s*#\s*include\s*([<\"])([\w./-]*)$", line)
        if m:
            return Context("include", m.group(2), len(line) - len(m.group(2)), m.group(1))
        if re.match(r"^\s*#\s*include\s+$", line):
            return Context("include", "", len(line), "")

    if in_literal(line, text_before, language):
        return None

    if language == "python":
        m = re.match(r"^\s*(?:from|import)\s+((?:[\w.]+\s*,\s*)*)([\w.]*)$", line)
        if m and not re.match(r"^\s*from\s+\S+\s", line):
            return Context("import", m.group(2), len(line) - len(m.group(2)))
    elif language == "java":
        m = re.match(r"^\s*import\s+(?:static\s+)?([\w.*]*)$", line)
        if m:
            return Context("import", m.group(1), len(line) - len(m.group(1)))

    wm = _WORD_AT_END.search(line)
    wstart = wm.start() if wm else len(line)
    word = wm.group(0) if wm else ""

    # member access:  qualifier . prefix
    if wstart > 0 and line[wstart - 1] == "." and language in ("python", "java"):
        if wstart >= 2 and line[wstart - 2] == ".":
            return None                       # "..", an ellipsis or a range
        head = line[:wstart - 1]
        if head and head[-1].isdigit() and not _QUALIFIER.search(head):
            return None                       # number literal such as 3.
        qm = _QUALIFIER.search(head)
        return Context("member", word, wstart, qm.group(1) if qm else "")
    if wstart > 0 and line[wstart - 1] == "." and language == "c":
        return None
    if wstart >= 2 and language == "c" and line[wstart - 2:wstart] == "->":
        return None

    if language == "c":
        if wstart > 0 and line[wstart - 1] == "#" and not line[:wstart - 1].strip():
            return Context("word", "#" + word, wstart - 1)
        if re.match(r"^\s*#$", line):
            return Context("word", "#", len(line) - 1)

    if not word:
        return None
    return Context("word", word, wstart)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def _subsequence(needle: str, hay: str) -> bool:
    """Loose match: same first letter, remaining letters in order (``prf`` ->
    ``printf``). Anchoring the first letter keeps the list from filling up with
    unrelated words (``int`` should not pull in ``fprintf``)."""
    if not needle or not hay or needle[0] != hay[0]:
        return False
    it = iter(hay[1:])
    return all(ch in it for ch in needle[1:])


def rank(cands: list[Completion], prefix: str, segment_match: bool = False) -> list[Completion]:
    """Order candidates for ``prefix``; drop non-matches.

    tier 0  same-case prefix match            (``pri`` -> ``print``)
    tier 1  case-insensitive prefix match
    tier 2  match on the last dotted segment  (imports: ``Scan`` -> java.util.Scanner)
    tier 3  loose subsequence match, only once 3+ characters are typed
    """
    p = prefix.lower()
    scored = []
    for order, c in enumerate(cands):
        label, low = c.label, c.label.lower()
        if not p:
            tier = 1
        elif label.startswith(prefix):
            tier = 0
        elif low.startswith(p):
            tier = 1
        elif segment_match and low.rsplit(".", 1)[-1].startswith(p):
            tier = 2
        elif len(p) >= 3 and _subsequence(p, low):
            tier = 3
        else:
            continue
        scored.append((tier, _KIND_RANK.get(c.kind, 2), len(label), order, c))
    # ties keep the data-table order, so hand-ordered snippets (sout before
    # souf) win over an alphabetical accident
    scored.sort(key=lambda t: t[:4])
    return [t[4] for t in scored[:MAX_RESULTS]]


_DOC_WORD = re.compile(r"[A-Za-z_]\w{2,}")


def document_words(text: str, exclude: set[str], prefix: str) -> list[Completion]:
    p = prefix.lower()
    seen: set[str] = set()
    out: list[Completion] = []
    for m in _DOC_WORD.finditer(text[:400_000]):
        w = m.group(0)
        if w in seen or w in exclude or w == prefix:
            continue
        seen.add(w)
        if w.lower().startswith(p) or (len(p) >= 3 and _subsequence(p, w.lower())):
            out.append(Completion(w, "word", w, "in this file"))
            if len(out) >= MAX_DOC_WORDS:
                break
    return out


def query(language: str, line_prefix: str, text_before: str, full_text: str,
          manual: bool = False, min_chars: int = 2) -> tuple[Context, list[Completion]] | None:
    """Everything the editor needs to decide whether/what to show."""
    ctx = analyze_context(line_prefix, text_before, language)
    if ctx is None and manual and not in_literal(line_prefix, text_before, language):
        ctx = Context("word", "", len(line_prefix))     # Ctrl+Space on an empty spot: list everything
    if ctx is None:
        return None

    if ctx.kind == "include":
        cands = [Completion(h, "module", h, "header") for h in MODULES["c"]]
        items = rank(cands, ctx.prefix)
    elif ctx.kind == "import":
        cands = [Completion(m, "module", m, "module" if language == "python" else "import")
                 for m in MODULES.get(language, [])]
        items = rank(cands, ctx.prefix, segment_match=True)
    elif ctx.kind == "member":
        items = rank(member_completions(language, ctx.extra), ctx.prefix)
    else:
        if not manual and len(ctx.prefix.lstrip("#")) < min_chars and ctx.prefix != "#":
            return None
        base = completions_for(language)
        if language == "c" and ctx.prefix.startswith("#"):
            base = c_include_lines() + base
        labels = {c.label for c in base}
        items = rank(base + document_words(full_text, labels, ctx.prefix), ctx.prefix)
    if not items:
        return None
    if len(items) == 1 and items[0].label == ctx.prefix and items[0].body == items[0].label:
        return None           # the word is already typed in full; nothing to offer
    return ctx, items


# ---------------------------------------------------------------------------
# Popup widget
# ---------------------------------------------------------------------------
class _Delegate(QStyledItemDelegate):
    def __init__(self, popup: "CompletionPopup"):
        super().__init__(popup)
        self.popup = popup

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.popup.ROW_H)

    def paint(self, p: QPainter, opt, idx):
        c: Completion = idx.data(Qt.ItemDataRole.UserRole)
        t = self.popup.tokens
        if c is None or t is None:
            return
        r = opt.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.accent_bg)
            p.drawRoundedRect(r.adjusted(3, 1, -3, -1), 5, 5)

        # kind badge
        tint = QColor(t.syntax.get(_KIND_COLOR.get(c.kind, "variable"), t.accent))
        badge = QRect(r.left() + 9, r.top() + (r.height() - 16) // 2, 16, 16)
        fill = QColor(tint)
        fill.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(badge, 4, 4)
        p.setPen(tint)
        bf = p.font()
        bf.setPointSizeF(max(7.0, self.popup.font_pt - 3.0))
        bf.setBold(True)
        p.setFont(bf)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, _KIND_BADGE.get(c.kind, "w"))

        # label (typed prefix highlighted)
        lf = self.popup.code_font
        p.setFont(lf)
        fm = QFontMetrics(lf)
        x = badge.right() + 9
        text_h = r.height()
        pre = self.popup.prefix
        label = c.label
        n = len(pre) if pre and label.lower().startswith(pre.lower()) else 0
        if n:
            p.setPen(t.accent)
            p.drawText(QRect(x, r.top(), r.right() - x, text_h), Qt.AlignmentFlag.AlignVCenter, label[:n])
            x += fm.horizontalAdvance(label[:n])
        p.setPen(t.text)
        p.drawText(QRect(x, r.top(), r.right() - x, text_h), Qt.AlignmentFlag.AlignVCenter, label[n:])
        x += fm.horizontalAdvance(label[n:])

        # detail, right-aligned and muted
        if c.detail:
            df = self.popup.ui_font
            p.setFont(df)
            dfm = QFontMetrics(df)
            room = r.right() - x - 22
            if room > 30:
                txt = dfm.elidedText(c.detail, Qt.TextElideMode.ElideRight, room)
                p.setPen(t.text_muted)
                p.drawText(QRect(x + 12, r.top(), r.right() - x - 22, text_h),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, txt)
        p.restore()


class CompletionPopup(QFrame):
    """Floating suggestion list. Never takes keyboard focus -- the editor keeps
    it and forwards Up/Down/Tab/Enter/Esc here."""

    accepted = Signal(object)        # a Completion was chosen with the mouse

    ROW_H = 26
    MAX_ROWS = 9

    def __init__(self, editor):
        super().__init__(editor.viewport())
        self.setObjectName("completionPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tokens = None
        self.prefix = ""
        self.font_pt = 11.0
        self.code_font = editor.font()
        self.ui_font = editor.font()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 4, 3, 4)
        self.list = QListWidget(self)
        self.list.setObjectName("completionList")
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(_Delegate(self))
        self.list.itemClicked.connect(lambda it: self.accepted.emit(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.list)
        self.hide()

    # -- look ------------------------------------------------------------
    def retheme(self, tokens, scrollbar_css: str, code_font, ui_font):
        self.tokens = tokens
        self.code_font = code_font
        self.ui_font = ui_font
        self.font_pt = code_font.pointSizeF() if code_font.pointSizeF() > 0 else 11.0
        self.setStyleSheet(
            f"QFrame#completionPopup {{ background: {tokens.hex(tokens.raised)};"
            f" border: 1px solid {tokens.hex(tokens.hairline_strong)}; border-radius: 9px; }}"
            f"QListWidget#completionList {{ background: transparent; border: none; outline: none; }}"
            + scrollbar_css)
        self.list.viewport().update()

    # -- content ---------------------------------------------------------
    def set_items(self, items: list[Completion], prefix: str, select: int = 0):
        self.prefix = prefix
        keep = self.current_completion()
        self.list.clear()
        fm = QFontMetrics(self.code_font)
        dfm = QFontMetrics(self.ui_font)
        width = 280
        for c in items:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, c)
            it.setSizeHint(QSize(10, self.ROW_H))
            self.list.addItem(it)
            width = max(width, 52 + fm.horizontalAdvance(c.label) + 24 + dfm.horizontalAdvance(c.detail))
        width = min(width, 560)
        rows = min(len(items), self.MAX_ROWS)
        self.setFixedSize(width + 8, rows * self.ROW_H + 10)
        row = 0
        if keep is not None:      # keep the user's highlighted choice while they keep typing
            for i, c in enumerate(items):
                if c.label == keep.label and c.kind == keep.kind:
                    row = i
                    break
        self.list.setCurrentRow(row if select == 0 else select)

    def current_completion(self) -> Completion | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def move(self, delta: int):
        n = self.list.count()
        if n:
            self.list.setCurrentRow((self.list.currentRow() + delta) % n if abs(delta) == 1
                                    else max(0, min(n - 1, self.list.currentRow() + delta)))

    # -- placement -------------------------------------------------------
    def place(self, anchor: QRect):
        """Below the anchor rect (caret/word start, viewport coordinates), or
        above when there is no room."""
        vp = self.parentWidget().rect()
        x = max(2, min(anchor.left() - 28, vp.width() - self.width() - 2))
        y = anchor.bottom() + 3
        if y + self.height() > vp.height() and anchor.top() - self.height() - 3 > 0:
            y = anchor.top() - self.height() - 3
        super().move(x, y)
        self.raise_()
        self.show()


# ---------------------------------------------------------------------------
# Snippet session
# ---------------------------------------------------------------------------
class SnippetSession:
    """Live tab stops for one expanded snippet.

    Each stop is a (start, end) pair of QTextCursors: ``start`` keeps its
    position when text is inserted at it and ``end`` moves along, so the pair
    keeps covering whatever the user types in the placeholder. Stops sharing a
    number are mirrors of the first one.
    """

    def __init__(self, editor, base: int, text: str, stops: list[tuple[int, int, int]]):
        doc = editor.document()
        self.editor = editor
        self.syncing = False
        self.stops: dict[int, list[tuple[QTextCursor, QTextCursor]]] = {}

        def pair(a_pos: int, b_pos: int):
            a = QTextCursor(doc)
            a.setPosition(a_pos)
            a.setKeepPositionOnInsert(True)
            b = QTextCursor(doc)
            b.setPosition(b_pos)
            return a, b

        for num, s, e in stops:
            self.stops.setdefault(num, []).append(pair(base + s, base + e))
        if 0 not in self.stops:
            self.stops[0] = [pair(base + len(text), base + len(text))]
        self.order = sorted(n for n in self.stops if n) + [0]
        self.idx = -1
        self.span_start, self.span_end = pair(base, base + len(text))
        # typing exactly at the end of the snippet is "after" it, not inside it
        self.span_end.setKeepPositionOnInsert(True)

    @property
    def number(self) -> int:
        return self.order[self.idx] if 0 <= self.idx < len(self.order) else -1

    def contains(self, pos: int) -> bool:
        return self.span_start.position() <= pos <= self.span_end.position()

    def _select(self, i: int):
        self.idx = i
        a, b = self.stops[self.order[i]][0]
        c = QTextCursor(self.editor.document())
        c.setPosition(a.position())
        c.setPosition(max(a.position(), b.position()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(c)

    def advance(self, step: int = 1) -> bool:
        """Move to the next/previous stop. Returns False when the session is
        over (the caret has reached the final stop)."""
        new = self.idx + step
        if new < 0:
            new = 0
        if new >= len(self.order):
            new = len(self.order) - 1
        self._select(new)
        return self.order[new] != 0

    def start(self) -> bool:
        return self.advance(1)

    def sync_mirrors(self):
        """Copy what was typed in the active placeholder to its mirrors."""
        pairs = self.stops.get(self.number)
        if not pairs or len(pairs) < 2 or self.syncing:
            return
        a, b = pairs[0]
        doc = self.editor.document()
        src = QTextCursor(doc)
        src.setPosition(a.position())
        src.setPosition(max(a.position(), b.position()), QTextCursor.MoveMode.KeepAnchor)
        text = src.selectedText()
        self.syncing = True
        try:
            for ma, mb in pairs[1:]:
                c = QTextCursor(doc)
                c.setPosition(ma.position())
                c.setPosition(max(ma.position(), mb.position()), QTextCursor.MoveMode.KeepAnchor)
                if c.selectedText() != text:
                    c.joinPreviousEditBlock()
                    c.insertText(text)
                    c.endEditBlock()
        finally:
            self.syncing = False
