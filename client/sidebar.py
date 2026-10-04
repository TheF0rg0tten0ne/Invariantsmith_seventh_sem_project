"""Activity rail + sidebar.

Rail icons switch the sidebar page; clicking the active icon collapses the
sidebar (VS Code behaviour). Pages:

  explorer  folder tree + OUTLINE + TIMELINE sections
  search    find text across the open folder
  history   everything the AI has done (fixes, conversions) and how it ended
  run       Run / Debug / Stop and where input comes from
  convert   translate the open file to another language
"""
import os
import re

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, QTimer, QSize
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QButtonGroup,
                               QSizePolicy)

from . import icons
from . import languages as client_languages
from .widgets import CollapsibleSection, IconButton

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode", ".mypy_cache",
                ".pytest_cache", "dist", "build", ".tox"}
MAX_SEARCH_FILES = 3000
MAX_SEARCH_BYTES = 1_000_000
MAX_RESULTS = 400

PAGES = (  # key, icon, tooltip
    ("explorer", "files", "Explorer (Ctrl+Shift+E)"),
    ("search", "search", "Search in folder (Ctrl+Shift+F)"),
    ("history", "clock", "AI history"),
    ("run", "play", "Run"),
    ("convert", "swap", "Convert language"),
)


class ActivityBar(QWidget):
    pageSelected = Signal(str)       # a rail icon was chosen
    toggleCollapse = Signal()        # the already-active icon was clicked again
    terminalClicked = Signal()
    settingsClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("activityBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(52)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(False)
        self.buttons: dict[str, IconButton] = {}
        self._active: str | None = None
        for key, ic, tip in PAGES:
            b = IconButton(ic, tip, 52, 22, "muted", "activityBtn", checkable=True)
            b.setFixedHeight(46)
            b.clicked.connect(lambda _=False, k=key: self._clicked(k))
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch()
        self.term_btn = IconButton("terminal", "Toggle panel (Ctrl+J)", 52, 22, "muted", "activityBtn")
        self.term_btn.setFixedHeight(46)
        self.term_btn.clicked.connect(self.terminalClicked)
        self.settings_btn = IconButton("settings", "Settings (Ctrl+,)", 52, 22, "muted", "activityBtn")
        self.settings_btn.setFixedHeight(46)
        self.settings_btn.clicked.connect(self.settingsClicked)
        lay.addWidget(self.term_btn)
        lay.addWidget(self.settings_btn)

    def set_active(self, key: str | None):
        self._active = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)

    def _clicked(self, key: str):
        if key == self._active:
            self.toggleCollapse.emit()
            self.set_active(self._active)   # re-assert checked state after Qt toggles it
        else:
            self.pageSelected.emit(key)

    def retheme(self, t):
        for b in list(self.buttons.values()) + [self.term_btn, self.settings_btn]:
            b.retheme(t)
        # active tint
        for k, b in self.buttons.items():
            pass


# ---------------------------------------------------------------------------
# Background folder search
# ---------------------------------------------------------------------------
class _SearchSignals(QObject):
    finished = Signal(int, list, bool)   # (search id, results, truncated)


class _SearchWorker(QRunnable):
    def __init__(self, search_id: int, root: str, text: str, case: bool):
        super().__init__()
        self.search_id = search_id
        self.root, self.text, self.case = root, text, case
        self.signals = _SearchSignals()
        self.cancelled = False

    def run(self):
        exts = tuple(e for p in client_languages.LANGUAGES.values() for e in p.extensions) + (".txt", ".md", ".json")
        needle = self.text if self.case else self.text.lower()
        out, scanned, truncated = [], 0, False
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for fn in filenames:
                if self.cancelled:
                    return
                if not fn.lower().endswith(exts):
                    continue
                path = os.path.join(dirpath, fn)
                scanned += 1
                if scanned > MAX_SEARCH_FILES:
                    truncated = True
                    break
                try:
                    if os.path.getsize(path) > MAX_SEARCH_BYTES:
                        continue
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            hay = line if self.case else line.lower()
                            if needle in hay:
                                out.append((path, i, line.strip()[:160]))
                                if len(out) >= MAX_RESULTS:
                                    truncated = True
                                    break
                except OSError:
                    continue
                if len(out) >= MAX_RESULTS:
                    break
            if truncated:
                break
        if not self.cancelled:
            self.signals.finished.emit(self.search_id, out, truncated)


