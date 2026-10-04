"""
The editor core: a QPlainTextEdit with a line-number gutter (with error
markers), tree-sitter highlighting, a debounced live-analysis loop talking to
the Invariantsmith API, and the everyday editing niceties people expect:
auto-indent, Tab/Shift+Tab block indent, Ctrl+/ comment toggle, duplicate /
move line, Ctrl+wheel zoom and find/replace -- plus (v29) auto-closing
brackets and quotes, a suggestion popup with snippets (see autocomplete.py),
bracket matching, indent guides and VS Code-style line commands.

It can hold many Documents (see documents.py) and swaps between them without
losing undo history, caret, scroll or the last analysis result.

Live flow:
    keystroke -> restart debounce -> (after LIVE_ANALYSIS_DEBOUNCE_MS idle)
    -> reparse for highlighting (local) AND /analyze on a worker thread ->
    squiggles + Problems list from the result.

Nothing here calls the network on the GUI thread.
"""
import re

from PySide6.QtCore import Qt, QRect, QSize, QTimer, QThreadPool, QRunnable, Signal, QObject, QRegularExpression
from PySide6.QtGui import (QPainter, QColor, QTextFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QKeySequence, QFontMetrics, QGuiApplication)
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit

from . import config
from . import design
from . import icons
from .autocomplete import (CompletionPopup, SnippetSession, in_literal, line_state, parse_snippet, query)
from .documents import Document
from .highlighter import TreeSitterHighlighter
from .theme import Theme

_COMMENT_PREFIX = {"python": "# ", "c": "// ", "java": "// "}


class _WorkerSignals(QObject):
    # NOTE: slots connected to these MUST be bound methods of a long-lived
    # QObject. A lambda has no receiver object, and the worker (hence this
    # signals object) is destroyed as soon as run() returns, which silently
    # drops the queued emission -- results then never reach the UI.
    finished = Signal(int, int, list, str)   # (doc id, request seq, errors, detected_language)
    failed = Signal(str)


class _AnalyzeWorker(QRunnable):
    """Runs api_client.analyze() off the GUI thread."""

    def __init__(self, api_client, doc_id: int, seq: int, file_path: str, code: str, language: str | None):
        super().__init__()
        self.doc_id, self.seq = doc_id, seq
        self.api_client = api_client
        self.file_path = file_path
        self.code = code
        self.language = language
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.api_client.analyze(self.file_path, self.code, self.language)
            self.signals.finished.emit(self.doc_id, self.seq, result.get("errors", []),
                                       result.get("detected_language", "python"))
        except Exception as e:
            self.signals.failed.emit(str(e))


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)

    def mousePressEvent(self, event):
        # Clicking an error marker in the gutter requests a fix for it.
        y = event.position().y()
        blk = self.editor.firstVisibleBlock()
        top = self.editor.blockBoundingGeometry(blk).translated(self.editor.contentOffset()).top()
        while blk.isValid():
            h = self.editor.blockBoundingRect(blk).height()
            if top <= y < top + h:
                line = blk.blockNumber() + 1
                for err in self.editor.current_errors:
                    if err.get("line") == line:
                        self.editor.errorClicked.emit(err)
                        return
                break
            top += h
            blk = blk.next()