# ---------------------------------------------------------------------------
class _FileTree(QTreeWidget):
    fileActivated = Signal(str)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setIconSize(QSize(16, 16))
        self.setAnimated(False)
        self.setUniformRowHeights(True)
        self.root_path: str | None = None
        self.tokens = None
        self.itemExpanded.connect(self._on_expand)
        self.itemCollapsed.connect(self._on_collapse)
        self.itemActivated.connect(self._on_open)
        self.itemClicked.connect(self._on_click)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _icon_for(self, path: str, is_dir: bool, expanded: bool = False):
        t = self.tokens
        col = t.hex(t.text_muted) if t else "#999"
        if is_dir:
            return icons.icon("folder-open" if expanded else "folder", t.hex(t.accent) if t else col, 16)
        lang = client_languages.language_for_filename(path)
        if lang:
            return icons.lang_icon(lang, 15)
        return icons.icon("file", col, 16)

    def load(self, root: str):
        self.clear()
        self.root_path = root
        item = self._make_item(root, True)
        item.setText(0, os.path.basename(root.rstrip("/\\")) or root)
        self.addTopLevelItem(item)
        item.setExpanded(True)

    def _make_item(self, path: str, is_dir: bool) -> QTreeWidgetItem:
        it = QTreeWidgetItem([os.path.basename(path)])
        it.setData(0, Qt.ItemDataRole.UserRole, path)
        it.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
        it.setIcon(0, self._icon_for(path, is_dir))
        it.setToolTip(0, path)
        if is_dir:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return it

    def _populate(self, item: QTreeWidgetItem):
        if item.childCount() and item.data(0, Qt.ItemDataRole.UserRole + 2):
            return
        item.takeChildren()
        path = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name in IGNORED_DIRS or (e.name.startswith(".") and e.is_dir()):
                continue
            item.addChild(self._make_item(e.path, e.is_dir()))
        item.setData(0, Qt.ItemDataRole.UserRole + 2, True)

    def _on_expand(self, item):
        self._populate(item)
        item.setIcon(0, self._icon_for(item.data(0, Qt.ItemDataRole.UserRole), True, True))

    def _on_collapse(self, item):
        item.setIcon(0, self._icon_for(item.data(0, Qt.ItemDataRole.UserRole), True, False))

    def _on_open(self, item, _col=0):
        if not item.data(0, Qt.ItemDataRole.UserRole + 1):
            self.fileActivated.emit(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_click(self, item, _col=0):
        if item.data(0, Qt.ItemDataRole.UserRole + 1):
            item.setExpanded(not item.isExpanded())
        else:
            self.fileActivated.emit(item.data(0, Qt.ItemDataRole.UserRole))

    def filter_names(self, text: str):
        text = text.lower().strip()
        def walk(it) -> bool:
            if it.childCount() == 0:
                visible = (not text) or text in it.text(0).lower()
            else:
                visible = any([walk(it.child(i)) for i in range(it.childCount())]) or (not text)
            it.setHidden(not visible)
            return visible
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if text:
                self._expand_all(top)
            walk(top)

    def _expand_all(self, it):
        if it.data(0, Qt.ItemDataRole.UserRole + 1):
            self._populate(it)
        it.setExpanded(True)
        for i in range(it.childCount()):
            c = it.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole + 1) and c.text(0) not in IGNORED_DIRS:
                self._expand_all(c)

    def reload(self):
        if self.root_path:
            self.load(self.root_path)