class CodeEditor(QPlainTextEdit):
    errorsChanged = Signal(list)     # a fresh /analyze result arrived
    errorClicked = Signal(dict)      # the user clicked a line/marker with an error
    cursorMoved = Signal(int, int)   # (1-based line, 1-based column)
    languageDetected = Signal(str)   # the *effective* language changed
    analysisFailed = Signal(str)     # server unreachable etc. (status bar listens)
    analysisStarted = Signal()
    documentSwitched = Signal(object)
    zoomChanged = Signal(int)

    def __init__(self, api_client, theme: Theme | None = None):
        super().__init__()
        self.api_client = api_client
        self._thread_pool = QThreadPool.globalInstance()
        self.current: Document | None = None
        self.documents: list[Document] = []
        self.font_size = 11.0
        self.tab_width = 4
        self._find_selections: list = []
        self._error_selections: list = []
        self._current_line_selection = None
        self._suppress_change_handler = False
        self._analysis_seq: dict[int, int] = {}   # doc id -> newest request number
        self.theme = theme
        # editing niceties (all switchable in Settings)
        self.auto_close = True        # auto-close brackets/quotes, overtype, surround
        self.suggestions = True       # autocomplete popup + snippets
        self.indent_guides = True
        self._closers: list[QTextCursor] = []      # auto-inserted closers we may overtype
        self._snippet: SnippetSession | None = None
        self._cmp_ctx = None
        self._cmp_start = 0
        self._popup_navigated = False
        self._bracket_selections: list = []
        self._word_selections: list = []
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width()

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(config.LIVE_ANALYSIS_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._run_live_analysis)
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)

        self._popup = CompletionPopup(self)
        self._popup.accepted.connect(self._accept_completion)
        self._word_timer = QTimer(self)
        self._word_timer.setSingleShot(True)
        self._word_timer.setInterval(160)
        self._word_timer.timeout.connect(self._update_word_highlights)
        self.verticalScrollBar().valueChanged.connect(lambda _=0: self._hide_popup())

        # a scratch document so the widget is never document-less
        self.set_current(self.new_document("", None, "Untitled"))

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def new_document(self, text: str = "", path: str | None = None, name: str = "Untitled",
                     mode: str = "auto", language: str = "python") -> Document:
        d = Document(text, path, name, mode, language)
        d.highlighter = TreeSitterHighlighter(
            d.doc, self.theme.colors if self.theme else _FALLBACK_COLORS, language)
        d.doc.setDefaultFont(self.font())
        self.documents.append(d)
        return d

    def close_document(self, d: Document):
        if d in self.documents:
            self.documents.remove(d)
        if d.highlighter is not None:
            d.highlighter.setDocument(None)
            d.highlighter = None

    def set_current(self, d: Document):
        if self.current is d:
            return
        if self.current is not None:
            self.current.cursor_pos = self.textCursor().position()
            self.current.scroll = self.verticalScrollBar().value()
        self._debounce_timer.stop()
        self._hide_popup()
        self._end_snippet()
        self._closers.clear()
        self._bracket_selections = []
        self._word_selections = []
        self._error_selections = []
        self._find_selections = []
        self.current = d
        self._suppress_change_handler = True
        try:
            self.setDocument(d.doc)
            d.doc.setDefaultFont(self.font())
            self.setTabStopDistance(self.tab_width * QFontMetrics(self.font()).horizontalAdvance(" "))
        finally:
            self._suppress_change_handler = False
        cur = self.textCursor()
        cur.setPosition(min(d.cursor_pos, max(0, d.doc.characterCount() - 1)))
        self.setTextCursor(cur)
        self.verticalScrollBar().setValue(d.scroll)
        self._update_line_number_area_width()
        self._build_error_selections(d.errors)
        self._update_current_line_selection()
        self.documentSwitched.emit(d)
        self.languageDetected.emit(d.language)
        self._run_live_analysis()

    # ---- compatibility surface used by the main window ---------------------
    @property
    def file_path(self) -> str:
        return self.current.name if self.current else "Untitled"

    @file_path.setter
    def file_path(self, v: str):
        if self.current:
            self.current.name = v

    @property
    def language(self) -> str:        # the *mode*: "auto" or pinned
        return self.current.mode if self.current else "auto"

    @property
    def active_language(self) -> str:
        return self.current.language if self.current else "python"

    @property
    def current_errors(self) -> list[dict]:
        return self.current.errors if self.current else []

    def setPlainText(self, text: str):   # noqa: N802 (Qt-style name kept for callers)
        """Replace the whole buffer as ONE undoable edit (so a fix/convert can
        be reverted with Ctrl+Z), keeping the caret near where it was."""
        cur = self.textCursor()
        pos = cur.position()
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(text)
        cur.endEditBlock()
        cur = self.textCursor()
        cur.setPosition(min(pos, max(0, len(text))))
        self.setTextCursor(cur)

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------
    def set_theme(self, theme: Theme):
        self.theme = theme
        theme.apply_to_editor_palette(self)
        self._apply_font()
        self.setStyleSheet("QPlainTextEdit { border: none; padding: 6px 2px; }" + theme.scrollbar_css())
        self._suppress_change_handler = True
        try:
            for d in self.documents:
                if d.highlighter is not None:
                    d.highlighter.set_theme(theme.colors)
            if self.current and self.current.highlighter:
                self.current.highlighter.reparse(self.toPlainText())
        finally:
            self._suppress_change_handler = False
        self._build_error_selections(self.current_errors)
        self._update_current_line_selection()
        self._line_number_area.update()
        self._popup.retheme(design.Tokens(theme), theme.scrollbar_css(), self.font(), design.ui_font(9.5))
        self.viewport().update()

    def _apply_font(self):
        f = design.mono_font(self.font_size)
        self.setFont(f)
        for d in self.documents:
            d.doc.setDefaultFont(f)
        self.setTabStopDistance(self.tab_width * QFontMetrics(f).horizontalAdvance(" "))
        self._update_line_number_area_width()
        if self.theme:
            self._popup.retheme(design.Tokens(self.theme), self.theme.scrollbar_css(), self.font(),
                                design.ui_font(9.5))

    def apply_settings(self, font_size: float | None = None, tab_width: int | None = None,
                       word_wrap: bool | None = None, auto_close: bool | None = None,
                       suggestions: bool | None = None, indent_guides: bool | None = None):
        if auto_close is not None:
            self.auto_close = bool(auto_close)
        if suggestions is not None:
            self.suggestions = bool(suggestions)
            if not self.suggestions:
                self._hide_popup()
        if indent_guides is not None:
            self.indent_guides = bool(indent_guides)
            self.viewport().update()
        if font_size is not None:
            self.font_size = max(8.0, min(28.0, float(font_size)))
        if tab_width is not None:
            self.tab_width = max(1, min(8, int(tab_width)))
        if word_wrap is not None:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if word_wrap
                                 else QPlainTextEdit.LineWrapMode.NoWrap)
        self._apply_font()

    def zoom(self, delta: float):
        self.apply_settings(font_size=self.font_size + delta)
        self.zoomChanged.emit(int(round(self.font_size)))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    # ------------------------------------------------------------------
    # Language mode
    # ------------------------------------------------------------------
    def set_language(self, language: str):
        """'auto' hands the decision back to the server's detector; any
        concrete id pins it immediately."""
        if not self.current:
            return
        self.current.mode = language
        if language != "auto":
            self._set_active_language(language)
        self._run_live_analysis()

    def _set_active_language(self, language: str):
        d = self.current
        if d is None or language == d.language:
            return
        d.language = language
        if d.highlighter is not None:
            self._suppress_change_handler = True
            try:
                d.highlighter.set_language(language)
                d.highlighter.reparse(self.toPlainText())
            except Exception:
                import traceback
                traceback.print_exc()   # colours are optional; never block the language badge
            finally:
                self._suppress_change_handler = False
        self.languageDetected.emit(language)

    # ------------------------------------------------------------------
    # Live analysis loop
    # ------------------------------------------------------------------
    def _on_text_changed(self):
        # rehighlight() fires textChanged again; without this guard that is
        # infinite mutual recursion.
        if self._suppress_change_handler or self.current is None:
            return
        if self._snippet is not None and not self._snippet.syncing:
            self._snippet.sync_mirrors()
        self._debounce_timer.start()
        if self.current.highlighter:
            self._suppress_change_handler = True
            try:
                self.current.highlighter.reparse(self.toPlainText())
            finally:
                self._suppress_change_handler = False

    def analyze_now(self):
        self._debounce_timer.stop()
        self._run_live_analysis()

    def _run_live_analysis(self):
        d = self.current
        if d is None:
            return
        requested = None if d.mode == "auto" else d.mode
        # Requests can finish out of order (a slow earlier one landing after a
        # newer one would paint stale squiggles), so each carries a number and
        # only the newest for its document is accepted.
        seq = self._analysis_seq.get(d.id, 0) + 1
        self._analysis_seq[d.id] = seq
        worker = _AnalyzeWorker(self.api_client, d.id, seq, d.name, d.doc.toPlainText(), requested)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_analysis_failed)
        self.analysisStarted.emit()
        self._thread_pool.start(worker)

    def _on_worker_finished(self, doc_id: int, seq: int, errors: list, detected_language: str):
        d = next((x for x in self.documents if x.id == doc_id), None)
        if d is None or seq != self._analysis_seq.get(doc_id, seq):
            return      # tab closed, or a newer request superseded this one
        self._on_analysis_result(d, errors, detected_language)

    def _on_analysis_result(self, d: Document, errors: list[dict], detected_language: str):
        if d not in self.documents:
            return
        d.errors = errors
        if d.mode == "auto" and d is self.current:
            self._set_active_language(detected_language)
        elif d.mode == "auto":
            d.language = detected_language
        if d is not self.current:
            return   # a result for a tab the user has since left: stored, not painted
        self._build_error_selections(errors)
        self._apply_extra_selections()
        self._line_number_area.update()
        self.errorsChanged.emit(errors)

    def _on_analysis_failed(self, message: str):
        self.analysisFailed.emit(message)

    # ------------------------------------------------------------------
    # Cursor + navigation
    # ------------------------------------------------------------------
    def _on_cursor_position_changed(self):
        cursor = self.textCursor()
        self.cursorMoved.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)
        if self._snippet is not None and not self._snippet.contains(cursor.position()):
            self._end_snippet()
        self._update_bracket_highlight()
        self._word_selections = []
        self._word_timer.start()
        self._update_current_line_selection()
        self._line_number_area.update()

    def goto_line(self, line: int, col: int | None = None):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position() + (max(0, col - 1) if col else 0))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    # ------------------------------------------------------------------
    # Extra selections: current line + error squiggles + find matches
    # ------------------------------------------------------------------
    def _build_error_selections(self, errors: list[dict]):
        self._error_selections = []
        if not self.theme:
            return
        for err in errors:
            cursor = self._cursor_for_error(err)
            if cursor is None:
                continue
            fmt = QTextCharFormat()
            color = (self.theme.error_color() if err.get("severity") == "syntax"
                     else self.theme.warning_color())
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
            fmt.setUnderlineColor(color)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = fmt
            self._error_selections.append(selection)

    def _update_current_line_selection(self):
        self._current_line_selection = None
        if self.theme:
            fmt = QTextCharFormat()
            fmt.setBackground(self.theme.current_line_bg())
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selection.format = fmt
            self._current_line_selection = selection
        self._apply_extra_selections()

    def _apply_extra_selections(self):
        sels = []
        if self._current_line_selection is not None:
            sels.append(self._current_line_selection)
        sels.extend(self._word_selections)
        sels.extend(self._find_selections)
        sels.extend(self._bracket_selections)
        sels.extend(self._error_selections)
        self.setExtraSelections(sels)

    def _cursor_for_error(self, err: dict) -> QTextCursor | None:
        """Underline just the offending identifier when the message quotes
        one; otherwise the whole line."""
        line = err.get("line", 1) - 1
        if line < 0 or line >= self.document().blockCount():
            return None
        block = self.document().findBlockByNumber(line)
        text = block.text()
        cursor = QTextCursor(block)
        match = re.search(r"'([^']+)'", err.get("message", ""))
        if match:
            idx = text.find(match.group(1))
            if idx != -1:
                cursor.setPosition(block.position() + idx)
                cursor.setPosition(block.position() + idx + len(match.group(1)), QTextCursor.MoveMode.KeepAnchor)
                return cursor
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + len(text), QTextCursor.MoveMode.KeepAnchor)
        return cursor

    # ------------------------------------------------------------------
    # Find / replace
    # ------------------------------------------------------------------
    def _find_flags(self, case: bool):
        return QTextDocument.FindFlag.FindCaseSensitively if case else QTextDocument.FindFlag(0)

    def _iter_matches(self, text: str, case: bool, regex: bool):
        doc = self.document()
        if not text:
            return
        pos = 0
        while True:
            if regex:
                rx = QRegularExpression(text)
                if not case:
                    rx.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
                if not rx.isValid():
                    return
                c = doc.find(rx, pos, self._find_flags(case))
            else:
                c = doc.find(text, pos, self._find_flags(case))
            if c.isNull():
                return
            yield c
            pos = c.selectionEnd() if c.selectionEnd() > c.selectionStart() else c.selectionEnd() + 1
            if pos >= doc.characterCount():
                return

    def find_all(self, text: str, case: bool = False, regex: bool = False) -> int:
        """Highlight every match; returns the count (capped for huge files)."""
        self._find_selections = []
        n = 0
        if self.theme and text:
            bg = QColor(self.theme.accent())
            bg.setAlpha(70)
            for c in self._iter_matches(text, case, regex):
                fmt = QTextCharFormat()
                fmt.setBackground(bg)
                s = QTextEdit.ExtraSelection()
                s.cursor, s.format = c, fmt
                self._find_selections.append(s)
                n += 1
                if n >= 5000:
                    break
        self._apply_extra_selections()
        return n

    def clear_find(self):
        self._find_selections = []
        self._apply_extra_selections()

    def find_step(self, text: str, case: bool, regex: bool, backwards: bool = False) -> bool:
        if not text:
            return False
        flags = self._find_flags(case)
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        target = QRegularExpression(text) if regex else text
        if regex and not case:
            target.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        if regex and not target.isValid():
            return False
        found = self.document().find(target, self.textCursor(), flags)
        if found.isNull():   # wrap around
            start = QTextCursor(self.document())
            if backwards:
                start.movePosition(QTextCursor.MoveOperation.End)
            found = self.document().find(target, start, flags)
        if found.isNull():
            return False
        self.setTextCursor(found)
        self.centerCursor()
        return True

    def replace_current(self, text: str, repl: str, case: bool, regex: bool) -> bool:
        cur = self.textCursor()
        sel = cur.selectedText()
        ok = (sel == text) if (case and not regex) else (
            sel.lower() == text.lower() if not regex else bool(re.fullmatch(text, sel, 0 if case else re.I)))
        if ok:
            cur.insertText(re.sub(text, repl, sel, count=1, flags=0 if case else re.I) if regex else repl)
        return self.find_step(text, case, regex)

    def replace_all(self, text: str, repl: str, case: bool, regex: bool) -> int:
        matches = list(self._iter_matches(text, case, regex))
        if not matches:
            return 0
        cur = self.textCursor()
        cur.beginEditBlock()
        for c in reversed(matches):
            piece = c.selectedText()
            c.insertText(re.sub(text, repl, piece, count=1, flags=0 if case else re.I) if regex else repl)
        cur.endEditBlock()
        return len(matches)

    # ------------------------------------------------------------------
    # Editing helpers
    # ------------------------------------------------------------------
    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        K = Qt.Key

        # --- suggestion popup owns a few keys while it is open ----------------
        if self._popup.isVisible():
            if key in (K.Key_Down, K.Key_Up) and not ctrl and not alt:
                self._popup.move(1 if key == K.Key_Down else -1)
                self._popup_navigated = True
                return
            if key in (K.Key_PageDown, K.Key_PageUp):
                self._popup.move(5 if key == K.Key_PageDown else -5)
                self._popup_navigated = True
                return
            if key == K.Key_Escape:
                self._hide_popup()
                return
            if key == K.Key_Tab and not ctrl and not shift:
                if self._accept_completion():
                    return
            if key in (K.Key_Return, K.Key_Enter) and not ctrl and not alt and not shift:
                # Enter only accepts when it would not just re-type the word
                # you already finished (so `pass`+Enter is a plain newline).
                c = self._popup.current_completion()
                exact = c is not None and c.label == self._popup.prefix and c.kind != "snippet"
                if (self._popup_navigated or not exact) and self._accept_completion():
                    return
                self._hide_popup()
            if key in (K.Key_Left, K.Key_Right, K.Key_Home, K.Key_End):
                self._hide_popup()

        # --- snippet tab stops --------------------------------------------------
        if self._snippet is not None:
            if key == K.Key_Tab and not ctrl and not shift:
                if not self._snippet.advance(1):
                    self._end_snippet()
                return
            if key == K.Key_Backtab:
                self._snippet.advance(-1)
                return
            if key == K.Key_Escape:
                self._end_snippet()
                return

        if ctrl and not shift and not alt and key == K.Key_Space:
            self.show_suggestions(manual=True)
            return
        if e.matches(QKeySequence.StandardKey.Copy) and not self.textCursor().hasSelection():
            self.copy_line()
            return
        if e.matches(QKeySequence.StandardKey.Cut) and not self.textCursor().hasSelection():
            self.cut_line()
            return
        if key in (K.Key_Return, K.Key_Enter) and not alt:
            if ctrl and shift:
                self.insert_line(above=True)
                return
            if shift and not ctrl:
                self.insert_line(above=False)
                return
            if not ctrl:
                self._smart_newline()
                self._hide_popup()
                return
        if key == K.Key_Tab and not ctrl:
            self._indent(+1)
            return
        if key == K.Key_Backtab:
            self._indent(-1)
            return
        if ctrl and key == K.Key_Slash:
            self.toggle_comment()
            return
        if ctrl and key == K.Key_BracketRight:
            self._indent(+1, force_lines=True)
            return
        if ctrl and key == K.Key_BracketLeft:
            self._indent(-1)
            return
        if ctrl and shift and key == K.Key_D:
            self.duplicate_line()
            return
        if ctrl and shift and key == K.Key_K:
            self.delete_line()
            return
        if ctrl and not shift and key == K.Key_L:
            self.select_line()
            return
        if ctrl and not shift and key == K.Key_D:
            self.select_next_occurrence()
            return
        if ctrl and shift and key == K.Key_Backslash:
            self.goto_matching_bracket()
            return
        if alt and key in (K.Key_Up, K.Key_Down):
            self.move_line(-1 if key == K.Key_Up else 1)
            return
        if ctrl and key in (K.Key_Plus, K.Key_Equal):
            self.zoom(1)
            return
        if ctrl and key == K.Key_Minus:
            self.zoom(-1)
            return
        if ctrl and key == K.Key_0:
            self.apply_settings(font_size=11)
            self.zoomChanged.emit(11)
            return
        if key == K.Key_Home and not ctrl and not alt:
            self._smart_home(shift)
            return
        if key == K.Key_Backspace and not self.textCursor().hasSelection() and not ctrl:
            if self._smart_backspace():
                self._after_edit_key()
                return

        # --- typed characters: auto-close / overtype / electric dedent ---------
        text = e.text()
        if (len(text) == 1 and text.isprintable() and (ctrl == alt)):
            if self._handle_typed_char(text):
                self._after_edit_key(text)
                return
            super().keyPressEvent(e)
            self._after_edit_key(text)
            return

        super().keyPressEvent(e)
        if key in (K.Key_Backspace, K.Key_Delete):
            self._after_edit_key()

    # ------------------------------------------------------------------
    # Typing helpers: bracket / quote pairing, overtype, electric dedent
    # ------------------------------------------------------------------
    _OPEN = {"(": ")", "[": "]", "{": "}"}
    _CLOSERS = ")]}"
    _QUOTES = "\"'"

    def _unit(self) -> str:
        return " " * self.tab_width

    def _text_before_caret(self, limit: int = 20000) -> str:
        cur = self.textCursor()
        c = QTextCursor(self.document())
        c.setPosition(max(0, cur.position() - limit))
        c.setPosition(cur.position(), QTextCursor.MoveMode.KeepAnchor)
        return c.selectedText().replace("\u2029", "\n")

    def _track_closer(self, pos: int):
        c = QTextCursor(self.document())
        c.setPosition(pos)
        self._closers.append(c)
        if len(self._closers) > 64:
            del self._closers[:16]

    def _consume_tracked_closer(self, pos: int, ch: str) -> bool:
        doc = self.document()
        for i, c in enumerate(self._closers):
            if c.position() == pos and doc.characterAt(pos) == ch:
                del self._closers[i]
                return True
        return False

    def _handle_typed_char(self, ch: str) -> bool:
        """Return True when the keystroke was fully handled here."""
        cur = self.textCursor()
        lang = self.active_language
        has_sel = cur.hasSelection()

        # Surround the selection:  "x" -> (x)  /  "x"
        if has_sel and self.auto_close and (ch in self._OPEN or ch in self._QUOTES):
            sel = cur.selectedText()
            closer = self._OPEN.get(ch, ch)
            cur.beginEditBlock()
            cur.insertText(ch + sel + closer)
            end = cur.position()
            cur.setPosition(end - len(closer) - len(sel))
            cur.setPosition(end - len(closer), QTextCursor.MoveMode.KeepAnchor)
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True
        if has_sel:
            return False

        pos = cur.position()
        text = cur.block().text()
        col = cur.positionInBlock()
        before, after = text[:col], text[col:]
        nxt, prev = after[:1], before[-1:]

        # Overtype a closer that was auto-inserted (or an obvious closing quote).
        if (ch in self._CLOSERS or ch == ">") and nxt == ch and self._consume_tracked_closer(pos, ch):
            cur.movePosition(QTextCursor.MoveOperation.Right)
            self.setTextCursor(cur)
            return True
        if ch in self._QUOTES and nxt == ch:
            tb = self._text_before_caret()
            triple = lang == "python" and tb.count(ch * 3) % 2 == 1
            if triple or (line_state(before, lang) == ("str", ch)):
                cur.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cur)
                return True

        # Electric dedent: `}` on a whitespace-only line lines up with its `{`.
        if ch == "}" and lang != "python" and before and not before.strip():
            self._dedent_closing_brace(cur, before)
        # Python: `else:` / `elif x:` / `except:` / `finally:` step back out.
        if ch == ":" and lang == "python":
            self._python_electric_dedent(cur, before, after)
            return False

        if not self.auto_close:
            return False

        if ch in self._OPEN:
            tb = self._text_before_caret()
            if in_literal(before, tb, lang):
                return False
            if not (nxt == "" or nxt.isspace() or nxt in ")]},;:.>"):
                return False
            return self._insert_pair(cur, ch, self._OPEN[ch])

        if ch == "<" and lang == "c" and re.match(r"^\s*#\s*include\s*$", before):
            return self._insert_pair(cur, "<", ">")

        if ch in self._QUOTES:
            tb = self._text_before_caret()
            if in_literal(before, tb, lang):
                return False
            if lang == "python" and before.endswith(ch * 2) and not before.endswith(ch * 3) and nxt != ch:
                # `""` + `"`  ->  `"""|"""`
                cur.insertText(ch + ch * 3)
                cur.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 3)
                self.setTextCursor(cur)
                return True
            if prev and (prev.isalnum() or prev == "_"):
                is_prefix = lang == "python" and re.search(r"(?<!\w)(?:[rRbBfFuU]|[rR][bB]|[bB][rR]|[fF][rR]|[rR][fF])$", before)
                if not is_prefix:
                    return False
            if nxt and (nxt.isalnum() or nxt == "_"):
                return False
            return self._insert_pair(cur, ch, ch)
        return False

    def _insert_pair(self, cur: QTextCursor, opener: str, closer: str) -> bool:
        cur.beginEditBlock()
        cur.insertText(opener + closer)
        cur.movePosition(QTextCursor.MoveOperation.Left)
        cur.endEditBlock()
        self.setTextCursor(cur)
        self._track_closer(cur.position())
        return True

    def _dedent_closing_brace(self, cur: QTextCursor, before: str):
        tb = self._text_before_caret(50000)
        depth, target = 0, None
        for i in range(len(tb) - 1, -1, -1):
            c = tb[i]
            if c == "}":
                depth += 1
            elif c == "{":
                if depth == 0:
                    ls = tb.rfind("\n", 0, i) + 1
                    target = re.match(r"[ \t]*", tb[ls:]).group(0)
                    break
                depth -= 1
        if target is None:
            unit = self._unit()
            target = before[:-len(unit)] if before.endswith(unit) else before[:-1]
        if target == before:
            return
        cur.beginEditBlock()
        cur.setPosition(cur.block().position())
        cur.setPosition(cur.block().position() + len(before), QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(target)
        cur.endEditBlock()
        self.setTextCursor(cur)

    _PY_CONTINUATION = re.compile(r"^(else|elif\b.*|except\b.*|finally)$")

    def _python_electric_dedent(self, cur: QTextCursor, before: str, after: str):
        if after.strip() or not self._PY_CONTINUATION.match(before.strip()):
            return
        indent = re.match(r"[ \t]*", before).group(0)
        if not indent:
            return
        blk = cur.block().previous()
        while blk.isValid():
            t = blk.text()
            if t.strip():
                ind = re.match(r"[ \t]*", t).group(0)
                if len(ind) < len(indent):
                    if ind != indent:
                        cur.beginEditBlock()
                        c = QTextCursor(cur.block())
                        c.setPosition(cur.block().position() + len(indent), QTextCursor.MoveMode.KeepAnchor)
                        c.insertText(ind)
                        cur.endEditBlock()
                    return
            blk = blk.previous()

    # ------------------------------------------------------------------
    # Newline / backspace / indent
    # ------------------------------------------------------------------
    def _smart_newline(self):
        cur = self.textCursor()
        if cur.hasSelection():
            cur.removeSelectedText()
        block_text = cur.block().text()
        col = cur.positionInBlock()
        before, after = block_text[:col], block_text[col:]
        indent = re.match(r"[ \t]*", block_text).group(0)
        if col < len(indent):
            indent = indent[:col]
        unit = self._unit()
        stripped = before.rstrip()
        ls = before.lstrip()
        lang = self.active_language
        pair = {"{": "}", "(": ")", "[": "]"}

        # `{|}`  ->  open a block with the closer on its own line
        if before[-1:] in pair and after[:1] == pair[before[-1:]]:
            cur.beginEditBlock()
            cur.insertText("\n" + indent + unit + "\n" + indent)
            cur.movePosition(QTextCursor.MoveOperation.Up)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cur.endEditBlock()
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            return

        extra, prefix, closing = "", "", ""
        if lang == "python":
            if not ls.startswith("#"):
                if stripped.endswith((":", "(", "[", "{")):
                    extra = unit
                elif (not after.strip() and re.match(r"^(return|raise|break|continue|pass)\b", ls)
                      and (indent.endswith(unit) or indent.endswith("\t"))):
                    indent = indent[:-len(unit)] if indent.endswith(unit) else indent[:-1]
        else:
            if ls.startswith("/*") and "*/" not in ls:
                prefix = " * "
                if not after.strip():
                    closing = "\n" + indent + " */"
            elif ls.startswith("*") and not ls.startswith("*/"):
                prefix = "* "
            elif stripped.endswith(("{", "(")):
                extra = unit
            elif re.match(r"^(case\b|default\b)", ls) and stripped.endswith(":"):
                extra = unit
            elif ((re.match(r"^(if|for|while)\b", ls) and stripped.endswith(")")
                   and stripped.count("(") == stripped.count(")"))
                  or ls.rstrip() == "else"):
                extra = unit

        cur.beginEditBlock()
        cur.insertText("\n" + indent + extra + prefix)
        if closing:
            pos = cur.position()
            cur.insertText(closing)
            cur.setPosition(pos)
        cur.endEditBlock()
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def insert_line(self, above: bool = False):
        cur = self.textCursor()
        cur.clearSelection()
        if above:
            cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            indent = re.match(r"[ \t]*", cur.block().text()).group(0)
            cur.beginEditBlock()
            cur.insertText(indent + "\n")
            cur.movePosition(QTextCursor.MoveOperation.Left)
            cur.endEditBlock()
            self.setTextCursor(cur)
        else:
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self.setTextCursor(cur)
            self._smart_newline()
        self.ensureCursorVisible()

    def _smart_home(self, keep: bool):
        cur = self.textCursor()
        text = cur.block().text()
        first = len(text) - len(text.lstrip())
        target = cur.block().position() + (first if cur.positionInBlock() != first else 0)
        cur.setPosition(target, QTextCursor.MoveMode.KeepAnchor if keep else QTextCursor.MoveMode.MoveAnchor)
        self.setTextCursor(cur)

    def _smart_backspace(self) -> bool:
        """Backspace over an empty pair removes both; over a run of indent
        spaces removes one indent level."""
        cur = self.textCursor()
        text = cur.block().text()
        col = cur.positionInBlock()
        before = text[:col]
        pair = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
        if self.auto_close and before and text[col:col + 1] and pair.get(before[-1]) == text[col]:
            cur.beginEditBlock()
            cur.deletePreviousChar()
            cur.deleteChar()
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True
        if before and before.strip() == "" and "\t" not in before:
            n = len(before) % self.tab_width or self.tab_width
            n = min(n, len(before))
            cur.setPosition(cur.position() - n, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            return True
        return False

    def _selected_blocks(self) -> tuple[int, int]:
        cur = self.textCursor()
        a, b = cur.selectionStart(), cur.selectionEnd()
        doc = self.document()
        first = doc.findBlock(a).blockNumber()
        last_block = doc.findBlock(b)
        last = last_block.blockNumber()
        if b > a and last_block.position() == b:   # selection ends at column 0 of a line
            last -= 1
        return first, max(first, last)

    def _indent(self, direction: int, force_lines: bool = False):
        cur = self.textCursor()
        if direction > 0 and not cur.hasSelection() and not force_lines:
            n = self.tab_width - (cur.positionInBlock() % self.tab_width)
            cur.insertText(" " * n)
            return
        first, last = self._selected_blocks()
        cur.beginEditBlock()
        for n in range(first, last + 1):
            blk = self.document().findBlockByNumber(n)
            c = QTextCursor(blk)
            if direction > 0:
                c.insertText(self._unit())
            else:
                text = blk.text()
                strip = min(len(text) - len(text.lstrip(" ")), self.tab_width)
                if text.startswith("\t"):
                    strip = 1
                if strip:
                    c.setPosition(blk.position() + strip, QTextCursor.MoveMode.KeepAnchor)
                    c.removeSelectedText()
        cur.endEditBlock()

    def toggle_comment(self):
        prefix = _COMMENT_PREFIX.get(self.active_language, "# ")
        bare = prefix.strip()
        first, last = self._selected_blocks()
        blocks = [self.document().findBlockByNumber(n) for n in range(first, last + 1)]
        non_empty = [b for b in blocks if b.text().strip()]
        all_commented = bool(non_empty) and all(b.text().lstrip().startswith(bare) for b in non_empty)
        cur = self.textCursor()
        cur.beginEditBlock()
        for b in blocks:
            text = b.text()
            if not text.strip():
                continue
            ind = len(text) - len(text.lstrip())
            c = QTextCursor(b)
            c.setPosition(b.position() + ind)
            if all_commented:
                rest = text[ind:]
                n = len(prefix) if rest.startswith(prefix) else len(bare)
                c.setPosition(b.position() + ind + n, QTextCursor.MoveMode.KeepAnchor)
                c.removeSelectedText()
            else:
                c.insertText(prefix)
        cur.endEditBlock()

    def duplicate_line(self):
        first, last = self._selected_blocks()
        doc = self.document()
        text = "\n".join(doc.findBlockByNumber(n).text() for n in range(first, last + 1))
        c = QTextCursor(doc.findBlockByNumber(last))
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        c.insertText("\n" + text)
        self.setTextCursor(c)

    def move_line(self, direction: int):
        first, last = self._selected_blocks()
        doc = self.document()
        if direction < 0 and first == 0:
            return
        if direction > 0 and last >= doc.blockCount() - 1:
            return
        cur = self.textCursor()
        cur.beginEditBlock()
        lines = [doc.findBlockByNumber(n).text() for n in range(first, last + 1)]
        other_n = first - 1 if direction < 0 else last + 1
        other = doc.findBlockByNumber(other_n).text()
        lo, hi = (other_n, last) if direction < 0 else (first, other_n)
        new_lines = (lines + [other]) if direction < 0 else ([other] + lines)
        c = QTextCursor(doc.findBlockByNumber(lo))
        c.setPosition(doc.findBlockByNumber(hi).position() + doc.findBlockByNumber(hi).length() - 1,
                      QTextCursor.MoveMode.KeepAnchor)
        c.insertText("\n".join(new_lines))
        cur.endEditBlock()
        ns = first + direction
        c = QTextCursor(doc.findBlockByNumber(ns))
        c.setPosition(doc.findBlockByNumber(ns + len(lines) - 1).position()
                      + len(doc.findBlockByNumber(ns + len(lines) - 1).text()), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)

    # ------------------------------------------------------------------
    # Suggestions & snippets
    # ------------------------------------------------------------------
    def _after_edit_key(self, typed: str = ""):
        """Called after every edit keystroke: decide whether to (re)open or
        close the suggestion popup."""
        if not self.suggestions:
            return
        if not typed:                       # backspace / delete: refresh only if already open
            if self._popup.isVisible():
                self.show_suggestions()
            return
        if typed.isalnum() or typed in "_.#<\"/":
            self.show_suggestions()
        elif typed == " ":
            cur = self.textCursor()
            before = cur.block().text()[:cur.positionInBlock()]
            if self.active_language == "c" and re.match(r"^\s*#\s*include\s+$", before):
                self.show_suggestions()
            elif self.active_language in ("python", "java") and re.match(r"^\s*(import|from)\s+$", before):
                self.show_suggestions()
            else:
                self._hide_popup()
        else:
            self._hide_popup()

    def show_suggestions(self, manual: bool = False):
        """Open (or refresh) the popup. ``manual`` is Ctrl+Space: show even with
        nothing typed yet."""
        if not self.suggestions and not manual:
            return
        cur = self.textCursor()
        if cur.hasSelection():
            self._hide_popup()
            return
        before = cur.block().text()[:cur.positionInBlock()]
        res = query(self.active_language, before, self._text_before_caret(), self.toPlainText(), manual=manual)
        if res is None:
            self._hide_popup()
            return
        ctx, items = res
        start = cur.block().position() + ctx.start
        if not self._popup.isVisible() or start != self._cmp_start:
            self._popup_navigated = False
        self._cmp_ctx, self._cmp_start = ctx, start
        self._popup.set_items(items, ctx.prefix)
        a = QTextCursor(self.document())
        a.setPosition(start)
        self._popup.place(self.cursorRect(a))

    def _hide_popup(self):
        if hasattr(self, "_popup") and self._popup.isVisible():
            self._popup.hide()
        self._cmp_ctx = None
        self._popup_navigated = False

    def _accept_completion(self, c=None) -> bool:
        c = c or self._popup.current_completion()
        ctx = self._cmp_ctx
        if c is None or ctx is None:
            self._hide_popup()
            return False
        start = self._cmp_start
        cur = self.textCursor()
        end = cur.position()
        self._hide_popup()
        if end < start:
            return False
        lang = self.active_language
        line = cur.block().text()
        after_line = line[cur.positionInBlock():]
        body, closer = c.body, ""
        if ctx.kind == "include":
            if ctx.extra:
                body, closer = c.label, (">" if ctx.extra == "<" else '"')
            else:
                body = f"<{c.label}>"
        elif ctx.kind == "import":
            body = c.label + (";" if lang == "java" and not after_line.startswith(";") else "")
        elif c.kind in ("func", "member") and after_line.startswith("("):
            body = c.label
        indent = re.match(r"[ \t]*", line).group(0)
        text, stops = parse_snippet(body, self._unit(), indent)

        cur.beginEditBlock()
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(text)
        if closer:
            if after_line[:1] == closer:
                cur.setPosition(cur.position() + 1)
            else:
                cur.insertText(closer)
        cur.endEditBlock()
        self.setTextCursor(cur)

        if c.kind in ("func", "member") and body != c.label:
            i = text.rfind(")")
            if i >= 0:
                self._track_closer(start + i)      # typing `)` steps over it
        if stops:
            self._snippet = SnippetSession(self, start, text, stops)
            if not self._snippet.start():
                self._end_snippet()
        return True

    def _end_snippet(self):
        self._snippet = None

    def focusOutEvent(self, e):
        self._hide_popup()
        super().focusOutEvent(e)

    # ------------------------------------------------------------------
    # Bracket matching + occurrence highlights
    # ------------------------------------------------------------------
    def _find_bracket_pair(self) -> tuple[int, int] | None:
        pos = self.textCursor().position()
        doc = self.document()
        n = 20000
        lo = max(0, pos - n)
        hi = min(doc.characterCount() - 1, pos + n)
        c = QTextCursor(doc)
        c.setPosition(lo)
        c.setPosition(hi, QTextCursor.MoveMode.KeepAnchor)
        win = c.selectedText()
        rel = pos - lo
        pairs = {"(": ")", "[": "]", "{": "}"}
        rev = {v: k for k, v in pairs.items()}
        for off in (-1, 0):
            i = rel + off
            if not 0 <= i < len(win):
                continue
            ch = win[i]
            if ch in pairs:
                depth = 0
                for j in range(i + 1, len(win)):
                    if win[j] == ch:
                        depth += 1
                    elif win[j] == pairs[ch]:
                        if depth == 0:
                            return lo + i, lo + j
                        depth -= 1
            elif ch in rev:
                depth = 0
                for j in range(i - 1, -1, -1):
                    if win[j] == ch:
                        depth += 1
                    elif win[j] == rev[ch]:
                        if depth == 0:
                            return lo + j, lo + i
                        depth -= 1
        return None

    def _update_bracket_highlight(self):
        self._bracket_selections = []
        if not self.theme or self.textCursor().hasSelection():
            return
        pair = self._find_bracket_pair()
        if not pair:
            return
        bg = QColor(self.theme.accent())
        bg.setAlpha(80)
        for p in pair:
            fmt = QTextCharFormat()
            fmt.setBackground(bg)
            s = QTextEdit.ExtraSelection()
            s.cursor = QTextCursor(self.document())
            s.cursor.setPosition(p)
            s.cursor.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
            s.format = fmt
            self._bracket_selections.append(s)

    def goto_matching_bracket(self):
        pair = self._find_bracket_pair()
        if not pair:
            return
        pos = self.textCursor().position()
        a, b = pair
        # we are next to one end; jump to the other
        near_a = pos in (a, a + 1)
        target = (b + 1) if near_a else a
        c = self.textCursor()
        c.setPosition(target)
        self.setTextCursor(c)
        self.ensureCursorVisible()

    _WORD_RE = re.compile(r"[A-Za-z_]\w{1,59}")

    def _update_word_highlights(self):
        self._word_selections = []
        if self.theme and self.current is not None:
            cur = self.textCursor()
            if cur.hasSelection():
                word = cur.selectedText()
            else:
                w = QTextCursor(cur)
                w.select(QTextCursor.SelectionType.WordUnderCursor)
                word = w.selectedText()
            if self._WORD_RE.fullmatch(word or ""):
                text = self.toPlainText()[:300_000]
                hits = [m for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", text)]
                if 1 < len(hits) <= 300:
                    bg = QColor(self.theme.foreground())
                    bg.setAlpha(30)
                    for m in hits:
                        fmt = QTextCharFormat()
                        fmt.setBackground(bg)
                        s = QTextEdit.ExtraSelection()
                        s.cursor = QTextCursor(self.document())
                        s.cursor.setPosition(m.start())
                        s.cursor.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
                        s.format = fmt
                        self._word_selections.append(s)
        self._apply_extra_selections()

    # ------------------------------------------------------------------
    # Line operations
    # ------------------------------------------------------------------
    def copy_line(self):
        QGuiApplication.clipboard().setText(self.textCursor().block().text() + "\n")

    def cut_line(self):
        self.copy_line()
        self.delete_line()

    def delete_line(self):
        first, last = self._selected_blocks()
        doc = self.document()
        sb, eb = doc.findBlockByNumber(first), doc.findBlockByNumber(last)
        if eb.next().isValid():
            a, b = sb.position(), eb.next().position()
        elif sb.previous().isValid():
            a, b = sb.previous().position() + sb.previous().length() - 1, eb.position() + eb.length() - 1
        else:
            a, b = 0, eb.position() + eb.length() - 1
        c = self.textCursor()
        c.beginEditBlock()
        c.setPosition(a)
        c.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()
        c.endEditBlock()
        self.setTextCursor(c)

    def select_line(self):
        first, last = self._selected_blocks()
        doc = self.document()
        cur = self.textCursor()
        sb, eb = doc.findBlockByNumber(first), doc.findBlockByNumber(last)
        end = eb.next().position() if eb.next().isValid() else eb.position() + eb.length() - 1
        if cur.selectionStart() == sb.position() and cur.selectionEnd() == end and eb.next().isValid():
            nb = eb.next()
            end = nb.next().position() if nb.next().isValid() else nb.position() + nb.length() - 1
        c = QTextCursor(doc)
        c.setPosition(sb.position())
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)

    def select_next_occurrence(self):
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.SelectionType.WordUnderCursor)
            if cur.hasSelection():
                self.setTextCursor(cur)
            return
        needle = cur.selectedText()
        flags = QTextDocument.FindFlag.FindCaseSensitively
        found = self.document().find(needle, cur.selectionEnd(), flags)
        if found.isNull():
            found = self.document().find(needle, 0, flags)
        if not found.isNull():
            self.setTextCursor(found)
            self.ensureCursorVisible()

    def tidy_document(self, d: Document) -> bool:
        """Trim trailing whitespace and make sure the file ends with a newline.
        One undoable edit. Returns True if anything changed."""
        doc = d.doc
        c = QTextCursor(doc)
        c.beginEditBlock()
        changed = False
        blk = doc.begin()
        while blk.isValid():
            t = blk.text()
            kept = len(t.rstrip(" \t"))
            if kept != len(t):
                cc = QTextCursor(blk)
                cc.setPosition(blk.position() + kept)
                cc.setPosition(blk.position() + len(t), QTextCursor.MoveMode.KeepAnchor)
                cc.removeSelectedText()
                changed = True
            blk = blk.next()
        if doc.lastBlock().text() != "":
            c.movePosition(QTextCursor.MoveOperation.End)
            c.insertText("\n")
            changed = True
        c.endEditBlock()
        return changed

    # ------------------------------------------------------------------
    # Indent guides
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.indent_guides and self.theme is not None:
            self._paint_indent_guides()

    def _paint_indent_guides(self):
        adv = self.fontMetrics().horizontalAdvance(" ")
        tw = self.tab_width
        if adv <= 0 or tw <= 0:
            return
        off = self.contentOffset()
        x0 = off.x() + self.document().documentMargin()
        limit = self.viewport().height()
        rows: list[list] = []
        block = self.firstVisibleBlock()
        while block.isValid():
            g = self.blockBoundingGeometry(block).translated(off)
            if g.top() > limit:
                break
            t = block.text()
            cols = None
            if t.strip():
                cols = 0
                for ch in t:
                    if ch == " ":
                        cols += 1
                    elif ch == "\t":
                        cols += tw - cols % tw
                    else:
                        break
            rows.append([g.top(), g.bottom(), cols])
            block = block.next()
        if not rows:
            return
        nxt = None
        later: list = [None] * len(rows)
        for i in range(len(rows) - 1, -1, -1):
            later[i] = nxt
            if rows[i][2] is not None:
                nxt = rows[i][2]
        prev = None
        for i, r in enumerate(rows):
            if r[2] is not None:
                prev = r[2]
            else:
                cand = [x for x in (prev, later[i]) if x is not None]
                r[2] = min(cand) if cand else 0
        col = QColor(self.theme.foreground())
        col.setAlpha(34)
        p = QPainter(self.viewport())
        p.setPen(col)
        for top, bottom, ind in rows:
            for k in range(0, (ind - 1) // tw + 1 if ind else 0):
                x = int(x0 + k * tw * adv)
                p.drawLine(x, int(top), x, int(bottom))
        p.end()

    # ------------------------------------------------------------------
    # Click on an error line -> offer a fix (deliberately not tied to
    # cursorPositionChanged, which would spam model calls on arrow keys).
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        self._hide_popup()
        super().mousePressEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        line = self.cursorForPosition(event.pos()).blockNumber() + 1
        for err in self.current_errors:
            if err.get("line") == line:
                self.errorClicked.emit(err)
                break

    # ------------------------------------------------------------------
    # Line number gutter
    # ------------------------------------------------------------------
    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 34 + self.fontMetrics().horizontalAdvance("9") * digits

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def _update_line_number_area_width(self):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    def paint_line_numbers(self, event):
        painter = QPainter(self._line_number_area)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = self.theme.window_bg() if self.theme else QColor("#1e1e24")
        painter.fillRect(event.rect(), bg)

        dim = QColor(self.theme.colors.get("ai-ghost-text", "#6b7280")) if self.theme else QColor("#6b7280")
        lit = QColor(self.theme.accent()) if self.theme else QColor("#7ee8c0")
        err_line = {e.get("line"): e for e in self.current_errors}
        current = self.textCursor().blockNumber()
        w = self._line_number_area.width()

        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        fh = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(lit if n == current else dim)
                painter.drawText(0, int(top), w - 10, fh, Qt.AlignmentFlag.AlignRight, str(n + 1))
                e = err_line.get(n + 1)
                if e is not None and self.theme:
                    col = self.theme.error_color() if e.get("severity") == "syntax" else self.theme.warning_color()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(col)
                    r = 5
                    painter.drawEllipse(8, int(top + fh / 2 - r), r * 2, r * 2)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            n += 1


_FALLBACK_COLORS = {
    "keyword": "#c9a0e8", "string": "#e3a35e", "number": "#b7d49a", "comment": "#5f6472",
    "function": "#e8d27a", "class": "#6fd0c4", "variable": "#8fc6e8",
}