class OutlineView(QListWidget):
    symbolActivated = Signal(int)

    _PATTERNS = {
        "python": re.compile(r"^(\s*)(async\s+def|def|class)\s+(\w+)"),
        "c": re.compile(r"^(?:[A-Za-z_][\w\s\*]*?[\s\*])(\w+)\s*\([^;{]*\)\s*\{?\s*$"),
        "java": re.compile(r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*"
                           r"(?:class|interface|enum|[\w<>\[\],]+)\s+(\w+)\s*(?:\([^;{]*\))?\s*(?:extends [\w.]+)?\s*\{?\s*$"),
    }

    def __init__(self):
        super().__init__()
        self.tokens = None
        self.itemClicked.connect(lambda it: self.symbolActivated.emit(it.data(Qt.ItemDataRole.UserRole)))

    def update_symbols(self, text: str, language: str):
        self.clear()
        pat = self._PATTERNS.get(language)
        if not pat:
            return
        skip = {"if", "for", "while", "switch", "return", "else", "catch", "main_"}
        for i, line in enumerate(text.split("\n"), 1):
            m = pat.match(line)
            if not m:
                continue
            if language == "python":
                kind, name = ("class" if m.group(2) == "class" else "function"), m.group(3)
                indent = len(m.group(1))
            else:
                name, indent = m.group(1), len(line) - len(line.lstrip())
                kind = "class" if re.search(r"\b(class|interface|enum)\b", line) else "function"
                if name in skip:
                    continue
            it = QListWidgetItem(("    " * min(2, indent // 4)) + name)
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setToolTip(f"Line {i}")
            if self.tokens is not None:
                it.setIcon(icons.icon("package" if kind == "class" else "bolt-outline",
                                      self.tokens.hex(self.tokens.syntax.get(
                                          "class" if kind == "class" else "function", self.tokens.accent)), 14))
            self.addItem(it)


class HistoryList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("historyList")
        self.setWordWrap(True)
        self.tokens = None

    def show_items(self, history: list[dict], show_file: bool = False):
        self.clear()
        if not history:
            it = QListWidgetItem("No AI actions yet.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(it)
            return
        t = self.tokens
        for h in history[:60]:
            if h.get("action_type") == "analyze":
                continue
            action = {"suggest_fix": "Fix suggested", "convert": "Conversion", "explain": "Explained error"}.get(
                h.get("action_type"), h.get("action_type", "action"))
            outcome = h.get("outcome") or "awaiting decision"
            conf = h.get("confidence")
            bits = [action, outcome] + ([f"{int(conf * 100)}%"] if conf is not None and h.get("action_type") != "explain" else [])
            text = " \u00b7 ".join(bits)
            if show_file:
                text += f"\n{h.get('file_path', '')}"
            it = QListWidgetItem(text)
            msg = h.get("error_message")
            it.setToolTip((msg or "") + (f"\n{h.get('timestamp', '')}" if h.get("timestamp") else ""))
            if t is not None:
                good = outcome == "accepted"
                bad = outcome == "rejected"
                name = "check-circle" if good else ("x-circle" if bad else "clock")
                col = t.success if good else (t.error if bad else t.text_muted)
                it.setIcon(icons.icon(name, col.name(), 14))
            self.addItem(it)
        if self.count() == 0:
            it = QListWidgetItem("No AI actions yet.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(it)


class _HistoryFetch(QRunnable):
    class S(QObject):
        done = Signal(list, str)

    def __init__(self, api, file_path, tag):
        super().__init__()
        self.api, self.file_path, self.tag = api, file_path, tag
        self.signals = _HistoryFetch.S()

    def run(self):
        try:
            self.signals.done.emit(self.api.history(file_path=self.file_path), self.tag)
        except Exception:
            self.signals.done.emit([], self.tag)


# ---------------------------------------------------------------------------
class SideBar(QWidget):
    openFile = Signal(str)
    openFolderRequested = Signal()
    gotoLine = Signal(int, int)
    runRequested = Signal()
    debugRequested = Signal()
    stopRequested = Signal()
    convertRequested = Signal(str)
    openResult = Signal(str, int)

    def __init__(self, api_client):
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.api_client = api_client
        self.tokens = None
        self._pool = QThreadPool.globalInstance()
        self._search_worker: _SearchWorker | None = None
        self._search_id = 0
        self._folder: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.page_index = {}
        self._build_explorer()
        self._build_search()
        self._build_history()
        self._build_run()
        self._build_convert()
        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.setInterval(500)
        self._hist_timer.timeout.connect(self._fetch_history)
        self._hist_file = "Untitled"

    def _add_page(self, key: str, widget: QWidget):
        self.page_index[key] = self.stack.addWidget(widget)

    def _title_row(self, text: str, extra: list | None = None) -> QWidget:
        w = QWidget()
        w.setFixedHeight(40)
        l = QHBoxLayout(w)
        l.setContentsMargins(16, 0, 8, 0)
        l.setSpacing(2)
        lab = QLabel(text)
        lab.setObjectName("sidebarTitle")
        l.addWidget(lab)
        l.addStretch()
        for b in extra or []:
            l.addWidget(b)
        return w

    # -- explorer ----------------------------------------------------------
    def _build_explorer(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.filter_btn = IconButton("search", "Filter files by name", 26, 15, checkable=True)
        self.refresh_btn = IconButton("refresh", "Refresh", 26, 15)
        self.open_folder_btn = IconButton("folder-open", "Open folder\u2026 (Ctrl+K Ctrl+O)", 26, 15)
        v.addWidget(self._title_row("PROJECT", [self.filter_btn, self.refresh_btn, self.open_folder_btn]))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter files\u2026")
        self.filter_edit.setVisible(False)
        self.filter_edit.setContentsMargins(12, 0, 12, 0)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(12, 0, 12, 8)
        fl.addWidget(self.filter_edit)
        self.filter_wrap = fw
        fw.setVisible(False)
        v.addWidget(fw)

        self.tree = _FileTree()
        self.empty_box = QWidget()
        eb = QVBoxLayout(self.empty_box)
        eb.setContentsMargins(16, 14, 16, 14)
        eb.setSpacing(10)
        self.empty_label = QLabel("No folder open.\nOpen a folder to browse and edit its files.")
        self.empty_label.setWordWrap(True)
        self.empty_label.setObjectName("muted")
        self.open_btn = QPushButton("Open Folder")
        self.open_btn.setObjectName("accentBtn")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(130)
        self.recent_title = QLabel("RECENT")
        self.recent_title.setObjectName("sidebarTitle")
        eb.addWidget(self.empty_label)
        eb.addWidget(self.open_btn)
        eb.addWidget(self.recent_title)
        eb.addWidget(self.recent_list)
        eb.addStretch()
        self.explorer_stack = QStackedWidget()
        self.explorer_stack.addWidget(self.empty_box)
        self.explorer_stack.addWidget(self.tree)
        v.addWidget(self.explorer_stack, stretch=1)

        self.outline = OutlineView()
        self.outline_section = CollapsibleSection("OUTLINE", self.outline, expanded=False, body_height=150)
        self.timeline = HistoryList()
        self.timeline_section = CollapsibleSection("TIMELINE", self.timeline, expanded=False, body_height=150)
        v.addWidget(self.outline_section)
        v.addWidget(self.timeline_section)

        self.filter_btn.toggled.connect(self._toggle_filter)
        self.filter_edit.textChanged.connect(self.tree.filter_names)
        self.refresh_btn.clicked.connect(self.tree.reload)
        self.open_folder_btn.clicked.connect(self.openFolderRequested)
        self.open_btn.clicked.connect(self.openFolderRequested)
        self.tree.fileActivated.connect(self.openFile)
        self.recent_list.itemClicked.connect(lambda it: self.set_folder(it.data(Qt.ItemDataRole.UserRole)))
        self.outline.symbolActivated.connect(lambda ln: self.gotoLine.emit(ln, 0))
        self.timeline_section.toggled.connect(lambda v: v and self._fetch_history())
        self._add_page("explorer", page)

    def _toggle_filter(self, on: bool):
        self.filter_wrap.setVisible(on)
        if on:
            self.filter_edit.setFocus()
        else:
            self.filter_edit.clear()

    # -- search --------------------------------------------------------------
    def _build_search(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._title_row("SEARCH"))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 0, 12, 8)
        bl.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search in folder\u2026")
        self.search_edit.returnPressed.connect(self._run_search)
        self.search_case = IconButton("case", "Match case", 26, 15, checkable=True)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.search_edit, stretch=1)
        row.addWidget(self.search_case)
        bl.addLayout(row)
        self.search_status = QLabel("Press Enter to search the open folder.")
        self.search_status.setObjectName("muted")
        self.search_status.setWordWrap(True)
        bl.addWidget(self.search_status)
        v.addWidget(box)
        self.search_results = QListWidget()
        self.search_results.itemActivated.connect(self._open_result)
        self.search_results.itemClicked.connect(self._open_result)
        v.addWidget(self.search_results, stretch=1)
        self._add_page("search", page)

    def focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _run_search(self):
        text = self.search_edit.text()
        if not text:
            return
        if not self._folder:
            self.search_status.setText("Open a folder first (Explorer \u2192 Open Folder).")
            return
        if self._search_worker:
            self._search_worker.cancelled = True
        self.search_results.clear()
        self.search_status.setText("Searching\u2026")
        self._search_id += 1
        w = _SearchWorker(self._search_id, self._folder, text, self.search_case.isChecked())
        w.signals.finished.connect(self._search_done)
        self._search_worker = w
        self._pool.start(w)

    def _search_done(self, search_id: int, results, truncated):
        if search_id != self._search_id:
            return      # superseded by a newer search
        self.search_results.clear()
        files = {r[0] for r in results}
        msg = f"{len(results)} result{'s' if len(results) != 1 else ''} in {len(files)} file{'s' if len(files) != 1 else ''}"
        self.search_status.setText(msg + (" (limited \u2014 refine your search)" if truncated else ""))
        for path, ln, text in results:
            rel = os.path.relpath(path, self._folder)
            it = QListWidgetItem(f"{rel}:{ln}\n{text}")
            it.setData(Qt.ItemDataRole.UserRole, (path, ln))
            it.setToolTip(path)
            self.search_results.addItem(it)

    def _open_result(self, it):
        data = it.data(Qt.ItemDataRole.UserRole)
        if data:
            self.openResult.emit(data[0], data[1])

    # -- history ---------------------------------------------------------------
    def _build_history(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.hist_refresh = IconButton("refresh", "Refresh", 26, 15)
        v.addWidget(self._title_row("AI HISTORY", [self.hist_refresh]))
        self.history_all = HistoryList()
        v.addWidget(self.history_all, stretch=1)
        self.hist_refresh.clicked.connect(lambda: self._fetch_history(all_files=True))
        self._add_page("history", page)

    # -- run ---------------------------------------------------------------------
    def _build_run(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._title_row("RUN"))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 0, 14, 14)
        bl.setSpacing(8)
        self.run_btn = QPushButton("Run   F5")
        self.debug_btn = QPushButton("Debug   F6")
        self.stop_btn = QPushButton("Stop   Shift+F5")
        self.run_btn.setObjectName("accentBtn")
        self.debug_btn.setObjectName("ghostBtn")
        self.stop_btn.setObjectName("ghostBtn")
        self.stop_btn.setEnabled(False)
        for b in (self.run_btn, self.debug_btn, self.stop_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bl.addWidget(b)
        self.run_btn.clicked.connect(self.runRequested)
        self.debug_btn.clicked.connect(self.debugRequested)
        self.stop_btn.clicked.connect(self.stopRequested)
        info = QLabel(
            "Run compiles (C, Java) and executes the current buffer with the compilers on this machine's PATH.\n\n"
            "Debug runs it the same way, and if it crashes, reads the traceback or compiler error, jumps to the "
            "line and asks the AI for a fix.\n\n"
            "Program input goes in the stdin field in the TERMINAL tab.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        bl.addSpacing(6)
        bl.addWidget(info)
        bl.addStretch()
        v.addWidget(box, stretch=1)
        self._add_page("run", page)

    def set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.debug_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    # -- convert -------------------------------------------------------------------
    def _build_convert(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._title_row("CONVERT"))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 0, 12, 12)
        bl.setSpacing(6)
        hint = QLabel("Translate the whole file into another language. You review the result before it replaces "
                      "anything, and it can be undone with Ctrl+Z.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        bl.addWidget(hint)
        bl.addSpacing(4)
        self.convert_btns: dict[str, QPushButton] = {}
        for lid in client_languages.LANGUAGE_ORDER:
            lab = client_languages.LANGUAGES[lid].label
            b = QPushButton(f"  Convert to {lab}")
            b.setObjectName("toolRow")
            b.setIcon(icons.lang_icon(lid, 18))
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=lid: self.convertRequested.emit(t))
            self.convert_btns[lid] = b
            bl.addWidget(b)
        bl.addStretch()
        v.addWidget(box, stretch=1)
        self._add_page("convert", page)

    def set_convert_source(self, language: str):
        for lid, b in self.convert_btns.items():
            b.setEnabled(lid != language)

    # -- public API -----------------------------------------------------------------
    def show_page(self, key: str):
        self.stack.setCurrentIndex(self.page_index[key])
        if key == "history":
            self._fetch_history(all_files=True)
        if key == "search":
            self.focus_search()

    def set_folder(self, folder: str | None, recent: list[str] | None = None):
        self._folder = folder
        if folder and os.path.isdir(folder):
            self.tree.load(folder)
            self.explorer_stack.setCurrentIndex(1)
        else:
            self.explorer_stack.setCurrentIndex(0)
        if recent is not None:
            self.recent_list.clear()
            for r in recent:
                it = QListWidgetItem(os.path.basename(r.rstrip("/\\")) or r)
                it.setToolTip(r)
                it.setData(Qt.ItemDataRole.UserRole, r)
                self.recent_list.addItem(it)
            self.recent_title.setVisible(bool(recent))
            self.recent_list.setVisible(bool(recent))

    def folder(self) -> str | None:
        return self._folder

    def update_outline(self, text: str, language: str):
        self.outline.update_symbols(text, language)

    def schedule_history(self, file_path: str):
        self._hist_file = file_path
        self._hist_timer.start()

    def _fetch_history(self, all_files: bool = False):
        for tag, fp in (("timeline", self._hist_file),) + ((("all", None),) if all_files or
                                                          self.stack.currentIndex() == self.page_index["history"] else ()):
            if tag == "timeline" and not self.timeline_section.body.isVisible():
                continue
            w = _HistoryFetch(self.api_client, fp, tag)
            w.signals.done.connect(self._history_done)
            self._pool.start(w)

    def _history_done(self, items: list, tag: str):
        if tag == "timeline":
            self.timeline.show_items(items)
        else:
            self.history_all.show_items(items, show_file=True)

    def retheme(self, t):
        self.tokens = t
        self.tree.tokens = t
        self.outline.tokens = t
        self.timeline.tokens = t
        self.history_all.tokens = t
        for b in (self.filter_btn, self.refresh_btn, self.open_folder_btn, self.search_case, self.hist_refresh):
            b.retheme(t)
        self.outline_section.retheme(t)
        self.timeline_section.retheme(t)
        self.run_btn.setIcon(icons.icon("play", t.hex(t.on_accent), 14))
        self.debug_btn.setIcon(icons.icon("bug", t.hex(t.text), 14))
        self.stop_btn.setIcon(icons.icon("stop", t.hex(t.text), 13))
        self.open_btn.setIcon(icons.icon("folder-open", t.hex(t.on_accent), 16))
        for b in self.convert_btns.values():
            pass
        self.tree.reload()
        self.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; font-size: 12px; }}"
            f"QListWidget::item {{ padding: 5px 12px; margin: 0 6px; border-radius: 5px; }}"
            f"QLabel#muted {{ color: {t.hex(t.text_muted)}; font-size: 11.5px; }}")
